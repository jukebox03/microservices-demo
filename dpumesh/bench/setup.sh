#!/bin/bash
# setup.sh: the tools perf.sh uses, under dpumesh/.build/bench. Run it after
# dpumesh/setup.sh. Idempotent; needs no root.
#  - Locust, pinned in requirements.txt, in a venv
#  - health-bench from DPUMesh (integrations/grpc/go/cmd/health-bench)
#  - for the hostproxy baseline, DPUMesh's linkerd2-proxy submodule built
#    without doca, its mock control plane, and libsomark.so
#  - Redis 7 taken out of the redis:7-alpine image and run through its musl
#    loader, so it can start inside perf.sh's network namespace
#  - dpu/ and cpusample.py, copied to <DPU_DIR>/ob-bench on the DPU
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FORK=$(cd "$HERE/../.." && pwd)
DPUMESH_ROOT=$(cd "${DPUMESH_ROOT:-$FORK/../DPUMesh}" && pwd)
OB=${OB_BUILD:-$HERE/../.build}
BB=$OB/bench
DPU=${DPU_HOST:-192.168.100.2}
DPU_DIR=${DPU_DIR:-DPUMesh-online-boutique}
REDIS_IMAGE=redis:7-alpine

log() { printf '[bench setup] %s\n' "$*"; }
mkdir -p "$BB"

log "Locust venv"
[ -x "$BB/locust-venv/bin/python" ] || python3 -m venv "$BB/locust-venv"
"$BB/locust-venv/bin/pip" install -q --upgrade pip
"$BB/locust-venv/bin/pip" install -q -r "$HERE/requirements.txt"

log "health-bench"
(cd "$DPUMESH_ROOT/integrations/grpc/go" && CGO_LDFLAGS="-L$DPUMESH_ROOT/build/lib" \
    go build -o "$BB/health-bench" ./cmd/health-bench)

log "linkerd2-proxy without doca, and the mock control plane (hostproxy)"
(cd "$DPUMESH_ROOT/linkerd2-proxy" &&
    export RUSTFLAGS="--cfg tokio_unstable -C target-cpu=native" CARGO_TARGET_DIR=$BB/hostproxy-target &&
    cargo build -q --release -p linkerd2-proxy --no-default-features --features allow-loopback &&
    cargo build -q --release -p linkerd-app-integration --bin mock-identity --bin mock-destination --bin mock-policy)
cc -O2 -shared -fPIC -o "$BB/libsomark.so" "$HERE/somark.c" -ldl

if [ ! -x "$BB/redis/redis-server" ]; then
    log "Redis from $REDIS_IMAGE"
    mkdir -p "$BB/redis"
    docker image inspect "$REDIS_IMAGE" >/dev/null 2>&1 || docker pull -q "$REDIS_IMAGE" >/dev/null
    cid=$(docker create "$REDIS_IMAGE")
    for f in /usr/local/bin/redis-server /lib/ld-musl-x86_64.so.1 /usr/lib/libssl.so.3 /usr/lib/libcrypto.so.3; do
        docker cp -L "$cid:$f" "$BB/redis/" >/dev/null
    done
    docker rm "$cid" >/dev/null
fi

log "DPU scripts to $DPU:$DPU_DIR/ob-bench"
ssh -n "$DPU" "mkdir -p $DPU_DIR/ob-bench"
scp -q "$HERE"/dpu/*.sh "$HERE/cpusample.py" "$DPU:$DPU_DIR/ob-bench/"
log "done: $BB (build the DPU proxy with: ssh $DPU bash $DPU_DIR/ob-bench/build.sh)"
