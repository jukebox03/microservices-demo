#!/bin/bash
# run.sh start|stop|status|smoke — Online Boutique as host processes whose
# service-to-service gRPC runs over DPUMesh. Each service is a DPUMesh "pod"
# with its own DPUMESH_POD_IP and serves a Service target
# 10.99.1.N:<service port>; clients dial those targets, and the DPU proxy
# forwards every flow to its original destination. Redis (cart) and the
# frontend's HTTP stay on kernel TCP.
#
# DPUMESH_MODE picks how the Node, Python, Java and .NET services reach the
# mesh: "preload" (default) runs them unmodified under the preload shim;
# "native" enables their DPUMesh gRPC library. The Go services use dmeshgo in
# both modes: Go makes its socket calls without libc, so preload cannot reach
# them. "tcp" is the baseline without DPUMesh: every service listens on its
# own TCP port and clients dial that port at the same 10.99.1.N address
# (TCP_HOST replaces the address, e.g. 127.0.0.1).
#
# Requires setup.sh and, except in tcp mode, a DPU proxy on DPUMESH_SERVER
# whose profile networks cover 10.99.0.0/16 (see README.md). REDIS_ADDR names
# a running Redis instead of the one run.sh starts in Docker.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FORK=$(cd "$HERE/.." && pwd)
DPUMESH_ROOT=$(cd "${DPUMESH_ROOT:-$FORK/../DPUMesh}" && pwd)
SRC=$FORK/src
OB=${OB_BUILD:-$HERE/.build}
RUN=$OB/run
LOGS=$OB/logs
LIB=$DPUMESH_ROOT/build/lib
PRELOAD=$LIB/libdpumesh_preload.so
MODE=${DPUMESH_MODE:-preload}
# The non-Go services that use their DPUMesh library: all of them in native
# mode; in preload mode, those NATIVE_SERVICES names, the rest preloaded.
NATIVE_SERVICES=${NATIVE_SERVICES:-}
FRONTEND_HTTP=${FRONTEND_HTTP:-127.0.0.1:18080}
REDIS_PORT=${REDIS_PORT:-16379}

