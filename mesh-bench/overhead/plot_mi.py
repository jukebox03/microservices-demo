#!/usr/bin/env python3
"""plot_mi.py RESULTS_DIR SUMMARY.csv OUTDIR: figures for the MeshInsight-style run.

fig_latency1.png  latency with one request outstanding (avg, p50, p99), per config
fig_cpu.png       host vCPU by part (app: kernel / gRPC library / rest; sidecar:
                  six buckets) at each offered load, one panel per config
fig_load.png      achieved throughput and p50/p99 latency vs offered load
Raw values only: vCPU are the cgroup CPU of the measured window, split by the
perf shares of the same point."""
import csv, glob, json, os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from plot import SEGS, SURFACE, INK, INK2, GRID

ORDER = ['N0-nosidecar', 'N0t-nosidecar-trace', 'L1-opaque', 'L2-l7', 'L3-authz', 'L4-traffic', 'L5-telemetry',
         'I1-l4', 'I2n-l7-notls', 'I2-l7', 'I3-authz', 'I4-traffic', 'I5-telemetry']
NAME = {'N0-nosidecar': 'No sidecar', 'N0t-nosidecar-trace': 'No sidecar + app tracing',
        'L1-opaque': 'Linkerd L4', 'L2-l7': 'Linkerd L7', 'L3-authz': 'Linkerd +authz', 'L4-traffic': 'Linkerd +traffic',
        'L5-telemetry': 'Linkerd +telemetry', 'I1-l4': 'Istio L4', 'I2n-l7-notls': 'Istio L7 no mTLS', 'I2-l7': 'Istio L7',
        'I3-authz': 'Istio +authz', 'I4-traffic': 'Istio +traffic', 'I5-telemetry': 'Istio +telemetry'}


def f(r, k):
    try:
        return float(r[k])
    except (KeyError, TypeError, ValueError):
        return 0.0


def fig_latency1(res, out):
    rows = []
    for c in ORDER:
        p = f'{res}/{c}/latency1/k6.json'
        if os.path.exists(p):
            d = json.load(open(p))['dur']
            rows.append((c, d['avg'], d['p(50)'], d['p(99)']))
    fig, ax = plt.subplots(figsize=(8.5, 3.4))
    xs = range(len(rows))
    ax.bar(xs, [r[2] for r in rows], 0.6, color='#2a78d6', label='p50', edgecolor=SURFACE)
    ax.scatter(xs, [r[3] for r in rows], marker='_', s=260, color='#eb6834', linewidths=2.5, label='p99', zorder=3)
    for x, r in zip(xs, rows):
        ax.text(x, r[2] / 2, f'{r[2]:.1f}', ha='center', va='center', fontsize=7, color='#ffffff')
        ax.text(x, r[3] + 1, f'{r[3]:.1f}', ha='center', va='bottom', fontsize=7, color=INK)
    ax.set_xticks(list(xs), [NAME[r[0]] for r in rows], rotation=40, ha='right', rotation_mode='anchor', fontsize=7.5)
    ax.set_ylabel('Latency per HTTP request (ms)')
    ax.set_title('One request outstanding (k6, 1 VU, 13 s)', fontsize=9.5)
    ax.yaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(out, dpi=200, bbox_inches='tight')
    return rows


def fig_cpu(rows, out):
    cfgs = [c for c in ORDER if any(k[0] == c for k in rows)]
    fig, axes = plt.subplots(3, 6, figsize=(16, 9), sharey=True)
    layout = {'N0-nosidecar': (0, 0), 'N0t-nosidecar-trace': (0, 1),
              'L1-opaque': (1, 0), 'L2-l7': (1, 1), 'L3-authz': (1, 2), 'L4-traffic': (1, 3), 'L5-telemetry': (1, 4),
              'I1-l4': (2, 0), 'I2n-l7-notls': (2, 1), 'I2-l7': (2, 2), 'I3-authz': (2, 3), 'I4-traffic': (2, 4), 'I5-telemetry': (2, 5)}
    used = set()
    for c in cfgs:
        ax = axes[layout[c]]; used.add(layout[c])
        rates = sorted(r for (cc, r) in rows if cc == c)
        bottom = [0.0] * len(rates)
        for key, name, color in SEGS:
            vals = [f(rows[(c, r)], key) * f(rows[(c, r)], 'rps') / 1000 for r in rates]
            ax.bar(range(len(rates)), vals, 0.7, bottom=bottom, color=color, label=name, edgecolor=SURFACE, linewidth=0.8)
            bottom = [b + v for b, v in zip(bottom, vals)]
        for x, (r, tot) in enumerate(zip(rates, bottom)):
            ach = f(rows[(c, r)], 'rps')
            ax.text(x, tot + 0.3, f'{tot:.1f}', ha='center', va='bottom', fontsize=6.5)
        ax.set_xticks(range(len(rates)), [f'{r:,}' for r in rates], fontsize=7)
        ax.set_title(NAME[c], fontsize=8.5)
        ax.yaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
    for i in range(3):
        for j in range(6):
            if (i, j) not in used:
                axes[i, j].axis('off')
        axes[i, 0].set_ylabel('Host vCPU (app + sidecar)')
    for ax in axes[-1]:
        ax.set_xlabel('Offered HTTP req/s', fontsize=7.5)
    h, l = axes[1, 1].get_legend_handles_labels()
    fig.legend(h[::-1], l[::-1], loc='upper right', bbox_to_anchor=(0.99, 0.95), frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(out, dpi=180, bbox_inches='tight')


def fig_load(rows, out):
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
    groups = [('No sidecar', ['N0-nosidecar', 'N0t-nosidecar-trace']),
              ('Linkerd', ['L1-opaque', 'L2-l7', 'L3-authz', 'L4-traffic', 'L5-telemetry']),
              ('Istio', ['I1-l4', 'I2n-l7-notls', 'I2-l7', 'I3-authz', 'I4-traffic', 'I5-telemetry'])]
    colors = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300']
    for ax, (title, cs) in zip(axes, groups):
        for c, color in zip(cs, colors):
            rates = sorted(r for (cc, r) in rows if cc == c)
            if not rates:
                continue
            ax.plot(rates, [f(rows[(c, r)], 'p50_ms') for r in rates], '-o', color=color, lw=2, ms=4, label=f'{NAME[c]} p50')
            ax.plot(rates, [f(rows[(c, r)], 'p99_ms') for r in rates], '--', color=color, lw=1.2, label=f'{NAME[c]} p99')
        ax.set_yscale('log'); ax.set_title(title, fontsize=9.5)
        ax.set_xlabel('Offered HTTP req/s'); ax.set_ylabel('Latency (ms, log)')
        ax.yaxis.grid(True, color=GRID, lw=0.6, which='both'); ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=6.5, ncol=1)
    fig.tight_layout(); fig.savefig(out, dpi=180, bbox_inches='tight')


if __name__ == '__main__':
    res, summary, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    rows = {(r['cfg'], int(r['rate'])): r for r in csv.DictReader(open(summary))}
    fig_latency1(res, f'{out}/fig_latency1.png')
    fig_cpu(rows, f'{out}/fig_cpu.png')
    fig_load(rows, f'{out}/fig_load.png')
    print('wrote', out)
