#!/usr/bin/env python3
"""dpumesh_plot.py [out.png]: p99 latency vs offered load of the DPUMesh runs
in results/16core-mux next to the 2026-10-07 DPUMesh run (results/16core) and
the same-day no-sidecar run, on plot.py's axes and style."""
import glob, json, os, re, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker

BASE = os.environ.get('RESULTS', 'results/16core-mux')
out = sys.argv[1] if len(sys.argv) > 1 else f'{BASE}/p99_vs_load_dpumesh.png'
# (run directory, label, color, line style)
SERIES = [(f'{BASE}/nosidecar', 'no-sidecar', '#c0504d', '-'),
          ('results/16core/dpumesh', 'DPUMesh 10-07: 10 frontends, DPA thread per flow', '#a5a5a5', '--'),
          (f'{BASE}/dpumesh-fe10', 'DPUMesh: 10 frontends, DPA thread per flow', '#9bbb59', '-'),
          (f'{BASE}/dpumesh-fe10-mux8', 'DPUMesh: 10 frontends, DPA mux 8', '#f79646', '-'),
          (f'{BASE}/dpumesh-fe14rr-mux8', 'DPUMesh: 14 frontends round-robin, DPA mux 8', '#8064a2', '-'),
          (f'{BASE}/dpumesh-fe2rr-mux8', 'DPUMesh: 2 frontends round-robin, DPA mux 8', '#4f81bd', '-')]

fig, ax = plt.subplots(figsize=(8, 5))
for d, label, color, style in SERIES:
    pts = []
    for f in glob.glob(f'{d}/rep1/rate*.json'):
        if re.search(r'rate\d+\.json$', f):
            r = json.load(open(f))
            pts.append((r['rate_rps'], r['dur']['p(99)']))
    if not pts:
        continue
    pts.sort()
    ax.plot([x for x, _ in pts], [y for _, y in pts], color=color, linestyle=style, marker='o', markersize=4,
            linewidth=2, label=label)
ax.set_ylim(0, 1000)
ax.set_xlim(0, None)
ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(1000))
ax.set_xlabel('Offered load (RPS)')
ax.set_ylabel('P99 Latency (ms)')
ax.set_title(f'P99 Latency, DPUMesh builds ({os.environ.get("HOST_CORES", "16")} host cores)', loc='left')
ax.legend(frameon=False, loc='upper left', fontsize=8)
ax.grid(True, axis='y', color='#e4e3dc')
for s in ('top', 'right'):
    ax.spines[s].set_visible(False)
fig.text(0.01, 0.005, os.environ.get('NOTE', 'Online Boutique, Kubernetes, pods on 16 host cores, 14 DPU workers. '
         'Dashed: 2026-10-07 build (per-worker DPA EU ranges, no flow dispatcher);\nthe others: DPUMesh '
         'feature/grpc-all-mux, 2026-10-14. 1 run, 15 s per point.'), fontsize=7, color='#6b6a63')
fig.tight_layout(rect=(0, 0.05, 1, 1))
fig.savefig(out, dpi=110, facecolor='white')
print('wrote', out)
