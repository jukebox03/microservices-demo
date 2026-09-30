#!/bin/bash
# perf.sh <mode> <tag>: one Online Boutique performance run (README.md).
#   tcp        no mesh: every service on its own TCP port
#   hostproxy  TCP through one linkerd2-proxy on the host (L7, one worker),
#              with the DPU proxy's mock control plane and a sidecar-style
#              iptables redirect
#   preload    DPUMesh, the preload shim for the non-Go services (DPU proxy, L7)
#   native     DPUMesh, each language's DPUMesh gRPC library (DPU proxy, L7)
# The host side runs in one rootless network namespace whose loopback carries
# 10.99.1.1-9, so the kernel TCP paths are the same in every mode. Phases:
# Locust closed loop at each USERS_LIST level, then health-bench with 1 and 64
# calls in flight on every service. Per-thread CPU and context switches are
# sampled around each window. Results go to $OUT/<tag>/, summary.txt first.
#
# Knobs: USERS_LIST ("8 32 128"; empty skips Locust), LDUR (40 s a level),
# LOCUST_PROCS (4), SKIP_BENCH=1, SKIP_M64=1, M1_WARM/M1_DUR (2s/8s),
# DPU_BUSY_POLL (1), DPU_HOST, DPU_DIR, OUT.
set -uo pipefail
MODE=${1:?mode} TAG=${2:?tag}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FORK=$(cd "$HERE/../.." && pwd)
DPUMESH_ROOT=$(cd "${DPUMESH_ROOT:-$FORK/../DPUMesh}" && pwd)
OB=${OB_BUILD:-$HERE/../.build}
BB=$OB/bench
E=${OUT:-$BB/results}/$TAG
DPU=${DPU_HOST:-192.168.100.2}
DB=${DPU_DIR:-DPUMesh-online-boutique}/ob-bench
USERS_LIST=${USERS_LIST-"8 32 128"}
LDUR=${LDUR:-40}
RUN=$OB/run
CPU="python3 $HERE/cpusample.py"
STATS="python3 $HERE/proxystats.py"
LOCUST=$BB/locust-venv/bin/locust
HP=$BB/hostproxy-target/release
RM=$BB/redis
SERVICES="frontend productcatalogservice currencyservice cartservice recommendationservice shippingservice checkoutservice adservice emailservice paymentservice"
export DPUMESH_ROOT

case $MODE in
    tcp | hostproxy)
        OB_MODE=tcp DPU_PROXY=0
        TARGETS=10.99.1.2:17000,10.99.1.9:15051,10.99.1.3:17070,10.99.1.7:19555,10.99.1.8:15000,10.99.1.4:18081,10.99.1.1:3550,10.99.1.5:50051,10.99.1.6:5050
        BENCH_ENV=(DPUMESH_ENABLE=0) ;;
    preload | native)
        OB_MODE=$MODE DPU_PROXY=1
        TARGETS=10.99.1.2:7000,10.99.1.9:50051,10.99.1.3:7070,10.99.1.7:9555,10.99.1.8:5000,10.99.1.4:8080,10.99.1.1:3550,10.99.1.5:50051,10.99.1.6:5050
        BENCH_ENV=(DPUMESH_ENABLE=1 DPUMESH_PCI_ADDR=${DPUMESH_PCI_ADDR:-94:00.0}
                   DPUMESH_SERVER=${DPUMESH_SERVER:-DPUMeshBoutique0} DPUMESH_REVERSE=${DPUMESH_REVERSE:-dpu-dma}
                   DPUMESH_POD_IP=10.99.0.30 LD_LIBRARY_PATH=$DPUMESH_ROOT/build/lib) ;;
    *) echo "usage: $0 tcp|hostproxy|preload|native <tag>" >&2; exit 2 ;;
esac
for f in "$LOCUST" "$BB/health-bench" "$RM/redis-server"; do
    [ -x "$f" ] || { echo "missing $f: run $HERE/setup.sh" >&2; exit 1; }
