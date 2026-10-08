#!/usr/bin/env python3
"""plot.py [out.png]: p99 latency vs offered load for the four configs in
results/, each configuration at its best replica counts (k8sob/gen.py), on the
DeathStarBench slide's axes."""
import glob, json, os, re, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker

BASE = os.environ.get('RESULTS', 'results')  # e.g. results/12core
out = sys.argv[1] if len(sys.argv) > 1 else f'{BASE}/p99_vs_load.png'
SERIES = [(f'{BASE}/nosidecar', 'no-sidecar p99 (ms)', '#c0504d'),
          (f'{BASE}/istio', 'Istio p99 (ms)', '#8064a2'),
          (f'{BASE}/linkerd', 'Linkerd p99 (ms)', '#1f3864'),
          (f'{BASE}/dpumesh', 'DPUMesh p99 (ms)', '#4f81bd')]

fig, ax = plt.subplots(figsize=(8, 5))
for d, label, color in SERIES:
    pts = []
    for f in glob.glob(f'{d}/rep1/rate*.json'):
        if re.search(r'rate\d+\.json$', f):
            d = json.load(open(f))
            pts.append((d['rate_rps'], d['dur']['p(99)']))
    pts.sort()
    ax.plot([x for x, _ in pts], [y for _, y in pts], color=color, marker='o', markersize=4, linewidth=2, label=label)
ax.set_ylim(0, 1000)
ax.set_xlim(0, None)
ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(1000))
ax.set_xlabel('Offered load (RPS)')
ax.set_ylabel('P99 Latency (ms)')
ax.set_title(f'P99 Latency ({os.environ.get("HOST_CORES", "16")} host cores)', loc='left')
ax.legend(frameon=False, loc='upper right')
ax.grid(True, axis='y', color='#e4e3dc')
for s in ('top', 'right'):
    ax.spines[s].set_visible(False)
fig.text(0.01, 0.005, f'Online Boutique, Kubernetes, pods on {os.environ.get("HOST_CORES", "16")} host cores; each configuration at its best '
         'replica counts (frontends: no-sidecar 2, Linkerd 6, Istio 4,\nDPUMesh 10 on 14 DPU workers). 1 run, 15 s per point.',
         fontsize=7, color='#6b6a63')
fig.tight_layout(rect=(0, 0.05, 1, 1))
fig.savefig(out, dpi=110, facecolor='white')
print('wrote', out)
