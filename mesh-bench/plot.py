#!/usr/bin/env python3
"""plot.py [out.png]: p99 latency vs offered load for the four configs in
results/ (no-sidecar, Linkerd and Istio with 4 frontends, DPUMesh with 10, one per
DPU worker), on the DeathStarBench slide's axes."""
import glob, json, re, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

out = sys.argv[1] if len(sys.argv) > 1 else 'results/p99_vs_load.png'
REQ_PER_TASK = 23 / 19
SERIES = [('results/nosidecar', 'no-sidecar p99 (ms)', '#c0504d'),
          ('results/istio', 'Istio p99 (ms)', '#8064a2'),
          ('results/linkerd', 'Linkerd p99 (ms)', '#1f3864'),
          ('results/dpumesh', 'DPUMesh p99 (ms)', '#4f81bd')]

fig, ax = plt.subplots(figsize=(8, 5))
for d, label, color in SERIES:
    pts = []
    for f in glob.glob(f'{d}/rep1/rate*.json'):
        m = re.search(r'rate(\d+)\.json$', f)
        if m:
            pts.append((int(m.group(1)) * REQ_PER_TASK, json.load(open(f))['dur']['p(99)']))
    pts.sort()
    ax.plot([x for x, _ in pts], [y for _, y in pts], color=color, marker='o', markersize=4, linewidth=2, label=label)
ax.set_ylim(0, 1000)
ax.set_xlim(0, 4600)
ax.set_xlabel('Offered load (RPS)')
ax.set_ylabel('P99 Latency (ms)')
ax.set_title('P99 Latency', loc='left')
ax.legend(frameon=False, loc='upper right')
ax.grid(True, axis='y', color='#e4e3dc')
for s in ('top', 'right'):
    ax.spines[s].set_visible(False)
fig.text(0.01, 0.005, 'Online Boutique, Kubernetes, same binaries. no-sidecar/Istio/Linkerd: 4 frontends; '
         'DPUMesh: 10 frontends (one per DPU worker). 1 run, 20 s per point.', fontsize=7, color='#6b6a63')
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(out, dpi=110, facecolor='white')
print('wrote', out)
