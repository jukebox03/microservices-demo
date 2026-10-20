## 1,500 req/s: app containers (cycles and instructions from perf stat per container cgroup)

| group |  |
|---|
| all |  |
| Go |  |
| Node.js |  |
| Java |  |
| .NET |  |
| Python |  |
| redis |  |


## G1-default+W14: max 5662 req/s (W=14 DMESH_DPA_MUX=8 DMESH_BUSY_POLL=0 )

| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |
|---|---|---|---|---|---|---|---|---|---|
| 5188 | 5170 | 44 / 103 | 27.0 | 0.84 | 2.1 | 13.5 | 93 (74-98) | 0:18 1:5 | pass |
| 5344 | 5345 | 61 / 132 | 27.2 | 0.85 | 1.9 | 13.5 | 94 (76-98) | 0:17 1:6 | pass |
| 5504 | 5489 | 78 / 154 | 27.5 | 0.85 | 2.2 | 13.6 | 94 (77-98) | 0:13 1:5 | pass |
| 5669 | 5662 | 156 / 357 | 27.5 | 0.86 | 2.2 | 14.2 | 93 (77-96) | 0:68 1:49 | pass |
| 5839 | 5778 | 367 / 743 | 27.5 | 0.86 | 2.2 | 13.7 | 95 (79-98) | 0:14 1:5 | FAIL |

proxy threads at 5669 (cores): dmesh-shard-1 0.96, dmesh-shard-0 0.95, dmesh-shard-5 0.95, dmesh-shard-10 0.94, dmesh-shard-6 0.94, dmesh-shard-13 0.94, dmesh-shard-2 0.94, dmesh-shard-11 0.94, dmesh-shard-4 0.93, dmesh-shard-3 0.92, dmesh-shard-7 0.91, dmesh-shard-9 0.87, dmesh-shard-12 0.86, dmesh-shard-8 0.73, dmesh 0.03

## G1-default+W15: max 5679 req/s (W=15 DMESH_DPA_MUX=8 DMESH_BUSY_POLL=0 SHARD_BASE=1 MAIN_CPUS=0 MOCK_CPUS=0)

| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |
|---|---|---|---|---|---|---|---|---|---|
| 5188 | 5182 | 39 / 94 | 27.1 | 0.85 | 1.9 | 14.5 | 93 (79-98) | 0:39 | pass |
| 5344 | 5342 | 49 / 118 | 27.2 | 0.85 | 2.1 | 14.5 | 93 (80-98) | 0:32 | pass |
| 5504 | 5500 | 73 / 153 | 27.6 | 0.88 | 2.2 | 14.6 | 94 (81-98) | 0:32 | pass |
| 5669 | 5679~ | 110 / 334 | 15.6 | 1.15 | 0.5 | 7.4 | 48 (41-53) | 0:11 | pass |
| 5839 | 5804 | 348 / 647 | 27.7 | 0.86 | 2.0 | 14.6 | 94 (81-98) | 0:29 | FAIL |

proxy threads at 5669 (cores): dmesh-shard-0 0.49, dmesh-shard-9 0.48, dmesh-shard-2 0.48, dmesh-shard-6 0.48, dmesh-shard-12 0.48, dmesh-shard-7 0.48, dmesh-shard-10 0.48, dmesh-shard-1 0.48, dmesh-shard-5 0.48, dmesh-shard-13 0.47, dmesh-shard-3 0.47, dmesh-shard-4 0.45, dmesh-shard-8 0.43, dmesh-shard-11 0.39, dmesh-shard-14 0.39, dmesh 0.03

## W0-nosidecar+fine: max 5665 req/s (no DPU proxy )

| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |
|---|---|---|---|---|---|---|---|---|---|
| 5188 | 5197 | 16 / 347 | 29.0 | 0.83 | 2.1 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 5344 | 5350 | 15 / 76 | 28.8 | 0.82 | 1.9 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 5504 | 5502 | 60 / 236 | 29.2 | 0.83 | 2.2 | 0.1 | 0 (0-1) | 0:0 1:1 | pass |
| 5669 | 5665 | 228 / 439 | 29.1 | 0.83 | 2.2 | 0.6 | 4 (1-8) | 0:8 1:1 | pass |
| 5839 | 5759 | 421 / 815 | 29.2 | 0.84 | 2.3 | 0.1 | 0 (0-1) | 0:0 1:0 | FAIL |

