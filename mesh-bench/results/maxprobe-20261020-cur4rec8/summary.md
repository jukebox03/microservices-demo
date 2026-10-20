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


## W0-nosidecar: max 7392 req/s (no DPU proxy )

| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |
|---|---|---|---|---|---|---|---|---|---|
| 5188 | 5187 | 13 / 156 | 29.6 | 0.80 | 2.0 | 0.1 | 1 (0-10) | 0:0 1:0 | pass |
| 5344 | 5322 | 14 / 37 | 29.5 | 0.80 | 2.0 | 0.5 | 3 (0-9) | 0:1 1:6 | pass |
| 5504 | 5511 | 15 / 101 | 29.6 | 0.80 | 2.1 | 0.0 | 0 (0-1) | 0:0 1:0 | pass |
| 5669 | 5655 | 17 / 49 | 30.0 | 0.80 | 2.2 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 5839 | 5839 | 18 / 58 | 30.1 | 0.81 | 2.2 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 6014 | 6029 | 21 / 51 | 30.4 | 0.81 | 2.3 | 0.1 | 0 (0-1) | 0:1 1:0 | pass |
| 6194 | 6206 | 23 / 53 | 30.5 | 0.81 | 2.3 | 0.0 | 0 (0-1) | 0:0 1:0 | pass |
| 6380 | 6369 | 26 / 60 | 30.7 | 0.82 | 2.2 | 0.1 | 0 (0-1) | 0:1 1:0 | pass |
| 6571 | 6570 | 29 / 72 | 30.8 | 0.82 | 2.5 | 0.0 | 0 (0-1) | 0:0 1:0 | pass |
| 6768 | 6794 | 34 / 91 | 31.0 | 0.83 | 2.5 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 6971 | 6971 | 42 / 137 | 31.1 | 0.84 | 2.6 | 0.0 | 0 (0-1) | 0:0 1:0 | pass |
| 7180 | 7175 | 122 / 300 | 31.2 | 0.85 | 2.7 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 7395 | 7392 | 362 / 660 | 31.2 | 0.85 | 2.9 | 0.2 | 1 (0-10) | 0:1 1:0 | pass |
| 7617 | 7487 | 442 / 829 | 31.2 | 0.85 | 2.7 | 0.1 | 0 (0-1) | 0:1 1:0 | FAIL |

pods at 7395 (pass, cores): frontend-6 1.86, frontend-4 1.85, frontend-1 1.85, frontend-5 1.85, frontend-2 1.84, frontend-3 1.81, adservice 1.10, productcatalogservice-1 1.03, productcatalogservice-4 0.98, productcatalogservice-3 0.98, productcatalogservice-2 0.98, cartservice 0.92, currencyservice-1 0.86, recommendationservice-5 0.84

pods at 7617 (FAIL, cores): frontend-1 1.86, frontend-3 1.84, frontend-5 1.84, frontend-4 1.83, frontend-6 1.83, frontend-2 1.83, adservice 1.09, productcatalogservice-1 1.02, productcatalogservice-3 0.99, productcatalogservice-2 0.99, productcatalogservice-4 0.98, cartservice 0.92, currencyservice-1 0.85, recommendationservice-5 0.84

## G1-default: max 8316 req/s (W=14 DMESH_DPA_MUX=8 DMESH_BUSY_POLL=0 )

| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |
|---|---|---|---|---|---|---|---|---|---|
| 5188 | 5168 | 42 / 76 | 27.4 | 0.82 | 2.0 | 13.6 | 94 (81-99) | 0:15 1:6 | pass |
| 5344 | 5336 | 46 / 87 | 27.5 | 0.82 | 1.9 | 13.6 | 94 (81-98) | 0:18 1:9 | pass |
| 5504 | 5489 | 48 / 87 | 27.6 | 0.83 | 2.2 | 13.7 | 95 (83-98) | 0:15 1:5 | pass |
| 5669 | 5682 | 52 / 95 | 27.8 | 0.84 | 2.2 | 13.3 | 91 (81-95) | 0:15 1:14 | pass |
| 5839 | 5851 | 56 / 104 | 28.0 | 0.85 | 2.2 | 14.3 | 95 (85-98) | 0:54 1:32 | pass |
| 6014 | 5996 | 59 / 105 | 28.2 | 0.85 | 2.4 | 13.8 | 95 (86-98) | 0:16 1:3 | pass |
| 6194 | 6215 | 65 / 116 | 28.4 | 0.86 | 2.3 | 13.8 | 96 (87-98) | 0:12 1:5 | pass |
| 6380 | 6372~ | 70 / 151 | 28.6 | 0.86 | 0.8 | 14.0 | 95 (87-99) | 0:35 1:17 | pass |
| 6571 | 6590 | 73 / 129 | 28.6 | 0.88 | 2.4 | 13.8 | 96 (88-99) | 0:15 1:4 | pass |
| 6768 | 6741 | 78 / 138 | 28.8 | 0.89 | 2.5 | 13.9 | 96 (88-99) | 0:13 1:6 | pass |
| 6971 | 6979 | 87 / 153 | 29.0 | 0.89 | 2.6 | 14.3 | 96 (89-98) | 0:53 1:29 | pass |
| 7180 | 7189~ | 93 / 165 | 19.0 | 1.31 | 0.5 | 8.1 | 57 (52-63) | 0:6 1:3 | pass |
| 7395 | 7397 | 106 / 191 | 29.7 | 0.91 | 2.7 | 14.4 | 96 (89-98) | 0:63 1:30 | pass |
| 7617 | 7588 | 111 / 202 | 30.0 | 0.91 | 2.5 | 13.8 | 96 (89-98) | 0:13 1:5 | pass |
| 7846 | 7844 | 135 / 245 | 30.3 | 0.92 | 2.9 | 13.7 | 95 (88-97) | 0:12 1:15 | pass |
| 8081 | 8061 | 158 / 445 | 30.6 | 0.92 | 3.0 | 13.8 | 96 (89-98) | 0:12 1:5 | pass |
| 8323 | 8316 | 294 / 714 | 30.8 | 0.93 | 2.8 | 13.6 | 94 (86-97) | 0:10 1:4 | pass |
| 8573 | 8511 | 340 / 931 | 30.8 | 0.93 | 2.8 | 13.7 | 95 (89-98) | 0:13 1:4 | FAIL |

pods at 8323 (pass, cores): frontend-3 1.79, frontend-1 1.77, frontend-2 1.77, frontend-6 1.72, frontend-5 1.71, frontend-4 1.69, adservice 1.47, cartservice 1.03, currencyservice-1 0.99, currencyservice-2 0.91, currencyservice-3 0.91, currencyservice-4 0.91, productcatalogservice-3 0.85, productcatalogservice-2 0.84

pods at 8573 (FAIL, cores): frontend-3 1.82, frontend-2 1.79, frontend-1 1.78, frontend-5 1.75, frontend-4 1.75, frontend-6 1.73, cartservice 1.08, currencyservice-1 1.01, adservice 0.95, currencyservice-3 0.94, currencyservice-2 0.93, currencyservice-4 0.93, productcatalogservice-1 0.86, productcatalogservice-3 0.86

proxy threads at 8323 (cores): dmesh-shard-8 0.97, dmesh-shard-5 0.97, dmesh-shard-6 0.97, dmesh-shard-7 0.96, dmesh-shard-9 0.96, dmesh-shard-0 0.96, dmesh-shard-10 0.96, dmesh-shard-13 0.95, dmesh-shard-3 0.95, dmesh-shard-4 0.95, dmesh-shard-2 0.94, dmesh-shard-1 0.89, dmesh-shard-11 0.88, dmesh-shard-12 0.86, dmesh 0.03

