#!/bin/bash
# Real-device integrity and lifecycle checks. Requires the existing
# host library and configured C++ build from the DPUMesh checkout.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "${DPUMESH_ROOT:-$HERE/../../../DPUMesh-online-boutique}" && pwd)
DPU=${DPU_HOST:-192.168.100.2}
DB=${DPU_DIR:-DPUMesh-online-boutique}/ob-bench
OUT=${OUT:-$ROOT/build/hw-regression}
GRPC=${HW_GRPC_BIN:-$ROOT/build/go-bin/channel-smoke}
STREAM=${HW_STREAM_BIN:-$ROOT/build/grpc/dpumesh_stream_smoke}
mkdir -p "$OUT"
if [ -z "${HW_GRPC_BIN:-}" ]; then
    mkdir -p "$ROOT/build/go-bin"
    (cd "$ROOT/integrations/grpc/go" && go build -o "$GRPC" ./cmd/channel-smoke)
fi
if [ -z "${HW_STREAM_BIN:-}" ]; then
    cmake --build "$ROOT/build/grpc" --target dpumesh_stream_smoke -j "${HW_BUILD_JOBS:-4}" \
        > "$OUT/build-stream.log" 2>&1
fi
for bin in "$GRPC" "$STREAM"; do test -x "$bin"; done
SERVER_PID= DPU_STARTED=0 PROXY_TAG=
cleanup() {
    if [ -n "$SERVER_PID" ]; then
        kill -TERM "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    if [ "$DPU_STARTED" = 1 ]; then
        ssh -n "$DPU" "cd $DB && bash stop.sh proxy mock-identity mock-policy mock-destination" >> "$OUT/cleanup.log" 2>&1 || true
    fi
}
trap cleanup EXIT
export LD_LIBRARY_PATH=${HW_LIB_DIR:-$ROOT/build/lib}:$ROOT/build/grpc${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export DPUMESH_ENABLE=1 DPUMESH_PCI_ADDR=${DPUMESH_PCI_ADDR:-94:00.0}
export DPUMESH_SERVER=${DPUMESH_SERVER:-DPUMeshBoutique0}
export DPU_EU_BASE=${DPU_EU_BASE:-64}
export DPUMESH_BACKEND_POOL=${HW_BACKEND_POOL:-4} DPUMESH_BACKEND_MAX=${HW_BACKEND_MAX:-8}
unset DPUMESH_SERVICE DPUMESH_SERVICE_IP DPUMESH_SERVICE_PORT DPUMESH_CONFIG

start_proxy() {
    local l7=$1 tag=$2
    PROXY_TAG=$tag
    # Refuse to overwrite a live run's PID files.
    ssh -n "$DPU" "cd $DB; for n in proxy mock-identity mock-policy mock-destination; do p=\$(cat run/\$n.pid 2>/dev/null) || continue; if kill -0 \$p 2>/dev/null; then echo \"\$n already running\"; exit 1; fi; done"
    DPU_STARTED=1
    ssh -n "$DPU" "cd $DB && export OB_L7=$l7 DMESH_BUSY_POLL=1 LINKERD2_PROXY_LOG=warn DPUMESH_DPA_EU_BASE=${DPU_EU_BASE:-0} && bash start.sh mocks && sleep 2 && bash start.sh proxy hw-$tag && sleep 6 && kill -0 \$(cat run/proxy.pid)"
}
stop_proxy() {
    ssh -n "$DPU" "cd $DB && bash stop.sh proxy mock-identity mock-policy mock-destination" >> "$OUT/cleanup.log" 2>&1
    DPU_STARTED=0
    scp -q "$DPU:$DB/run/proxy-hw-$PROXY_TAG.log" "$OUT/$PROXY_TAG-proxy.log"
    if grep -Eq 'flexio_crash_data|panicked|Failed to stop dpa thread|Failed to destroy dpa thread event handler' "$OUT/$PROXY_TAG-proxy.log"; then
        echo "DPU crash or thread cleanup failure detected in $OUT/$PROXY_TAG-proxy.log" >&2
        return 1
    fi
}
wait_server() {
    local log=$1 marker=$2
    for _ in {1..100}; do
        grep -q "$marker" "$log" && return
        kill -0 "$SERVER_PID" 2>/dev/null || { cat "$log"; return 1; }
        sleep 0.1
    done
    cat "$log"
    return 1
}
stop_server() {
    kill -TERM "$SERVER_PID"
    for _ in {1..100}; do
        kill -0 "$SERVER_PID" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "server teardown exceeded 10 seconds" >&2
        kill -KILL "$SERVER_PID"
        wait "$SERVER_PID" || true
        SERVER_PID=
        return 1
    fi
    wait "$SERVER_PID"
    SERVER_PID=
}

for reverse in ${REVERSE_MODES:-dpu-dma}; do
    export DPUMESH_REVERSE=$reverse
    if [[ " ${HW_PHASES:-grpc stream} " == *" grpc "* ]]; then
    start_proxy 1 "$reverse-grpc"
    env DPUMESH_POD_IP=10.99.0.41 DPUMESH_SERVICE=localhost:18086 \
        "$GRPC" -mode server > "$OUT/$reverse-grpc-server.log" 2>&1 &
    SERVER_PID=$!
    wait_server "$OUT/$reverse-grpc-server.log" 'SERVER_READY'
    env DPUMESH_POD_IP=10.99.0.42 DPUMESH_SERVICE_IP=127.0.0.1 DPUMESH_SERVICE_PORT=18086 \
        timeout 120s "$GRPC" -mode client -rounds 40 -timeout 90s -rpc-timeout 5s \
        > "$OUT/$reverse-grpc-client.log" 2>&1
    stop_server
    stop_proxy
    echo "PASS $reverse: gRPC payloads, sibling traffic, 40 close/reopen rounds and channel recreation"
    fi

    if [[ " ${HW_PHASES:-grpc stream} " == *" stream "* ]]; then
    start_proxy 0 "$reverse-stream"
    env DPUMESH_POD_IP=10.99.0.43 DPUMESH_SERVICE=localhost:18087 \
        "$STREAM" server > "$OUT/$reverse-stream-server.log" 2>&1 &
    SERVER_PID=$!
    wait_server "$OUT/$reverse-stream-server.log" 'STREAM_SMOKE_SERVER_READY'
    for size in ${STREAM_SIZES:-64 128 129 8064 8192 65536 1048576 3145728}; do
        count=128
        [ "$size" -lt 65536 ] || count=8
        count=${STREAM_COUNT:-$count}
        env DPUMESH_POD_IP=10.99.0.44 timeout 90s \
            "$STREAM" client 127.0.0.1:18087 "$count" "$size" \
            > "$OUT/$reverse-stream-$size.log" 2>&1
    done
    clients=()
    for ((i=1; i<=${CONCURRENT_STREAMS:-4}; ++i)); do
        env DPUMESH_POD_IP=10.99.0.$((44+i)) timeout 90s \
            "$STREAM" client 127.0.0.1:18087 128 8192 \
            > "$OUT/$reverse-stream-concurrent-$i.log" 2>&1 &
        clients+=("$!")
    done
    for client in "${clients[@]}"; do wait "$client"; done
    stop_server
    grep -q 'STREAM_SMOKE_SERVER_DONE live=0' "$OUT/$reverse-stream-server.log"
    stop_proxy
    echo "PASS $reverse: every payload byte checked through 3 MiB messages, staging wraps and concurrent streams"
    fi
done