done
rm -rf "$E"; mkdir -p "$E"
log() { echo "[$(date +%T)] $*" | tee -a "$E/run.log"; }
log "mode $MODE, users '$USERS_LIST', ldur $LDUR, fork $(git -C "$FORK" rev-parse --short HEAD), DPUMesh $(git -C "$DPUMESH_ROOT" rev-parse --short HEAD)"

# --- network namespace -------------------------------------------------------
unshare -Urn sleep infinity &
NS=$!
sleep 0.3
ns() { nsenter -t $NS -U -n --preserve-credentials "$@"; }
# Background processes exec through nsenter so $! is the process itself.
NSX="nsenter -t $NS -U -n --preserve-credentials"
ns sh -c 'ip link set lo up; for i in $(seq 1 9); do ip addr add 10.99.1.$i/32 dev lo; done'
$NSX "$RM/ld-musl-x86_64.so.1" --library-path "$RM" "$RM/redis-server" --port 16379 --bind 127.0.0.1 \
    --save '' --appendonly no > "$E/redis.log" 2>&1 &
REDIS=$!

# --- proxy -------------------------------------------------------------------
HPROXY=
if [ "$MODE" = hostproxy ]; then
    # Like linkerd-init: redirect the service addresses to the outbound
    # listener, except the proxy's own connections (SO_MARK from libsomark).
    ns iptables -t nat -A OUTPUT -p tcp -d 10.99.1.0/24 -m mark ! --mark 0x2102 -j REDIRECT --to-ports 17140
    (
        export LINKERD2_PROXY_ROOT=$DPUMESH_ROOT/linkerd2-proxy
        source "$LINKERD2_PROXY_ROOT/scripts/dev-proxy-env.sh" >/dev/null
        export MOCK_IDENTITY_ADDR=127.0.0.1:17088 MOCK_POLICY_ADDR=127.0.0.1:17087 MOCK_DESTINATION_ADDR=127.0.0.1:17089
        export MOCK_POLICY_ECHO_TARGET=1
        export LINKERD2_PROXY_IDENTITY_SVC_ADDR=127.0.0.1:17088 LINKERD2_PROXY_DESTINATION_SVC_ADDR=127.0.0.1:17089 LINKERD2_PROXY_POLICY_SVC_ADDR=127.0.0.1:17087
        export LINKERD2_PROXY_POLICY_WORKLOAD=boutique-e2e
        export LINKERD2_PROXY_OUTBOUND_LISTEN_ADDR=127.0.0.1:17140 LINKERD2_PROXY_INBOUND_LISTEN_ADDR=127.0.0.1:17143
        export LINKERD2_PROXY_ADMIN_LISTEN_ADDR=127.0.0.1:17191 LINKERD2_PROXY_CONTROL_LISTEN_ADDR=127.0.0.1:17190
        export LINKERD2_PROXY_INBOUND_DEFAULT_POLICY=all-unauthenticated
        export LINKERD2_PROXY_LOG=info LINKERD2_PROXY_CORES=1
        export LINKERD2_PROXY_DESTINATION_PROFILE_NETWORKS=127.0.0.0/8,10.99.0.0/16
        for m in mock-identity mock-policy mock-destination; do
            $NSX taskset -c "${HOST_MOCK_CPUS:-33}" "$HP/$m" > "$E/$m.log" 2>&1 &
            echo $! > "$E/$m.pid"
        done
        sleep 2
        $NSX env LD_PRELOAD="$BB/libsomark.so" taskset -c "${HOST_PROXY_CPUS:-34,35}" "$HP/linkerd2-proxy" > "$E/proxy.log" 2>&1 &
        echo $! > "$E/proxy.pid"
    )
    sleep 4
    HPROXY=$(cat "$E/proxy.pid")
    kill -0 "$HPROXY" || { log "host proxy failed"; exit 1; }