## G1-default+W15: max 8321 req/s (W=15 DMESH_DPA_MUX=8 DMESH_BUSY_POLL=0 SHARD_BASE=1 MAIN_CPUS=0 MOCK_CPUS=0)

| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |
|---|---|---|---|---|---|---|---|---|---|
| 5188 | 5180 | 37 / 69 | 27.4 | 0.83 | 2.0 | 14.7 | 94 (86-99) | 0:43 | pass |
| 5344 | 5352 | 39 / 74 | 27.5 | 0.83 | 1.9 | 14.7 | 94 (86-99) | 0:34 | pass |
| 5504 | 5506 | 41 / 77 | 27.7 | 0.83 | 1.9 | 14.7 | 95 (87-98) | 0:34 | pass |
| 5669 | 5669 | 46 / 120 | 27.9 | 0.84 | 2.0 | 14.9 | 94 (88-98) | 0:68 | pass |
| 5839 | 5864 | 46 / 86 | 28.2 | 0.88 | 2.2 | 14.9 | 95 (88-98) | 0:43 | pass |
| 6014 | 6027 | 48 / 88 | 28.4 | 0.86 | 2.3 | 14.9 | 96 (90-99) | 0:32 | pass |
| 6194 | 6206 | 52 / 96 | 28.5 | 0.86 | 2.3 | 14.9 | 96 (90-99) | 0:34 | pass |
| 6380 | 6375 | 58 / 139 | 28.7 | 0.87 | 2.4 | 15.3 | 96 (90-98) | 0:88 | pass |
| 6571 | 6577 | 58 / 107 | 29.0 | 0.89 | 2.4 | 15.0 | 96 (91-99) | 0:37 | pass |
| 6768 | 6751 | 63 / 112 | 29.2 | 0.88 | 2.5 | 15.0 | 96 (91-98) | 0:31 | pass |
| 6971 | 6972 | 68 / 125 | 29.5 | 0.88 | 2.6 | 15.0 | 96 (92-99) | 0:33 | pass |
| 7180 | 7171 | 74 / 132 | 29.8 | 0.89 | 2.6 | 13.8 | 89 (84-94) | 0:39 | pass |
| 7395 | 7394 | 81 / 151 | 30.0 | 0.90 | 2.7 | 15.0 | 96 (92-98) | 0:33 | pass |
| 7617 | 7630 | 91 / 192 | 30.3 | 0.91 | 2.8 | 14.9 | 96 (92-98) | 0:31 | pass |
| 7846 | 7863 | 132 / 298 | 30.3 | 0.92 | 2.8 | 15.0 | 95 (90-97) | 0:77 | pass |
| 8081 | 8096 | 138 / 267 | 30.7 | 0.92 | 2.9 | 14.9 | 96 (91-98) | 0:35 | pass |
| 8323 | 8321 | 204 / 549 | 30.9 | 0.93 | 2.7 | 14.9 | 96 (91-98) | 0:27 | pass |
| 8573 | 8438 | 406 / 778 | 31.0 | 0.93 | 3.0 | 14.8 | 96 (91-98) | 0:26 | FAIL |

pods at 8323 (pass, cores): frontend-1 1.79, frontend-2 1.75, frontend-5 1.73, frontend-3 1.73, frontend-6 1.71, frontend-4 1.70, cartservice 1.10, adservice 1.02, currencyservice-1 1.01, currencyservice-4 0.93, currencyservice-3 0.91, productcatalogservice-1 0.90, currencyservice-2 0.90, productcatalogservice-3 0.87

pods at 8573 (FAIL, cores): frontend-1 1.79, frontend-2 1.78, frontend-3 1.74, frontend-5 1.74, frontend-4 1.74, frontend-6 1.73, cartservice 1.10, adservice 1.08, currencyservice-1 1.00, currencyservice-4 0.92, currencyservice-2 0.90, currencyservice-3 0.90, productcatalogservice-1 0.87, productcatalogservice-3 0.86

