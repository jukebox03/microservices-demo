# Max req/s with currency x4, recommendation x8 (2026-10-20 11:38-11:53)

Same rig and method as `maxprobe-20261019-fine`: jet2 2.3 GHz fixed (turbo off, SMT on),
k6 on jet1, L7 default, 3% steps from 5,188 req/s for both configs (2 s warm + 8 s
measured; pass = no drops, no failures, >= 97% achieved). DPU proxy feature/dpa-mux
cd01a50 + comch-wake, W=14, DMESH_DPA_MUX=8, event-driven; host lib feature/comch-wake.
Layout: frontend x6 round-robin, catalog x4, **currency x4 (was 2), recommendation x8
(was 5)**, the rest x1: 29 pods (`OB_N_CUR=4 OB_N_REC=8 OB_LAYOUT=dpumesh/layout14rr-fe6-cur4-rec8.txt`).
Each step also records the CPU of every app container (`pods` in max.json).

| config | max req/s | host busy at max /32 | pods at max (cores) | max with p99 <= 200 ms | max with p99 <= 100 ms |
|---|---|---|---|---|---|
| G1 DPUMesh (comch-wake) | **8,316** | 30.8 | 27.9 | 7,397 | 5,489 |
| W0 no sidecar | **7,392** | 31.2 | 28.4 | 6,971 | 6,794 |
| (24-pod layout, 10-19) G1 / W0 | 5,662 / 5,665 | 27.5 / 29.1 | | | |

1. With the currency/recommendation ceiling removed, both configs end at host-wide CPU
   saturation (~31 of 32 hardware threads) and DPUMesh reaches 12.5% more (4 grid steps).
   Host CPU per request at the max: G1 3.70 ms, W0 4.22 ms.
2. At the same load the pods use less CPU with DPUMesh, but the gap narrows with load:
   6,971 req/s G1 25.9 vs W0 28.1 cores (-8%); at 1,500 req/s it was 12.2 vs 16.4 (-26%).
3. Host busy barely follows the load (W0 29.6 at 5,188 -> 31.2 at 7,392; G1 27.4 -> 30.8),
   so busy% is not a per-request cost.
4. Latency: W0 is far lower below its knee (5,669: p50 17 vs 52 ms; 6,571: 29 vs 73 ms)
   and keeps the p99 <= 100 ms bound to a higher load; G1 degrades later (7,180:
   p50 93 vs 122 ms), so it wins at p99 <= 200 ms and at the max.
5. Per pod at the max: currency 0.85 (W0) / 0.91-1.0 (G1), recommendation 0.84 in both,
   frontends 1.7-1.8 (G1) / ~1.8 (W0). DPU shards 0.86-0.97 cores (busy%, not saturation).
6. flow_check: 245 ring adds, 19 slots at most per worker (of 64); 20 `forward ring
   stopped, error 1` (TAIL) at DPU 02:46:38 = jet2 ~11:46:50, after the last step
   (DPU clock ~11.8 s behind jet2), i.e. during the namespace teardown. Earlier runs show
   the same at teardown (x4, x4, x16).

G1 steps 6,380 and 7,180 had a probe window not fully under load (jet1 busy 0.8 / 0.5);
their k6 numbers are valid, their CPU numbers are not.