elif [ $DPU_PROXY = 1 ]; then
    ssh -n "$DPU" "cd $DB && export DMESH_BUSY_POLL=${DPU_BUSY_POLL:-1} OB_L7=1 && bash start.sh mocks && sleep 2 && bash start.sh proxy perf-$TAG && sleep 6 && kill -0 \$(cat run/proxy.pid)" \
        || { log "DPU start failed"; exit 1; }
fi

# --- services ------------------------------------------------------------------
ns env DPUMESH_MODE=$OB_MODE REDIS_ADDR=127.0.0.1:16379 bash "$FORK/dpumesh/run.sh" start > "$E/start.log" 2>&1
sleep 6
ns bash "$FORK/dpumesh/run.sh" status > "$E/status.txt"
log "$(grep -c 'up (' "$E/status.txt") services up"
for s in $SERVICES; do
    echo "$s $(grep -o -E 'libdpumesh[_a-z]*\.so[.0-9]*|dpumesh_grpc\.node|libdpumesh_jni[0-9]*\.so|Dpumesh\.Grpc\.dll|cygrpc[^/ ]*\.so' "/proc/$(cat "$RUN/$s.pid")/maps" 2>/dev/null | sort -u | tr '\n' ' ')"
done > "$E/libs.txt"
ns bash "$FORK/dpumesh/run.sh" smoke > "$E/smoke.txt" 2>&1 && log "smoke PASS" || log "smoke FAIL"

pids() {
    for s in $SERVICES; do echo "$s=$(cat "$RUN/$s.pid")"; done
    [ -n "$HPROXY" ] && echo "hostproxy=$HPROXY"
}
snap() {  # snap <name>
    $CPU snap "$E/cpu-$1.json" $(pids)
    [ $DPU_PROXY = 1 ] && ssh -n "$DPU" "cd $DB && python3 cpusample.py snap /tmp/ob-bench-dpu-$1.json dpuproxy=\$(cat run/proxy.pid)"
    return 0
}
dpu_diff() {  # dpu_diff <before> <after> [calls]
    [ $DPU_PROXY = 1 ] || return 0
    ssh -n "$DPU" "cd $DB && python3 cpusample.py diff /tmp/ob-bench-dpu-$1.json /tmp/ob-bench-dpu-$2.json ${3:-}" | tail -n +2
}
metrics() {
    if [ -n "$HPROXY" ]; then ns curl -s --max-time 5 http://127.0.0.1:17191/metrics
    elif [ $DPU_PROXY = 1 ]; then ssh -n "$DPU" 'curl -s --max-time 5 http://127.0.0.1:17191/metrics'; fi
}

