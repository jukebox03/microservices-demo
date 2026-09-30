# Online Boutique performance

These scripts compare four ways to carry Online Boutique's service-to-service gRPC, under the same load on the same host.

| Mode | Service-to-service gRPC | Proxy |
|---|---|---|
| `tcp` | kernel TCP, straight to each service's port | none |
| `hostproxy` | kernel TCP, redirected through a linkerd2-proxy on the host | DPUMesh's linkerd2-proxy submodule built without `doca`: one worker, L7 |
| `preload` | DPUMesh; the six non-Go services use the preload shim | the DPU linkerd2-proxy, L7 |
| `native` | DPUMesh; the six non-Go services use their language's DPUMesh library | the DPU linkerd2-proxy, L7 |

The `hostproxy` proxy uses the DPU proxy's mock control plane and forwards each flow to its original destination. So in both proxy modes, an RPC crosses exactly one proxy.

Results and analysis are in DPUMesh's `bench-results/2026-09-29_online-boutique-e2e.md`.

## What a run measures

`perf.sh <mode> <tag>` runs the following.

1. **Locust, closed loop.** It uses upstream `src/loadgenerator/locustfile.py` with no wait time, 4 processes, and 8, 32 and 128 users for 40 s each.
2. **health-bench.** DPUMesh's `integrations/grpc/go/cmd/health-bench` calls every service's gRPC health `Check`, first with 1 call in flight and then with 64.

Around every window, it records three things:
- the CPU time and context switches of each thread of the services and the host proxy (`cpusample.py`);
- for DPUMesh modes, the same for the DPU proxy;
- the proxy's per-service request counts and latency buckets (`proxystats.py`).

`summary.txt` in the result directory collects all of it. `summarize.py` turns result directories into one CSV.

### Network namespace

The host side runs in one rootless network namespace (`unshare -Urn`): services, Redis, Locust, health-bench and the host proxy.
- Its loopback carries the service addresses 10.99.1.1–9, so every mode dials the same addresses over the same kernel paths.
- In `hostproxy` mode, an iptables rule inside the namespace redirects 10.99.1.0/24 to the proxy's outbound port, as linkerd-init does in a pod. `libsomark.so` marks the proxy's own connections so that the rule skips them.

### Locust needs TCP_NODELAY

geventhttpclient 2.4 sends a GET's headers and an empty chunked body in two writes. With Nagle on, the second write waits for the frontend's delayed ACK, and Go's HTTP server reads that body before replying.

The result is about 40 ms added to every GET page, independent of the mode. `locust_closed.py` sets `TCP_NODELAY` on Locust's sockets. `LOCUST_NODELAY=0` restores the upstream behavior, and `chunked_get_probe.py` shows the effect against a running frontend.

## Setup

Run these once, in this order.

1. **Online Boutique.** Build it as in `../README.md`: DPUMesh's host and stream libraries, then `DPUMESH_ROOT=<DPUMesh> dpumesh/setup.sh`.

2. **The DPU checkout.** Copy the same DPUMesh checkout to the DPU and build its proxy. `build.sh` builds the transport archives, the proxy with `doca`, and the mocks. The first build takes about 25 minutes.

   ```sh
   rsync -ac --exclude=.git --exclude=target --exclude='build/' <DPUMesh>/ 192.168.100.2:DPUMesh-online-boutique/
   ```

3. **The bench tools.** Set up the tools, then build the proxy on the DPU:

   ```sh
   DPUMESH_ROOT=<DPUMesh> dpumesh/bench/setup.sh
   ssh 192.168.100.2 bash DPUMesh-online-boutique/ob-bench/build.sh
   ```

   `setup.sh` installs its tools under `dpumesh/.build/bench`:
   - Locust from `requirements.txt`;
   - health-bench;
   - the host proxy and mocks;
   - `libsomark.so`;
   - Redis, taken from the `redis:7-alpine` image.

   It also copies `dpu/` to `DPUMesh-online-boutique/ob-bench` on the DPU.

`DPU_HOST` and `DPU_DIR` select another DPU or checkout.

The DPU proxy serves Comch name `DPUMeshBoutique0` on 03:00.0/94:00.0, pinned to cores 9 and 12. `DPU_PCI`, `REP_PCI` and `PROXY_CPUS` in `dpu/env.sh` and `dpu/start.sh` change that. The host proxy is pinned to cores 34–35 and its mocks to core 33 (`HOST_PROXY_CPUS`, `HOST_MOCK_CPUS`).

## Run

```sh
export DPUMESH_ROOT=<DPUMesh>
dpumesh/bench/matrix.sh 1                    # the recorded run set, ~45 min
dpumesh/bench/perf.sh hostproxy my-run       # one mode
USERS_LIST= SKIP_M64=1 dpumesh/bench/perf.sh native m1-only
```

`matrix.sh <rep>` runs three groups:
1. every mode with the defaults;
2. preload and native with health-bench at 1 call in flight only;
3. preload with the DPU proxy's busy poll off (`DPU_BUSY_POLL=0`).

It then writes `results/matrix-r<rep>.csv`.

Groups 2 and 3 are there because the DPU's DPA process can crash under load, which cuts the first group short in the DPUMesh modes. `dpuproxy: crash=` in `summary.txt` counts those crashes.

With busy poll off, the DPU proxy's CPU reflects its work rather than a spinning loop.

`perf.sh` knobs:

| Variable | Default | Meaning |
|---|---|---|
| `USERS_LIST` | `8 32 128` | Locust levels; empty skips Locust |
| `LDUR` | 40 | seconds per Locust level |
| `LOCUST_PROCS` | 4 | Locust processes |
| `SKIP_BENCH`, `SKIP_M64` | 0 | skip health-bench, or its 64-in-flight phase |
| `M1_WARM`, `M1_DUR` | 2s, 8s | health-bench warm-up and window per service, 1 in flight |
| `DPU_BUSY_POLL` | 1 | the DPU proxy's `DMESH_BUSY_POLL` |
| `OUT` | `dpumesh/.build/bench/results` | where result directories go |
