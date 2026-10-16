#!/usr/bin/env python3
"""tables_mi.py RESULTS_DIR [RATE]: the MeshInsight-style run's tables from
summary.csv and <cfg>/latency1/k6.json.

tables.md          latency with one request outstanding; every load point with
                   sidecar vCPU by bucket; kernel interaction per HTTP request
table_features.md  the feature ladder at RATE (default 1500): latency, vCPU and
                   sidecar buckets per configuration, with the step from the row
                   above
Raw values only."""
import csv, json, sys

ORDER = ['N0-nosidecar', 'N0t-nosidecar-trace', 'L1-opaque', 'L2-l7', 'L3-authz', 'L4-traffic', 'L5-telemetry',
         'I1-l4', 'I2n-l7-notls', 'I2-l7', 'I3-authz', 'I4-traffic', 'I5-telemetry']
B = ['kernel', 'mtls', 'l7_parsing', 'l7_policy', 'telemetry', 'other']
BN = ['kernel/IPC', 'mTLS', 'L7 parsing', 'L7 policy', 'telemetry', 'runtime']
LADDER = [('Linkerd', [('L1-opaque', 'L4 + mTLS'), ('L2-l7', 'L7 (default)'), ('L3-authz', '+ authz'),
                       ('L4-traffic', '+ traffic policy'), ('L5-telemetry', '+ telemetry')]),
          ('Istio', [('I1-l4', 'L4 + mTLS'), ('I2n-l7-notls', 'L7, mTLS off'), ('I2-l7', 'L7 (default)'),
                     ('I3-authz', '+ authz'), ('I4-traffic', '+ traffic policy'), ('I5-telemetry', '+ telemetry')])]


def f(r, k):
    return float(r[k]) if r.get(k) not in (None, '') else 0.0


def tables(R, rows):
    out = ['## 1. Latency, one request outstanding (ms)\n', '| config | req/s | avg | p50 | p90 | p99 |',
           '|---|---:|---:|---:|---:|---:|']
    for c in ORDER:
        d = json.load(open(f'{R}/{c}/latency1/k6.json')); u = d['dur']
        out.append(f"| {c} | {d['reqs']['count'] / 13:.0f} | {u['avg']:.2f} | {u['p(50)']:.2f} | {u['p(90)']:.2f} | {u['p(99)']:.2f} |")
    out += ['\n## 2. Load points: throughput, latency, host vCPU (app + sidecar), sidecar vCPU by bucket\n',
            '| config | offered | achieved | p50 ms | p99 ms | drop | app vCPU | sidecar vCPU | ' + ' | '.join('sc ' + b for b in B)
            + ' | app kernel | app gRPC | app rest |',
            '|---|---:|---:|---:|---:|---:|---:|---:|' + '---:|' * len(B) + '---:|---:|---:|']
    for c in ORDER:
        for rate in sorted(r for (cc, r) in rows if cc == c):
            r = rows[(c, rate)]; rps = f(r, 'rps')
            v = lambda k: f(r, k) * rps / 1000
            out.append(f"| {c} | {rate} | {rps:.0f} | {f(r, 'p50_ms'):.1f} | {f(r, 'p99_ms'):.1f} | {int(f(r, 'dropped'))} | "
                       f"{f(r, 'app_cores'):.2f} | {f(r, 'sidecar_cores'):.2f} | "
                       + ' | '.join(f"{v('sidecar_' + b + '_ms_per_req'):.2f}" for b in B)
                       + f" | {v('app_kernel_ms_per_req'):.2f} | {v('app_app_grpc_ms_per_req'):.2f} | {v('app_app_user_ms_per_req'):.2f} |")
    out += ['\n## 3. Kernel interaction per HTTP request\n',
            '| config | offered | app syscalls | sidecar syscalls | app vol cs | app invol cs | sidecar vol cs | sidecar invol cs | loopback pkts | pod-to-pod pkts |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c in ORDER:
        for rate in sorted(r for (cc, r) in rows if cc == c):
            r = rows[(c, rate)]
            out.append(f"| {c} | {rate} | {f(r, 'app_syscalls_per_req'):.0f} | {f(r, 'sidecar_syscalls_per_req'):.0f} | "
                       f"{f(r, 'app_vol_cs_per_req'):.0f} | {f(r, 'app_invol_cs_per_req'):.1f} | {f(r, 'sidecar_vol_cs_per_req'):.0f} | "
                       f"{f(r, 'sidecar_invol_cs_per_req'):.1f} | {f(r, 'pod_lo_pkts_per_req'):.0f} | {f(r, 'pod_eth_pkts_per_req'):.0f} |")
    return '\n'.join(out) + '\n'


def features(R, rows, rate):
    out = ['# Table: cost of each sidecar feature (Online Boutique, raw data)\n',
           f'Latency: one request outstanding. CPU: {rate:,} HTTP req/s offered (no drops). vCPU = cgroup CPU of the measured '
           'window; sidecar buckets split by perf. "Step" = difference from the row above.\n']
    for mesh, cs in LADDER:
        out += [f'## {mesh}\n',
                '| configuration | latency mean ms | step | app+sidecar vCPU | step | sidecar vCPU | step | containerd vCPU | '
                + ' | '.join(BN) + ' |',
                '|---|---:|---:|---:|---:|---:|---:|---:|' + '---:|' * len(B)]
        prev = None
        for c, name in cs:
            r = rows[(c, rate)]; rps = f(r, 'rps')
            lat = json.load(open(f'{R}/{c}/latency1/k6.json'))['dur']['avg']
            tot = f(r, 'app_cores') + f(r, 'sidecar_cores'); sc = f(r, 'sidecar_cores'); cd = f(r, 'containerd_cores')
            bk = [f(r, f'sidecar_{b}_ms_per_req') * rps / 1000 for b in B]
            st = lambda a, b: '' if b is None else f'{a - b:+.2f}'
            out.append(f"| {name} | {lat:.2f} | {st(lat, prev and prev[0])} | {tot:.2f} | {st(tot, prev and prev[1])} | {sc:.2f} | "
                       f"{st(sc, prev and prev[2])} | {cd:.2f} | " + ' | '.join(f'{x:.2f}' for x in bk) + ' |')
            prev = (lat, tot, sc)
        out.append('')
    r0, r1 = rows[('N0-nosidecar', rate)], rows[('N0t-nosidecar-trace', rate)]
    l0 = json.load(open(f'{R}/N0-nosidecar/latency1/k6.json'))['dur']['avg']
    l1 = json.load(open(f'{R}/N0t-nosidecar-trace/latency1/k6.json'))['dur']['avg']
    out.append(f"No sidecar: latency {l0:.2f} ms, app {f(r0, 'app_cores'):.2f} vCPU, containerd {f(r0, 'containerd_cores'):.2f}. "
               f"With app tracing (1%), as in the +telemetry rows: latency {l1:.2f} ms, app {f(r1, 'app_cores'):.2f} vCPU.")
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    R = sys.argv[1]
    rate = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    rows = {(r['cfg'], int(r['rate'])): r for r in csv.DictReader(open(f'{R}/summary.csv'))}
    open(f'{R}/tables.md', 'w').write(tables(R, rows))
    open(f'{R}/table_features.md', 'w').write(features(R, rows, rate))
    print('wrote', f'{R}/tables.md', f'{R}/table_features.md')