export DPUMESH_PCI_ADDR=${DPUMESH_PCI_ADDR:-94:00.0}
export DPUMESH_SERVER=${DPUMESH_SERVER:-DPUMeshBoutique0}
export DPUMESH_REVERSE=${DPUMESH_REVERSE:-dpu-dma}
export DPUMESH_SPIN_US=${DPUMESH_SPIN_US:-0}
export LD_LIBRARY_PATH=$LIB:$DPUMESH_ROOT/build/grpc${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export DISABLE_PROFILER=1 ENABLE_TRACING=0 DISABLE_TRACING=1 DISABLE_STATS=1
POOL=${DPUMESH_BACKEND_POOL:-1}
MAX=${DPUMESH_BACKEND_MAX:-8}

# Service targets, as the clients dial them. In tcp mode a target is the
# service's own TCP port: target <ip>:<mesh port>:<tcp port>.
target() {
    local ip=$1 mesh=$2 tcp=$3
    if [ "$MODE" = tcp ]; then echo "${TCP_HOST:-$ip}:$tcp"; else echo "$ip:$mesh"; fi
}
PRODUCT=$(target 10.99.1.1 3550 3550)
CURRENCY=$(target 10.99.1.2 7000 17000)
CART=$(target 10.99.1.3 7070 17070)
RECOMMENDATION=$(target 10.99.1.4 8080 18081)
SHIPPING=$(target 10.99.1.5 50051 50051)
CHECKOUT=$(target 10.99.1.6 5050 5050)
AD=$(target 10.99.1.7 9555 19555)
EMAIL=$(target 10.99.1.8 5000 15000)
PAYMENT=$(target 10.99.1.9 50051 15051)

mkdir -p "$RUN" "$LOGS"

# launch <name> <dir> <env...> -- <command...>
launch() {
    local name=$1 dir=$2; shift 2
    local envs=()
    while [ "$1" != "--" ]; do envs+=("$1"); shift; done
    shift
    (cd "$dir" && exec env "${envs[@]}" DPUMESH_WORKLOAD="$name" "$@") > "$LOGS/$name.log" 2>&1 &
    echo $! > "$RUN/$name.pid"
    echo "started $name (pid $!)"
}

# The mesh settings of a Go program: none in tcp mode.
go_mesh() {
    [ "$MODE" = tcp ] && echo DPUMESH_ENABLE=0 || echo DPUMESH_ENABLE=1
}

# go_server <name> <pod ip> <target> <dir> <binary> [env...]
go_server() {
    local name=$1 pod=$2 target=$3 dir=$4 bin=$5; shift 5
    launch "$name" "$dir" "$(go_mesh)" DPUMESH_POD_IP="$pod" DPUMESH_SERVICE="$target" \
        DPUMESH_BACKEND_POOL="$POOL" DPUMESH_BACKEND_MAX="$MAX" PORT="${target##*:}" "$@" -- "$OB/bin/$bin"
}

# mesh_server <name> <pod ip> <target> <local port> <dir> [env...] -- <command...>
# In preload mode the shim turns the listen on <local port> into the service's
# native listener; in native mode the service's DPUMesh library serves it.
mesh_server() {
    local name=$1 pod=$2 target=$3 port=$4 dir=$5; shift 5
    local via=(LD_PRELOAD="$PRELOAD" DPUMESH_PORT="$port")
    if [ "$MODE" = tcp ]; then
        via=(DPUMESH_ENABLE=0)
    elif [ "$MODE" = native ] || [[ " $NATIVE_SERVICES " == *" $name "* ]]; then
        via=(DPUMESH_ENABLE=1)
    fi
    launch "$name" "$dir" "${via[@]}" DPUMESH_POD_IP="$pod" DPUMESH_SERVICE="$target" \
        PORT="$port" DPUMESH_BACKEND_POOL="$POOL" DPUMESH_BACKEND_MAX="$MAX" "$@"
}

start() {
    case "$MODE" in
        preload | native | tcp) ;;
        *) echo "DPUMESH_MODE must be preload, native or tcp" >&2; return 2 ;;
    esac
    echo "mode: $MODE${NATIVE_SERVICES:+ (native: $NATIVE_SERVICES)}"
    if [ -z "${REDIS_ADDR:-}" ]; then
        docker run -d --rm --name ob-redis -p 127.0.0.1:$REDIS_PORT:6379 redis:7-alpine >/dev/null 2>&1 \
            && echo "started redis on 127.0.0.1:$REDIS_PORT" || echo "redis already running?"
    fi

    go_server productcatalogservice 10.99.0.11 $PRODUCT "$SRC/productcatalogservice" productcatalogservice
    mesh_server currencyservice 10.99.0.12 $CURRENCY 17000 "$SRC/currencyservice" -- node server.js
    mesh_server cartservice 10.99.0.13 $CART 17070 "$OB/bin/cartservice" \
        REDIS_ADDR="${REDIS_ADDR:-127.0.0.1:$REDIS_PORT}" ASPNETCORE_URLS=http://+:17070 DOTNET_CLI_TELEMETRY_OPTOUT=1 \
        -- "$OB/toolchains/dotnet/dotnet" cartservice.dll
    go_server shippingservice 10.99.0.15 $SHIPPING "$SRC/shippingservice" shippingservice
    mesh_server adservice 10.99.0.17 $AD 19555 "$SRC/adservice" JAVA_HOME="$OB/toolchains/jdk" \
        -- "$SRC/adservice/build/install/hipstershop/bin/AdService"
    mesh_server emailservice 10.99.0.18 $EMAIL 15000 "$SRC/emailservice" \
        -- "$OB/venv/emailservice/bin/python" email_server.py
    mesh_server paymentservice 10.99.0.19 $PAYMENT 15051 "$SRC/paymentservice" -- node index.js
    sleep "${SERVER_WARMUP:-8}"

    mesh_server recommendationservice 10.99.0.14 $RECOMMENDATION 18081 "$SRC/recommendationservice" \
        DPUMESH_TARGETS=$PRODUCT PRODUCT_CATALOG_SERVICE_ADDR=$PRODUCT \
        -- "$OB/venv/recommendationservice/bin/python" recommendation_server.py
    go_server checkoutservice 10.99.0.16 $CHECKOUT "$SRC/checkoutservice" checkoutservice \
        PRODUCT_CATALOG_SERVICE_ADDR=$PRODUCT SHIPPING_SERVICE_ADDR=$SHIPPING PAYMENT_SERVICE_ADDR=$PAYMENT \
        EMAIL_SERVICE_ADDR=$EMAIL CURRENCY_SERVICE_ADDR=$CURRENCY CART_SERVICE_ADDR=$CART
    sleep "${CLIENT_WARMUP:-4}"

    launch frontend "$SRC/frontend" "$(go_mesh)" DPUMESH_POD_IP=10.99.0.20 \
        LISTEN_ADDR="${FRONTEND_HTTP%:*}" PORT="${FRONTEND_HTTP##*:}" \
        PRODUCT_CATALOG_SERVICE_ADDR=$PRODUCT CURRENCY_SERVICE_ADDR=$CURRENCY CART_SERVICE_ADDR=$CART \
        RECOMMENDATION_SERVICE_ADDR=$RECOMMENDATION SHIPPING_SERVICE_ADDR=$SHIPPING \
        CHECKOUT_SERVICE_ADDR=$CHECKOUT AD_SERVICE_ADDR=$AD SHOPPING_ASSISTANT_SERVICE_ADDR=127.0.0.1:1 \
        -- "$OB/bin/frontend"
}