proxy threads at 8323 (cores): dmesh-shard-0 0.98, dmesh-shard-8 0.98, dmesh-shard-12 0.98, dmesh-shard-1 0.98, dmesh-shard-7 0.98, dmesh-shard-11 0.97, dmesh-shard-14 0.97, dmesh-shard-13 0.97, dmesh-shard-9 0.96, dmesh-shard-10 0.96, dmesh-shard-4 0.94, dmesh-shard-3 0.94, dmesh-shard-2 0.93, dmesh-shard-5 0.92, dmesh-shard-6 0.90, dmesh 0.05

## G1-default+mc0: max 8058 req/s (W=14 DMESH_DPA_MUX=8 DMESH_BUSY_POLL=0 )

| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |
|---|---|---|---|---|---|---|---|---|---|
| 5188 | 5176 | 40 / 77 | 28.1 | 0.81 | 2.1 | 13.6 | 94 (76-99) | 0:18 1:5 | pass |
| 5344 | 5365 | 44 / 102 | 28.0 | 0.81 | 2.4 | 14.0 | 94 (79-98) | 0:46 1:22 | pass |
| 5504 | 5472 | 45 / 87 | 28.4 | 0.81 | 2.1 | 13.7 | 95 (77-99) | 0:17 1:4 | pass |
| 5669 | 5676 | 49 / 95 | 28.6 | 0.82 | 2.2 | 13.4 | 92 (77-95) | 0:12 1:14 | pass |
| 5839 | 5838 | 52 / 102 | 28.9 | 0.84 | 2.3 | 13.8 | 95 (80-99) | 0:18 1:7 | pass |
| 6014 | 6029 | 56 / 111 | 29.1 | 0.83 | 2.3 | 13.8 | 96 (81-99) | 0:12 1:4 | pass |
| 6194 | 6177 | 59 / 115 | 29.3 | 0.84 | 2.3 | 13.9 | 96 (82-99) | 0:15 1:5 | pass |
| 6380 | 6377 | 65 / 128 | 29.5 | 0.86 | 2.4 | 13.9 | 96 (84-99) | 0:15 1:8 | pass |
| 6571 | 6567 | 69 / 135 | 29.7 | 0.85 | 2.4 | 13.9 | 96 (84-99) | 0:15 1:5 | pass |
| 6768 | 6757 | 74 / 144 | 29.9 | 0.85 | 2.5 | 13.9 | 96 (85-99) | 0:17 1:5 | pass |
| 6971 | 6990 | 82 / 162 | 30.1 | 0.86 | 2.6 | 13.2 | 91 (80-93) | 0:28 1:6 | pass |
| 7180 | 7176 | 92 / 183 | 30.1 | 0.87 | 2.7 | 14.5 | 96 (86-99) | 0:55 1:39 | pass |
| 7395 | 7392 | 102 / 200 | 30.4 | 0.88 | 2.7 | 13.9 | 96 (86-99) | 0:15 1:5 | pass |
| 7617 | 7601 | 110 / 210 | 30.6 | 0.89 | 2.8 | 13.9 | 96 (86-98) | 0:11 1:5 | pass |
| 7846 | 7856 | 147 / 292 | 30.8 | 0.90 | 2.8 | 14.0 | 96 (87-99) | 0:27 1:9 | pass |
| 8081 | 8058 | 196 / 450 | 30.9 | 0.90 | 2.9 | 13.9 | 96 (87-99) | 0:15 1:5 | pass |
| 8323 | 8123 | 472 / 859 | 30.9 | 0.90 | 2.9 | 13.9 | 97 (88-99) | 0:14 1:4 | FAIL |

pods at 8081 (pass, cores): frontend-1 1.75, frontend-2 1.73, frontend-6 1.73, frontend-3 1.71, frontend-5 1.70, frontend-4 1.70, cartservice 1.15, adservice 1.01, currencyservice-1 0.97, currencyservice-3 0.92, productcatalogservice-1 0.91, currencyservice-4 0.91, currencyservice-2 0.90, productcatalogservice-3 0.88

