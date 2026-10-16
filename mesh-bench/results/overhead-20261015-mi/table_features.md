# Table: cost of each sidecar feature (Online Boutique, raw data)

Latency: one request outstanding. CPU: 1,500 HTTP req/s offered (no drops). vCPU = cgroup CPU of the measured window; sidecar buckets split by perf. "Step" = difference from the row above.

## Linkerd

| configuration | latency mean ms | step | app+sidecar vCPU | step | sidecar vCPU | step | containerd vCPU | kernel/IPC | mTLS | L7 parsing | L7 policy | telemetry | runtime |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L4 + mTLS | 14.34 |  | 18.49 |  | 5.03 |  | 1.34 | 3.46 | 0.41 | 0.00 | 0.02 | 0.13 | 1.01 |
| L7 (default) | 21.01 | +6.68 | 20.23 | +1.74 | 8.60 | +3.57 | 1.22 | 2.77 | 0.29 | 2.37 | 0.43 | 0.79 | 1.94 |
| + authz | 20.10 | -0.91 | 20.07 | -0.16 | 8.55 | -0.05 | 1.23 | 2.73 | 0.28 | 2.36 | 0.41 | 0.83 | 1.94 |
| + traffic policy | 20.86 | +0.76 | 20.19 | +0.12 | 8.80 | +0.25 | 1.22 | 2.74 | 0.27 | 2.37 | 0.63 | 0.83 | 1.97 |
| + telemetry | 21.73 | +0.86 | 20.08 | -0.11 | 9.20 | +0.40 | 2.05 | 2.57 | 0.27 | 2.40 | 0.52 | 1.44 | 2.00 |

## Istio

| configuration | latency mean ms | step | app+sidecar vCPU | step | sidecar vCPU | step | containerd vCPU | kernel/IPC | mTLS | L7 parsing | L7 policy | telemetry | runtime |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L4 + mTLS | 15.05 |  | 19.20 |  | 5.89 |  | 1.35 | 3.53 | 0.67 | 0.00 | 0.00 | 0.05 | 1.65 |
| L7, mTLS off | 26.16 | +11.12 | 20.72 | +1.52 | 10.47 | +4.58 | 1.12 | 2.09 | 0.00 | 3.65 | 1.17 | 1.07 | 2.49 |
| L7 (default) | 26.84 | +0.68 | 20.82 | +0.10 | 10.79 | +0.32 | 1.09 | 2.10 | 0.49 | 3.62 | 1.11 | 1.05 | 2.42 |
| + authz | 26.21 | -0.63 | 20.83 | +0.01 | 11.00 | +0.21 | 1.10 | 2.07 | 0.56 | 3.67 | 1.19 | 1.07 | 2.45 |
| + traffic policy | 27.81 | +1.60 | 20.89 | +0.06 | 11.10 | +0.10 | 1.08 | 2.14 | 0.50 | 3.73 | 1.20 | 1.04 | 2.49 |
| + telemetry | 29.30 | +1.49 | 22.31 | +1.42 | 11.90 | +0.80 | 1.17 | 2.10 | 0.50 | 3.99 | 1.22 | 1.49 | 2.59 |

No sidecar: latency 8.95 ms, app 15.36 vCPU, containerd 1.40. With app tracing (1%), as in the +telemetry rows: latency 9.38 ms, app 16.05 vCPU.
