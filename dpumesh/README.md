# Online Boutique over DPUMesh

This branch runs Online Boutique as host processes whose service-to-service
gRPC goes over [DPUMesh](https://github.com/youngmin-kaist/DPUMesh): each
connection is a PCIe DMA stream to the linkerd2-proxy on the BlueField DPU,
which forwards it to the destination service. The browser-to-frontend HTTP
and cartservice's Redis stay on kernel TCP.

`DPUMESH_MODE` picks how the Node.js, Python, Java and .NET services reach the
mesh:

- `preload` (default): the services run unmodified under DPUMesh's
  `LD_PRELOAD` shim, which turns their sockets into DPUMesh streams.
- `native`: each uses its language's DPUMesh gRPC library
  (`integrations/grpc` in DPUMesh), enabled by `DPUMESH_ENABLE=1`.

The Go services use `dmeshgo` in both modes (built with `-tags dpumesh`): Go
makes its socket calls without libc, so preload cannot reach them. Every
change on this branch is inert without DPUMesh: the default Go build tag,
`DPUMESH_ROOT`-less .NET and Gradle builds, and the `DPUMESH_ENABLE` checks
keep upstream behavior.

## Run

Needs a DPUMesh checkout (`DPUMESH_ROOT`, default `../DPUMesh`) with the host
library and the stream library built (DPUMesh `README.md`,
`integrations/grpc/README.md`), Go, Node.js, Python 3, g++, curl and Docker
(Redis). `setup.sh` downloads JDK 21 and the .NET 10 SDK and builds the
DPUMesh grpcio wheel once.

```sh
DPUMESH_ROOT=~/DPUMesh dpumesh/setup.sh
DPUMESH_ROOT=~/DPUMesh DPUMESH_MODE=native dpumesh/run.sh start
dpumesh/run.sh smoke     # home, product, add to cart, cart, checkout
dpumesh/run.sh stop
```

`NATIVE_SERVICES="cartservice adservice"` in preload mode makes just those
services native. Frontend HTTP listens on `127.0.0.1:18080`; logs go to
`dpumesh/.build/logs`.

Each service is a DPUMesh pod (`DPUMESH_POD_IP` 10.99.0.11–20) serving the
service address 10.99.1.1–9 its clients dial. The DPU proxy must serve the
`DPUMESH_SERVER` Comch name (`DPUMeshBoutique0`) on the same PCI functions,
treat 10.99.0.0/16 as profile networks
(`LINKERD2_PROXY_DESTINATION_PROFILE_NETWORKS`), and forward each flow to its
original destination (the mock policy's `MOCK_POLICY_ECHO_TARGET=1`). A DPU
worker must allow 64 flows.

Results: DPUMesh `bench-results/2026-09-29_online-boutique-e2e.md`.
