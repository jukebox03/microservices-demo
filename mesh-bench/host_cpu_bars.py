#!/usr/bin/env python3
"""host_cpu_bars.py [out.png]: jet1's busy CPU (%, 100 per core, all 16 cores)
per offered load for no-sidecar and DPUMesh, as grouped bars on the
DeathStarBench slide's layout. Every measured load is a category, the last
one of each sweep saturated."""
import glob, json, os, re, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE = os.environ.get('RESULTS', 'results')  # e.g. results/12core
out = sys.argv[1] if len(sys.argv) > 1 else f'{BASE}/host_cpu_usage.png'
SERIES = [('nosidecar', 'no-sidecar', '#c0504d'), ('dpumesh', 'DPUMesh', '#4f81bd')]
GREY = '#595959'
plt.rcParams['font.family'] = ['Liberation Sans', 'DejaVu Sans']

data = {}
for cfg, _, _ in SERIES:
    data[cfg] = {}
    for f in glob.glob(f'{BASE}/{cfg}/rep1/rate*.cpu.json'):
        rate = int(re.search(r'rate(\d+)\.cpu\.json$', f).group(1))
        data[cfg][rate] = json.load(open(f))['host_busy'] * 100
rates = sorted({r for d in data.values() for r in d})

fig, ax = plt.subplots(figsize=(9, 5))
w = 0.32
for i, (cfg, label, color) in enumerate(SERIES):
    xs = [j + (i - 0.5) * (w + 0.04) for j, r in enumerate(rates) if r in data[cfg]]
    ax.bar(xs, [data[cfg][r] for r in rates if r in data[cfg]], w, color=color, label=label)
ax.set_xticks(range(len(rates)), [f'{r / 1000:g}K' for r in rates])
ax.set_ylim(0, 1600)
ax.set_yticks(range(0, 1601, 200))
ax.set_xlabel('Offered load (RPS)', fontsize=15, color=GREY)
ax.set_ylabel('CPU Usage (%)', fontsize=15, color=GREY)
ax.set_title(f'Host CPU Usage ({os.environ.get("HOST_CORES", "16")} host cores)', fontsize=20, color=GREY, pad=36)
ax.tick_params(axis='both', labelsize=13, colors=GREY, length=0)
ax.grid(True, axis='y', color='#d9d9d9')
ax.set_axisbelow(True)
for s in ('top', 'right', 'left'):
    ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#bfbfbf')
leg = ax.legend(frameon=False, loc='upper right', bbox_to_anchor=(1.0, 1.1), ncol=2, fontsize=14,
                handlelength=0.7, handleheight=0.7, columnspacing=1.2)
for t in leg.get_texts():
    t.set_color(GREY)
fig.tight_layout()
fig.savefig(out, dpi=110, facecolor='white')
print('wrote', out)
