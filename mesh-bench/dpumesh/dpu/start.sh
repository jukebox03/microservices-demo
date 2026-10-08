#!/bin/bash
# start.sh mocks | proxy <tag> | stop: the mock control plane and the proxy.
# The proxy process gets all 16 DPU cores; once its shards exist, shard i is
# pinned to CPU SHARD_BASE+i (W=14: CPUs 2-15) and the remaining threads to
# MAIN_CPUS (0-1).
set -u
source "$(dirname "$0")/env.sh"
cd "$P"
SHARD_BASE=${SHARD_BASE:-2} SHARD_CPUS=${SHARD_CPUS:-$DMESH_NUM_WORKERS} MAIN_CPUS=${MAIN_CPUS:-0-1}
case "$1" in
    mocks)
        for m in mock-identity mock-policy mock-destination; do
            nohup taskset -c "${MOCK_CPUS:-0}" target/release/$m > "$R/$m.log" 2>&1 < /dev/null &
            echo $! > "$R/$m.pid"
        done ;;
    proxy)
        # As root: since 2026-10-04 a non-root process on this DPU may not
        # list representors (doca_caps: rep_filter_net unsupported).
        echo "${SUDO_PW:-}" | sudo -S -p '' -v
        KEEP_MOCKS=1 "$B/start.sh" stop  # a leftover proxy keeps the Comch names registered
        sudo -E nohup taskset -c "${PROXY_CPUS:-0-15}" target/release/linkerd2-proxy > "$R/proxy-$2.log" 2>&1 < /dev/null &
        for _ in $(seq 1 50); do pid=$(pgrep -nx linkerd2-proxy); [ -n "$pid" ] && break; sleep 0.1; done
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
            # The proxy's own affinity calls leave threads this user may not
            # re-pin, so pinning needs root (SUDO_PW from the caller).
            echo "${SUDO_PW:-}" | sudo -S -p '' taskset -pc "$cpu" "$tid" >/dev/null
        done
        echo "proxy $pid: $(grep -l '^dmesh-shard' /proc/$pid/task/*/comm | wc -l) shards pinned from CPU $SHARD_BASE" ;;
    stop)
        echo "${SUDO_PW:-}" | sudo -S -p '' -v 2>/dev/null
        if pgrep -x linkerd2-proxy >/dev/null; then
            sudo pkill -TERM -x linkerd2-proxy
            for _ in $(seq 1 40); do pgrep -x linkerd2-proxy >/dev/null || break; sleep 0.5; done
            pgrep -x linkerd2-proxy >/dev/null && { sudo pkill -KILL -x linkerd2-proxy; sleep 1; }
        fi
        rm -f "$R/proxy.pid"
        # The mock identity's certificate is valid for 24 h from its start, so
        # the mocks restart with every run (mocks), not with the proxy.
        [ "${KEEP_MOCKS:-0}" = 1 ] && exit 0
        for n in mock-identity mock-policy mock-destination; do
            p=$(cat "$R/$n.pid" 2>/dev/null) || continue
            kill -TERM "$p" 2>/dev/null; rm -f "$R/$n.pid"
        done ;;
    *) echo "usage: $0 mocks | proxy <tag> | stop" >&2; exit 2 ;;
esac
