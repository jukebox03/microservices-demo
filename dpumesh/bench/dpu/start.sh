#!/bin/bash
# start.sh mocks | proxy <tag>: start the mock control plane or the proxy in
# the background (PROXY_CPUS, MOCK_CPUS pin them). The proxy logs to
# run/proxy-<tag>.log.
set -eu
source "$(dirname "$0")/env.sh"
cd "$P"
case "$1" in
    mocks)
        for m in mock-identity mock-policy mock-destination; do
            nohup taskset -c "${MOCK_CPUS:-12}" target/release/$m > "$R/$m.log" 2>&1 < /dev/null &
            echo $! > "$R/$m.pid"
        done ;;
    proxy)
        nohup taskset -c "${PROXY_CPUS:-9,12}" target/release/linkerd2-proxy > "$R/proxy-$2.log" 2>&1 < /dev/null &
        echo $! > "$R/proxy.pid" ;;
    *) echo "usage: $0 mocks | proxy <tag>" >&2; exit 2 ;;
esac
