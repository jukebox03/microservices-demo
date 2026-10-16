#!/bin/bash
# start.sh mocks | proxy <tag> | stop: the mock control plane and the proxy, on
# jet2's shared DPU. As ../dpu/start.sh, but the proxy is found and stopped by
# its own PID only (the DPU runs other users' processes of the same name).
# The proxy process gets all 16 DPU cores; once its shards exist, shard i is
# pinned to CPU SHARD_BASE+i (W=14: CPUs 2-15) and the remaining threads to
# MAIN_CPUS (0-1).
set -u
source "$(dirname "$0")/env.sh"
cd "$P"
BIN=$P/target/release/linkerd2-proxy
# sudo with the password on stdin every time: on this DPU a validated sudo
# timestamp does not carry over to the next sudo call
S() { echo "${SUDO_PW:-}" | sudo -S -p '' "$@"; }
SHARD_BASE=${SHARD_BASE:-2} SHARD_CPUS=${SHARD_CPUS:-$DMESH_NUM_WORKERS} MAIN_CPUS=${MAIN_CPUS:-0-1}
case "$1" in
    mocks)
        for m in mock-identity mock-policy mock-destination; do
            nohup taskset -c "${MOCK_CPUS:-0}" target/release/$m > "$R/$m.log" 2>&1 < /dev/null &
            echo $! > "$R/$m.pid"
        done ;;
    proxy)
        # As root: a non-root process on this DPU may not list representors.
        KEEP_MOCKS=1 "$B/start.sh" stop  # a leftover proxy of ours keeps the Comch names registered
        S -E nohup taskset -c "${PROXY_CPUS:-0-15}" "$BIN" > "$R/proxy-$2.log" 2>&1 &
        pid=
        for _ in $(seq 1 50); do pid=$(pgrep -nf "^$BIN\$"); [ -n "$pid" ] && break; sleep 0.1; done
        echo $pid > "$R/proxy.pid"
        for _ in $(seq 1 100); do
            [ "$(grep -l '^dmesh-shard' /proc/$pid/task/*/comm 2>/dev/null | wc -l)" -ge "$DMESH_NUM_WORKERS" ] && break
            sleep 0.2
        done
        for c in /proc/$pid/task/*/comm; do
            tid=$(basename "$(dirname "$c")") name=$(cat "$c")
            case $name in
                dmesh-shard-*) cpu=$((SHARD_BASE + ${name#dmesh-shard-} % SHARD_CPUS)) ;;
                *) cpu=$MAIN_CPUS ;;
            esac
            S taskset -pc "$cpu" "$tid" >/dev/null
        done
        # Return once every worker serves (pools are created one after another,
        # then the DMESH_DPA_MUX threads; about 30 s for 14 workers).
        t0=$(date +%s)
        for _ in $(seq 1 600); do
            pools=$(grep -c 'Created DPA thread pool' "$R/proxy-$2.log")
            muxes=$(grep -c 'DPA mux: .* threads on worker' "$R/proxy-$2.log")
            [ "$pools" -ge "$DMESH_NUM_WORKERS" ] &&
                { [ "${DMESH_DPA_MUX:-0}" = 0 ] || [ "$muxes" -ge "$DMESH_NUM_WORKERS" ]; } && break
            sleep 0.2
        done
        sleep 1
        echo "proxy $pid: $(grep -l '^dmesh-shard' /proc/$pid/task/*/comm | wc -l) shards pinned from CPU $SHARD_BASE," \
             "$pools DPA pools and $muxes mux workers ready after $(( $(date +%s) - t0 )) s" ;;
    stop)
        pid=$(cat "$R/proxy.pid" 2>/dev/null)
        if [ -n "$pid" ] && [ "$(S readlink /proc/$pid/exe 2>/dev/null)" = "$BIN" ]; then
            S kill -TERM "$pid"
            for _ in $(seq 1 40); do S kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
            S kill -0 "$pid" 2>/dev/null && { S kill -KILL "$pid"; sleep 1; }
            S kill -0 "$pid" 2>/dev/null && echo "proxy $pid still running" || echo "proxy $pid stopped"
        fi
        rm -f "$R/proxy.pid"
        [ "${KEEP_MOCKS:-0}" = 1 ] && exit 0
        for n in mock-identity mock-policy mock-destination; do
            p=$(cat "$R/$n.pid" 2>/dev/null) || continue
            kill -TERM "$p" 2>/dev/null; rm -f "$R/$n.pid"
        done ;;
    *) echo "usage: $0 mocks | proxy <tag> | stop" >&2; exit 2 ;;
esac
