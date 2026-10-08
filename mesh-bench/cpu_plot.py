#!/usr/bin/env python3
"""cpu_plot.py [out.png]: the host's busy cores per config at the offered loads
in LOADS (requests/s), stacked as cpusnap.py's split, with the DPU's busy cores for DPUMesh above its bar."""
import json, os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE = os.environ.get('RESULTS', 'results')  # e.g. results/12core
out = sys.argv[1] if len(sys.argv) > 1 else f'{BASE}/host_cpu.png'
LOADS = [int(x) for x in os.environ.get('LOADS', '1000 2000').split()]
CONFIGS = [('nosidecar', 'no-sidecar'), ('istio', 'Istio'), ('linkerd', 'Linkerd'), ('dpumesh', 'DPUMesh')]
PARTS = [('app', 'app', '#4f81bd'), ('sidecar', 'sidecar', '#c0504d'),
         ('pods', 'other pods', '#9bbb59'), ('runtime', 'containerd (container logs)', '#f79646'),
         ('system', 'system (kubelet, kernel)', '#a5a5a5'), ('user', 'login sessions', '#d9d9d9')]

fig, axes = plt.subplots(1, len(LOADS), figsize=(10, 4.6), sharey=True)
for ax, load in zip(axes, LOADS):
    names = []
    for j, (cfg, name) in enumerate(CONFIGS):
        f = f'{BASE}/{cfg}/rep1/rate{load}'
        names.append(name)
        if not os.path.exists(f + '.ctrs.json'):
            continue
        s = json.load(open(f + '.ctrs.json'))['split']
        bottom = 0
        for k, label, color in PARTS:
            ax.bar(j, s[k], 0.7, bottom=bottom, color=color, label=label if ax is axes[0] and j == 0 else None)
            bottom += s[k]
        if cfg == 'dpumesh':
            dpu = json.load(open(f + '.cpu.json'))['dpu_busy']
            ax.text(j, bottom + 0.15, f'+ DPU {dpu:.1f}', ha='center', va='bottom', fontsize=8, color='#4f81bd')
    ax.set_xticks(range(len(names)), names, fontsize=9)
    ax.set_title(f'{load:,} RPS offered', fontsize=10)
    ax.axhline(16, color='#6b6a63', linewidth=0.8)
    ax.grid(True, axis='y', color='#e4e3dc')
    ax.set_axisbelow(True)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
axes[0].set_ylabel('jet1 CPU (cores busy of 16)')
axes[0].set_ylim(0, 16.5)
fig.suptitle(f'Host CPU usage ({os.environ.get("HOST_CORES", "16")} host cores for pods)', x=0.01, ha='left')
fig.legend(frameon=False, loc='center right', fontsize=8)
fig.tight_layout(rect=(0, 0, 0.8, 1))
fig.savefig(out, dpi=110, facecolor='white')
print('wrote', out)
