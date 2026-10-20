# comch-wake without the DPA mux: smoke on hardware (2026-10-20 14:59-15:02)

Question: does `feature/comch-wake` work on main alone (the PR without feature/dpa-mux)?
Every earlier comch-wake measurement ran on a DPU build of dpa-mux + comch-wake.

- DPU: `~/DPUMesh-cw-main` = DPUMesh `feature/comch-wake` 61f6c29 (main ece30c2 + comch-wake)
  + linkerd2-proxy fb4b3632 (main's pin), built with `ob-bench/build.sh` at `-j 2`.
  W=14, `DMESH_DPA_MUX=0` (main has no mux: one DPA pool thread per flow), event-driven, L7.
- Host: libdpumesh from `feature/comch-wake` (fast path on by default), 24-pod layout.
- Run: `overhead/run_wake.py ... G1-default` with `DPU_OB=~/DPUMesh-cw-main/ob-bench
  DPU_PROXY_ENV='W=14 DMESH_DPA_MUX=0 DMESH_BUSY_POLL=0'`; jet2 at 2.3 GHz fixed.

| | G1, dpa-mux + comch-wake (`wake-20261019e`) | G1, comch-wake on main (this run) |
|---|---|---|
| DPU ready | 14 pools + 14 mux workers, 30 s | 14 pools, no mux, 15 s |
| one request outstanding: avg / p50 / p99 ms | 16.24 / 17.75 / 33.76 | 16.26 / 18.51 / 30.69 |
| 1,500 req/s: achieved, p50 / p99 ms | 1,501, 16.0 / 30.1 | 1,503, 17.2 / 28.2 |
| failures / drops | 0 / 0 | 0 / 0 |
| app cores / host busy | 11.64 / 14.76 | 11.81 / 14.93 |
| fast path in use (23 pods) | rx_signaled=1, 0 ARM messages, 0 doorbells | the same |
| flow_check | no errors | no errors (101 client + 89 backend opens, 190 DPA thread assigns) |

Pass. The fast path works without the DPA mux, with the same CPU and latency within the
run-to-run spread (G2, a G1 repeat on 10-19: 11.79 cores, p50 16.2 ms). The proxy log's
118 `fast-path producer went idle ... (peer gone?)` lines are at the namespace teardown
after the measurement, as in 10-19e (119).