pods at 8323 (FAIL, cores): frontend-1 1.75, frontend-2 1.71, frontend-6 1.70, frontend-4 1.69, frontend-5 1.69, frontend-3 1.67, cartservice 1.17, adservice 0.99, currencyservice-1 0.98, currencyservice-4 0.92, currencyservice-3 0.92, productcatalogservice-1 0.90, currencyservice-2 0.90, productcatalogservice-2 0.87

proxy threads at 8081 (cores): dmesh-shard-2 0.99, dmesh-shard-3 0.98, dmesh-shard-4 0.98, dmesh-shard-1 0.98, dmesh-shard-0 0.98, dmesh-shard-7 0.98, dmesh-shard-8 0.97, dmesh-shard-5 0.97, dmesh-shard-12 0.97, dmesh-shard-13 0.97, dmesh-shard-10 0.97, dmesh-shard-6 0.93, dmesh-shard-9 0.92, dmesh-shard-11 0.85, dmesh 0.04

## W0-nosidecar+mc0: max 7185 req/s (no DPU proxy )

| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |
|---|---|---|---|---|---|---|---|---|---|
| 5188 | 5206 | 13 / 137 | 30.2 | 0.78 | 2.0 | 0.1 | 0 (0-1) | 0:1 1:0 | pass |
| 5344 | 5340 | 14 / 40 | 29.9 | 0.78 | 2.1 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 5504 | 5518 | 15 / 45 | 30.2 | 0.79 | 2.1 | 0.4 | 2 (1-6) | 0:4 1:4 | pass |
| 5669 | 5674 | 17 / 59 | 30.3 | 0.79 | 2.0 | 0.2 | 1 (0-10) | 0:0 1:0 | pass |
| 5839 | 5820 | 18 / 48 | 30.5 | 0.80 | 2.2 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 6014 | 6021 | 20 / 61 | 30.7 | 0.80 | 2.1 | 0.1 | 1 (0-2) | 0:0 1:0 | pass |
| 6194 | 6204 | 22 / 51 | 30.8 | 0.80 | 2.3 | 0.0 | 0 (0-1) | 0:0 1:0 | pass |
| 6380 | 6391 | 25 / 60 | 30.9 | 0.81 | 2.3 | 0.0 | 0 (0-1) | 0:0 1:0 | pass |
| 6571 | 6562 | 29 / 88 | 31.0 | 0.82 | 2.4 | 0.1 | 0 (0-1) | 0:1 1:0 | pass |
| 6768 | 6776 | 32 / 99 | 31.1 | 0.82 | 2.5 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 6971 | 6971 | 42 / 153 | 31.2 | 0.84 | 2.6 | 0.1 | 1 (0-10) | 0:0 1:0 | pass |
| 7180 | 7185 | 93 / 315 | 31.3 | 0.84 | 2.7 | 0.1 | 0 (0-1) | 0:0 1:0 | pass |
| 7395 | 7358 | 357 / 823 | 31.2 | 0.84 | 2.7 | 0.6 | 3 (1-8) | 0:10 1:1 | FAIL |

pods at 7180 (pass, cores): frontend-2 1.86, frontend-4 1.85, frontend-1 1.84, frontend-3 1.83, frontend-6 1.83, frontend-5 1.82, adservice 1.09, productcatalogservice-1 1.02, productcatalogservice-2 1.00, productcatalogservice-3 0.99, productcatalogservice-4 0.99, cartservice 0.94, recommendationservice-8 0.84, recommendationservice-5 0.84

pods at 7395 (FAIL, cores): frontend-4 1.85, frontend-2 1.84, frontend-1 1.84, frontend-6 1.84, frontend-3 1.83, frontend-5 1.83, adservice 1.09, productcatalogservice-1 1.02, productcatalogservice-2 0.99, productcatalogservice-4 0.98, productcatalogservice-3 0.98, cartservice 0.95, recommendationservice-2 0.84, recommendationservice-8 0.84

