# What limits max req/s (2026-10-19 evening)

jet2 at 2.3 GHz fixed (turbo off, SMT on), k6 on jet1, L7 default, common 24-pod
layout. DPU proxy feature/dpa-mux + comch-wake, DMESH_DPA_MUX=8, event-driven.
Scripts: `overhead/run_max_probe.py`, `overhead/run_threads.py`, `overhead/summarize_probe.py`.

## Runs
| dir | what |
|---|---|
| `maxprobe-20261019/` | W0 / L1 / G1: 1,500 req/s step with per-container cycles+instructions, then the 10% step search with host/DPU/jet1 per-CPU and DPU per-thread CPU (`summary.md`) |
| `maxprobe-20261019-fine/` | 3% steps from 5,188: G1 W=14, G1 W=15 (shards on CPUs 1-15, IRQ/main/mocks on CPU 0), W0 (`summary.md`) |
| `threads-20261019/` | one 5,669 req/s step, W0 and G1: CPU of every app-container thread |

## Findings
1. **All three hit the same ceiling.** 3% steps: W0 5,665, G1 W=14 5,662, G1 W=15 5,679;
   every one passes 5,669 and fails 5,839. The earlier +5% for DPUMesh (5,733 vs 5,450)
   came from the 10% grids (W0 4,500x1.1^n, DPUMesh 2,000x1.1^n), not from the system.
2. **The ceiling is currencyservice's event loop.** At 5,669 req/s the main `node` thread
   of each of the 2 currencyservice pods runs at 0.88-0.92 cores, in W0 and G1 alike;
   no other app thread is above 0.2. recommendationservice (5 Python pods) is at about
   1.05 cores per pod (GIL). Host total is not the limit (G1 27.7/32, W0 29.4/32).
3. **DPU shard busy% is not a saturation measure.** At 5,188 req/s the shard CPUs are 93%
   busy with 14 shards and still 93% with 15 (proportional work would give 87%); W=15
   does not move the maximum and lowers p50 only near the knee (5,669: 110 vs 156 ms).
   CPUs 0-1 (W=14) use 5-20%; CPU 0 alone (W=15) 30-40%.
4. **jet1 (k6) is not the limit:** <= 2.5 busy cores at every step.
5. **1,500 req/s, app containers (perf stat per cgroup):**

| | W0 no sidecar | L1 legacy | G1 fast-path wake |
|---|---|---|---|
| app cores | 16.37 | 16.63 | 12.19 |
| instructions / request (M) | 11.32 | 15.65 | 11.34 |
| cycles / request (M) | 20.02 | 18.64 | 14.29 |
| IPC | 0.566 | 0.840 | 0.794 |

   G1 executes as many instructions per request as no sidecar but at 40% higher IPC;
   L1's extra 38% instructions are the nap/linger polling. Go runtime (wake-20261019d/e
   perf, `go_runtime_leaf.py` / `.txt` here): L1 -> G1 runtime -0.62 vCPU, of it scheduler
   idle work (stealWork/findRunnable/netpoll) -0.52; W0 -> G1 mostly GC (0.92 -> 0.61).

Steps marked `~` in the summaries had a probe window not fully under load (k6 started
late); their k6 numbers are valid, their CPU numbers are not.