# Clients first, so no server departs under a live stream.
ORDER="frontend checkoutservice recommendationservice paymentservice emailservice adservice
       shippingservice cartservice currencyservice productcatalogservice"

stop() {
    for name in $ORDER; do
        local f=$RUN/$name.pid
        [ -f "$f" ] || continue
        local pid; pid=$(cat "$f")
        if kill -TERM "$pid" 2>/dev/null; then
            for _ in $(seq 1 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
            kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
            echo "stopped $name"
        fi
        rm -f "$f"
    done
    [ -n "${REDIS_ADDR:-}" ] || { docker rm -f ob-redis >/dev/null 2>&1 && echo "stopped redis" || true; }
}

status() {
    for name in $ORDER; do
        local f=$RUN/$name.pid state=down
        [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null && state="up (pid $(cat "$f"))"
        printf '%-24s %s\n' "$name" "$state"
    done
}

# smoke: the home page, a product page, add to cart, view cart, place an order.
smoke() {
    local base=http://$FRONTEND_HTTP jar
    jar=$(mktemp)
    local fail=0
    check() {
        local what=$1 code; shift
        code=$(curl -s -o /dev/null -w '%{http_code}' -b "$jar" -c "$jar" --max-time 20 "$@")
        printf '%-14s HTTP %s\n' "$what" "$code"
        [ "$code" = 200 ] || [ "$code" = 302 ] || fail=1
    }
    check home "$base/"
    check product "$base/product/OLJCESPC7Z"
    check add-to-cart -X POST -d product_id=OLJCESPC7Z -d quantity=2 "$base/cart"
    check cart "$base/cart"
    check checkout -X POST "$base/cart/checkout" \
        -d email=someone@example.com -d street_address="1600 Amphitheatre Parkway" -d zip_code=94043 \
        -d city="Mountain View" -d state=CA -d country="United States" \
        -d credit_card_number=4432801561520454 -d credit_card_expiration_month=1 \
        -d credit_card_expiration_year=2039 -d credit_card_cvv=672
    rm -f "$jar"
    return $fail
}

case "${1:-}" in
    start) start ;;
    stop) stop ;;
    status) status ;;
    smoke) smoke ;;
    *) echo "usage: $0 start|stop|status|smoke" >&2; exit 2 ;;
esac