# --- phase A: Locust -------------------------------------------------------------
export OB_LOCUST_DIR=$FORK/src/loadgenerator
locust() {  # locust <users> <seconds> [args...]
    ns "$LOCUST" -f "$HERE/locust_closed.py" --headless --processes "${LOCUST_PROCS:-4}" \
        -u "$1" -r "$1" -t "$2s" --host http://127.0.0.1:18080 --only-summary "${@:3}"
}
[ -z "$USERS_LIST" ] || locust 32 15 > "$E/locust-warmup.log" 2>&1
for U in $USERS_LIST; do
    metrics > "$E/metrics-u$U-before.txt"
    snap u$U-a
    ns /usr/bin/time -f "LOCUST_CPU user=%U sys=%S elapsed=%e" "$LOCUST" -f "$HERE/locust_closed.py" --headless \
        --processes "${LOCUST_PROCS:-4}" -u "$U" -r "$U" -t "${LDUR}s" --host http://127.0.0.1:18080 \
        --only-summary --csv "$E/locust-u$U" > "$E/locust-u$U.log" 2>&1
    snap u$U-b
    metrics > "$E/metrics-u$U-after.txt"
    set -- $(python3 -c "
import csv
for r in csv.DictReader(open('$E/locust-u${U}_stats.csv')):
    if r['Name'] == 'Aggregated':
        print(r['Request Count'], r['Requests/s'], r['50%'], r['95%'], r['99%'], r['Failure Count'])")
    { echo "== users=$U: frontend req/s=$2 requests=$1 p50=$3ms p95=$4ms p99=$5ms failures=$6"
      grep LOCUST_CPU "$E/locust-u$U.log"
      $STATS reqs "$E/metrics-u$U-before.txt" "$E/metrics-u$U-after.txt" "$LDUR"
      $STATS lat "$E/metrics-u$U-before.txt" "$E/metrics-u$U-after.txt"
      $CPU diff "$E/cpu-u$U-a.json" "$E/cpu-u$U-b.json" "$1" | tail -n +2
      dpu_diff u$U-a u$U-b "$1"; } | tee -a "$E/summary.txt"
done

# --- phases B and C: health-bench on every service ---------------------------------
bench() {  # bench <tag> <in flight> <warm> <dur>
    local tag=$1 out=$E/bench-$1.txt
    $NSX env "${BENCH_ENV[@]}" "$BB/health-bench" -targets "$TARGETS" -m "$2" -warm "$3" -dur "$4" > "$out" 2>&1 &
    local bp=$! seen=0 lines
    while kill -0 $bp 2>/dev/null; do
        lines=$(wc -l < "$out")
        while [ $seen -lt "$lines" ]; do
            seen=$((seen + 1))
            set -- $(sed -n "${seen}p" "$out")
            case "${1:-}" in
                MEASURE_START) snap "$tag-${2//[:.]/_}-a" ;;
                MEASURE_END) snap "$tag-${2//[:.]/_}-b" ;;
            esac
        done
        sleep 0.05
    done
    wait $bp
    echo "bench exit=$?" >> "$out"
    echo "== health-bench $tag" | tee -a "$E/summary.txt"
    grep ^RESULT "$out" | while read -r _ kv; do
        local t calls
        t=$(echo "$kv" | grep -o 'target=[^ ]*' | cut -d= -f2)
        calls=$(echo "$kv" | grep -o ' calls=[^ ]*' | cut -d= -f2)
        echo "RESULT $kv"
        $CPU diff "$E/cpu-$tag-${t//[:.]/_}-a.json" "$E/cpu-$tag-${t//[:.]/_}-b.json" "$calls" | tail -n +2 \
            | awk '$2 > 0.02 || /total/'
        dpu_diff "$tag-${t//[:.]/_}-a" "$tag-${t//[:.]/_}-b" "$calls"
    done | tee -a "$E/summary.txt"
}
if [ "${SKIP_BENCH:-0}" != 1 ]; then
    bench m1 1 "${M1_WARM:-2s}" "${M1_DUR:-8s}"
    [ "${SKIP_M64:-0}" = 1 ] || bench m64 64 3s 10s
fi

# --- teardown --------------------------------------------------------------------
metrics > "$E/metrics-end.txt"
ns bash "$FORK/dpumesh/run.sh" stop > "$E/stop.log" 2>&1
pgrep -u "$(id -u)" -f 'Roslyn/[b]incore' | xargs -r kill
kill $REDIS 2>/dev/null
if [ -n "$HPROXY" ]; then
    kill "$HPROXY" $(cat "$E"/mock-*.pid) 2>/dev/null
    echo "hostproxy: WARN=$(grep -c ' WARN ' "$E/proxy.log") ERROR=$(grep -c ' ERROR ' "$E/proxy.log")" | tee -a "$E/summary.txt"
fi
if [ $DPU_PROXY = 1 ]; then
    sleep 6
    ssh -n "$DPU" "cd $DB; L=run/proxy-perf-$TAG.log; echo \"dpuproxy: ERR=\$(grep -c '\]\[ERR\]' \$L) crash=\$(grep -c flexio_crash_data \$L) panics=\$(grep -c -i panicked \$L)\"; bash stop.sh proxy mock-identity mock-policy mock-destination >/dev/null" | tee -a "$E/summary.txt"
    scp -q "$DPU:$DB/run/proxy-perf-$TAG.log" "$E/" 2>/dev/null
fi
kill $NS
cp "$OB"/logs/*.log "$E/" 2>/dev/null
log "done: $E"
