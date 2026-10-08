#!/usr/bin/env python3
"""packets_plot.py [out.png]: pod-to-pod network packets per HTTP request vs
offered load for no-sidecar, Linkerd and Istio (veth rx+tx counters / 2 /
throughput). DPUMesh is left out: its service-to-service gRPC goes over DMA,
not veth, so only k6 to frontend and cart to Redis remain (3-4 per request)."""
import glob, json, os, re, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE = os.environ.get('RESULTS', 'results')  # e.g. results/12core
out = sys.argv[1] if len(sys.argv) > 1 else f'{BASE}/packets_per_request.png'
SERIES = [(f'{BASE}/nosidecar', 'no-sidecar', '#c0504d'),
          (f'{BASE}/istio', 'Istio', '#8064a2'),
          (f'{BASE}/linkerd', 'Linkerd', '#1f3864')]

fig, ax = plt.subplots(figsize=(8, 5))
for d, label, color in SERIES:
    pts = []
    for f in glob.glob(f'{d}/rep1/rate*.json'):
        if not re.search(r'rate\d+\.json$', f):
            continue
        r = json.load(open(f))
        c = json.load(open(f[:-5] + '.cpu.json'))
        rps = r['reqs']['count'] / r['measure_s']
        pts.append((r['rate_rps'], c['veth_pps'] / rps / 2))
    pts.sort()
    ax.plot([x for x, _ in pts], [y for _, y in pts], color=color, marker='o', markersize=4, linewidth=2, label=label)
ax.set_ylim(0, 70)
ax.set_xlim(0, None)
ax.set_xlabel('Offered load (RPS)')
ax.set_ylabel('Network packets per HTTP request (pod to pod)')
ax.set_title('Packets per HTTP request', loc='left')
ax.legend(frameon=False, loc='upper right')
ax.grid(True, axis='y', color='#e4e3dc')
for s in ('top', 'right'):
    ax.spines[s].set_visible(False)
fig.text(0.01, 0.005, 'veth rx+tx / 2 / throughput; k6 to frontend included, app to sidecar (loopback) not. '
         'Last point: saturated.', fontsize=7, color='#6b6a63')
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(out, dpi=110, facecolor='white')
print('wrote', out)
