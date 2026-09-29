#!/bin/bash
# Builds Online Boutique to run as host processes over DPUMesh, from this
# checkout and a DPUMesh checkout (DPUMESH_ROOT, default ../../DPUMesh).
# The Go services link the dmeshgo adapter (-tags dpumesh) and the other
# services their language's DPUMesh adapter; each uses it only when
# DPUMESH_ENABLE=1. Runtimes and dependencies go under dpumesh/.build. Idempotent; needs no root. Build the
# DPUMesh host library first (`make lib` in DPUMESH_ROOT).
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FORK=$(cd "$HERE/.." && pwd)
DPUMESH_ROOT=$(cd "${DPUMESH_ROOT:-$FORK/../DPUMesh}" && pwd)
SRC=$FORK/src
OUT=${OB_BUILD:-$HERE/.build}
JDK_URL=https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse
DOTNET_CHANNEL=10.0
REDIS_IMAGE=redis:7-alpine

log() { printf '[setup] %s\n' "$*"; }
mkdir -p "$OUT/bin" "$OUT/toolchains" "$OUT/logs"
[ -e "$DPUMESH_ROOT/build/lib/libdpumesh.so.5" ] || {
    echo "build the DPUMesh host library first: make -C $DPUMESH_ROOT lib" >&2; exit 1; }
# The .NET, Node.js and Java adapters load the stream library
# (integrations/grpc/README.md).
[ -e "$DPUMESH_ROOT/build/grpc/libdpumesh_stream.so" ] || {
    echo "build libdpumesh_stream.so into $DPUMESH_ROOT/build/grpc first" >&2; exit 1; }

# One workspace holds the Go services and dmeshgo, so no go.mod names a path.
GO_SERVICES="frontend checkoutservice productcatalogservice shippingservice"
{
    echo "go $(go env GOVERSION | sed 's/^go//')"
    echo "use ("
    for svc in $GO_SERVICES; do echo "	$SRC/$svc"; done
    echo "	$DPUMESH_ROOT/integrations/grpc/go"
    echo ")"
} > "$OUT/go.work"
for svc in $GO_SERVICES; do
    log "go build $svc"
    (cd "$SRC/$svc" && GOWORK=$OUT/go.work CGO_LDFLAGS="-L$DPUMESH_ROOT/build/lib" \
        go build -tags dpumesh -o "$OUT/bin/$svc" .)
done

# grpcio with gRPC over DPUMesh, built once (integrations/grpc/python).
wheel() { ls "$DPUMESH_ROOT"/build/grpcio/wheels/grpcio-1.80.0-*.whl 2>/dev/null | head -1; }
if [ -z "$(wheel)" ]; then
    log "building the DPUMesh grpcio wheel"
    bash "$DPUMESH_ROOT/integrations/grpc/python/build_wheel.sh" >/dev/null
fi
# The two services pin conflicting versions, so each gets its own venv.
for svc in emailservice recommendationservice; do
    venv=$OUT/venv/$svc
    [ -x "$venv/bin/python" ] || python3 -m venv "$venv"
    log "pip install $svc"
    "$venv/bin/pip" install -q --upgrade pip
    "$venv/bin/pip" install -q -r "$SRC/$svc/requirements.txt"
    "$venv/bin/pip" install -q --force-reinstall --no-deps "$(wheel)"
    "$venv/bin/pip" install -q --no-deps "$DPUMESH_ROOT/integrations/grpc/python"
done

log "node-gyp (DPUMesh Node.js adapter)"
(cd "$DPUMESH_ROOT/integrations/grpc/node" && npx --yes node-gyp rebuild --loglevel=error >/dev/null)
for svc in currencyservice paymentservice; do
    log "npm ci $svc"
    (cd "$SRC/$svc" && npm ci --no-audit --no-fund --loglevel=error &&
        npm install --no-save --ignore-scripts --no-audit --no-fund --loglevel=error \
            "$DPUMESH_ROOT/integrations/grpc/node")
done

JDK=$OUT/toolchains/jdk
if [ ! -x "$JDK/bin/java" ]; then
    log "downloading JDK 21"
    mkdir -p "$JDK"
    curl -fsSL "$JDK_URL" | tar -xz -C "$JDK" --strip-components=1
fi
log "gradle jar (DPUMesh Java adapter)"
(cd "$SRC/adservice" && JAVA_HOME=$JDK sh ./gradlew -q --no-daemon \
    -p "$DPUMESH_ROOT/integrations/grpc/java" jar)
log "gradle installDist (adservice)"
(cd "$SRC/adservice" && JAVA_HOME=$JDK DPUMESH_ROOT=$DPUMESH_ROOT sh ./gradlew -q installDist --no-daemon)

DOTNET=$OUT/toolchains/dotnet
if [ ! -x "$DOTNET/dotnet" ]; then
    log "installing .NET $DOTNET_CHANNEL SDK"
    curl -fsSL https://dot.net/v1/dotnet-install.sh -o "$OUT/toolchains/dotnet-install.sh"
    bash "$OUT/toolchains/dotnet-install.sh" --channel "$DOTNET_CHANNEL" --install-dir "$DOTNET" >/dev/null
fi
log "dotnet publish (cartservice)"
DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 "$DOTNET/dotnet" publish \
    "$SRC/cartservice/src/cartservice.csproj" -c Release -o "$OUT/bin/cartservice" \
    -p:DPUMESH_ROOT="$DPUMESH_ROOT" >/dev/null
"$DOTNET/dotnet" build-server shutdown >/dev/null 2>&1 || true

log "redis image"
docker image inspect "$REDIS_IMAGE" >/dev/null 2>&1 || docker pull -q "$REDIS_IMAGE" >/dev/null

log "done: $OUT"
