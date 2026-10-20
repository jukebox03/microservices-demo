# What stops the host short of 100% busy (2026-10-20 12:00-12:16)

Layout and rig as `maxprobe-20261020-cur4rec8` (29 pods: currency x4, recommendation x8;
jet2 2.3 GHz, SMT on; k6 on jet1). Script `overhead/run_diag.py`: one 3 s + 16 s step per
rate; host PSI and per-CPU runqueue wait (/proc/schedstat), per-container CPU and
cpu.pressure, per-thread CPU and runqueue wait (task schedstat), DPU per-CPU and per-thread;
DPU `perf record -F 499` of the proxy (G1). Dirs: `diag-20261020/` (G1 5188/7846/8081,
W0 5188/6971/7180; its perf-*.txt are too fragmented, superseded by) `diag-20261020-perf/`
(G1 5188/8081, perf by comm / dso / dso,sym). W=15 search: `maxprobe-20261020-cur4rec8/G1-default+W15`.

## Host
| step | p50 ms | host busy /32 | idle hw threads (per CPU) | tasks waiting in runqueues | PSI cpu some |
|---|---|---|---|---|---|
| G1 5,188 | 39 | 27.4 | 5.3 (2-18%) | 34 | 0.55 |
| G1 7,846 | 112 | 30.3 | 2.0 (1-13%) | 90 | 0.76 |
| G1 8,081 | 136 | 30.5 | 1.8 (1-13%) | 96 | 0.77 |
| W0 5,188 | 13 | 29.3 | 3.1 (9-16%) | 70 | 0.72 |
| W0 6,971 | 39 | 31.0 | 1.3 (3-10%) | 136 | 0.84 |
| W0 7,180 | 60 | 31.2 | 1.0 (3-7%) | 152 | 0.85 |

- Near both maxima ~100-150 runnable threads wait for a CPU on average while 3-7% of each
  CPU is idle: the leftover ~1 hardware thread is scheduler gaps spread over all 32
  (SMT siblings), not a free core. The host is saturated.
- No single thread limits: currencyservice's `node` main thread 0.70-0.81 cores at every
  step (in the 24-pod layout it was 0.9 at the ceiling); no cgroup CPU limit (cpu.max max,
  nr_throttled 0).
- At 5,188 G1 has half of W0's CPU contention (34 vs 70 waiting, PSI 0.55 vs 0.72) but
  3x its p50: G1's latency is not host CPU queueing.

## DPU (G1, perf of the proxy, shards = 99.7% of samples)
| share of shard time | 5,188 | 8,081 |
|---|---|---|
| proxy L7 work (h2/hpack, hyper, linkerd/tower/metrics, tokio, futures, jemalloc) | 70% | 74% |
| DOCA PE progress / CQ | 13% | 10% |
| kernel (syscalls, epoll, other) | 9% | 7% |
| libc memcpy | 4% | 5% |

Shards sum to 13.4 cores at 5,188, 7,846 and 8,081 alike (event-driven: they sleep in
epoll when idle, so this is work, not spinning); per request 2.58 -> 1.66 ms, i.e. they
absorb load by batching more per wakeup, with queueing delay as the price.

## W=15 (shards on CPUs 1-15, IRQ/main/mocks on CPU 0), same grid
Max 8,321 vs W=14 8,316 (both fail 8,573). p50 15-22% lower at 5,344-7,617 (6,971: 68 vs
87 ms; 7,395: 81 vs 106 ms), the gain gone from 7,846 (132 vs 135 ms) where the host
saturates. CPU 0 at 26-88%.

## Conclusion
Host CPU sets the maximum for both configs (no-sidecar 7,392, DPUMesh 8,316-8,321); the
idle remainder cannot be turned into throughput. The DPU proxy is fully busy with L7 work
from ~5,000 req/s and sets DPUMesh's latency below the host knee (more shards lower it),
but not its maximum.

## Follow-up (12:22-12:36, `maxprobe-20261020-cur4rec8/{G1-default+L4,*+mc0}`, `run_AB.sh`)
- A. DPU proxy at L4 (`OB_L7=0`, MOCK_OUTBOUND_OPAQUE): not measurable. The proxy opened no
  DMA backend flow (0 backend opens, 195 `dmesh DMA backend gone; refusing instead of TCP
  fallback`, one `Failed to create remote mmap ... DOCA_ERROR_DRIVER`), every smoke request
  HTTP 500. The L4 path to dmesh backends does not work in this build.
- B. CFS `migration_cost_ns` 500000 -> 0 (restored after): W0 max 7,185 (default 7,392),
  G1 8,058 (default 8,316), one grid step lower each; host busy at the max unchanged
  (W0 31.2-31.3, G1 30.9). Faster idle pulling does not fill the remaining ~1 hw thread.
