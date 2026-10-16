#!/usr/bin/env python3
"""plot.py SUMMARY.csv OUTDIR: figures for the sidecar CPU-overhead ladder.

fig_breakdown.png  host CPU per HTTP request, stacked: app (kernel, its gRPC
                   library, the rest) and sidecar (six buckets), per config,
                   one panel per offered load
fig_sidecar.png    the sidecar part alone, as shares of the sidecar's CPU
fig_kernel.png     per HTTP request: syscalls, context switches, loopback packets
"""
import csv, os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ORDER = ['N0-nosidecar', 'L1-opaque', 'L2-l7', 'L3-authz', 'L4-traffic', 'L5-telemetry',
         'I1-l4', 'I2n-l7-notls', 'I2-l7', 'I3-authz', 'I4-traffic', 'I5-telemetry']
LABEL = {'N0-nosidecar': 'none', 'L1-opaque': 'L4', 'L2-l7': 'L7', 'L3-authz': '+authz',
         'L4-traffic': '+traffic', 'L5-telemetry': '+telem', 'I1-l4': 'L4', 'I2n-l7-notls': 'L7\nno TLS',
         'I2-l7': 'L7', 'I3-authz': '+authz', 'I4-traffic': '+traffic', 'I5-telemetry': '+telem'}
SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
# app segments in neutral grays (context), sidecar buckets in categorical slots 1-6
SEGS = [('app_kernel_ms_per_req', 'App: kernel', '#8d8c87'),
        ('app_app_grpc_ms_per_req', 'App: gRPC library', '#b4b3ad'),
        ('app_app_user_ms_per_req', 'App: rest', '#d6d5cf'),
        ('sidecar_kernel_ms_per_req', 'Sidecar: kernel / IPC', '#2a78d6'),
        ('sidecar_mtls_ms_per_req', 'Sidecar: mTLS', '#eb6834'),
        ('sidecar_l7_parsing_ms_per_req', 'Sidecar: L7 parsing', '#1baf7a'),
        ('sidecar_l7_policy_ms_per_req', 'Sidecar: L7 policy', '#eda100'),
        ('sidecar_telemetry_ms_per_req', 'Sidecar: telemetry', '#e87ba4'),
        ('sidecar_other_ms_per_req', 'Sidecar: other (runtime)', '#008300')]

plt.rcParams.update({'font.size': 9, 'axes.edgecolor': INK2, 'axes.labelcolor': INK, 'xtick.color': INK2,
                     'ytick.color': INK2, 'text.color': INK, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
                     'savefig.facecolor': SURFACE, 'axes.spines.top': False, 'axes.spines.right': False})


def load(path):
    rows = {}
    for r in csv.DictReader(open(path)):
        rows[(r['cfg'], int(r['rate']))] = {k: (float(v) if v not in ('', None) and k != 'cfg' else v) for k, v in r.items()}
    return rows


def f(r, k):
    v = r.get(k)
    return v if isinstance(v, float) else 0.0


def mesh_groups(ax, y):
    for x0, x1, name in ((0.6, 5.4, 'Linkerd'), (5.6, 11.4, 'Istio')):
        ax.annotate('', xy=(x0, y), xytext=(x1, y), xycoords=('data', 'axes fraction'),
                    arrowprops=dict(arrowstyle='-', color=INK2, lw=0.8))
        ax.text((x0 + x1) / 2, y + 0.015, name, transform=ax.get_xaxis_transform(), ha='center', va='bottom',
                color=INK2, fontsize=8.5)


def fig_breakdown(rows, rates, out):
    fig, axes = plt.subplots(1, len(rates), figsize=(6.6 * len(rates), 3.8), sharey=True)
    axes = axes if len(rates) > 1 else [axes]
    for ax, rate in zip(axes, rates):
        cfgs = [c for c in ORDER if (c, rate) in rows]
        xs = range(len(cfgs))
        bottom = [0.0] * len(cfgs)
        for key, name, color in SEGS:
            vals = [f(rows[(c, rate)], key) for c in cfgs]
            ax.bar(xs, vals, 0.72, bottom=bottom, color=color, label=name, edgecolor=SURFACE, linewidth=1.0)
            bottom = [b + v for b, v in zip(bottom, vals)]
        for x, c, tot in zip(xs, cfgs, bottom):
            ax.text(x, tot + 0.25, f'{tot:.1f}', ha='center', va='bottom', fontsize=7.5, color=INK)
        ax.set_xticks(list(xs), [LABEL[c] for c in cfgs], fontsize=7.5, rotation=40, ha='right', rotation_mode='anchor')
        ax.set_title(f'{rate:,} HTTP req/s', fontsize=9.5, color=INK, pad=18)
        ax.yaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
        mesh_groups(ax, 1.0)
    axes[0].set_ylabel('Host CPU time per HTTP request (ms)')
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h[::-1], l[::-1], loc='center left', bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches='tight')


def fig_sidecar(rows, rate, out):
    cfgs = [c for c in ORDER if (c, rate) in rows and f(rows[(c, rate)], 'sidecar_ms_per_req') > 0]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    left = [0.0] * len(cfgs)
    for key, name, color in SEGS[3:]:
        vals = [f(rows[(c, rate)], key) / f(rows[(c, rate)], 'sidecar_ms_per_req') * 100 for c in cfgs]
        ax.barh(range(len(cfgs)), vals, 0.7, left=left, color=color, label=name.replace('Sidecar: ', ''),
                edgecolor=SURFACE, linewidth=1.0)
        for i, (l0, v) in enumerate(zip(left, vals)):
            if v >= 7:
                ax.text(l0 + v / 2, i, f'{v:.0f}', ha='center', va='center', fontsize=7, color=INK)
        left = [a + b for a, b in zip(left, vals)]
    names = [('Linkerd ' if c.startswith('L') else 'Istio ') + LABEL[c].replace('\n', ' ') for c in cfgs]
    ax.set_yticks(range(len(cfgs)), names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 100); ax.set_xlabel(f'Share of sidecar CPU (%) at {rate:,} HTTP req/s')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.18), ncol=3, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches='tight')


def fig_kernel(rows, rate, out):
    cfgs = [c for c in ORDER if (c, rate) in rows]
    panels = [('Syscalls', ('app_syscalls_per_req', 'sidecar_syscalls_per_req')),
              ('Context switches', ('app_cswitch_per_req', 'sidecar_cswitch_per_req')),
              ('Packets', ('pod_lo_pkts_per_req', 'pod_eth_pkts_per_req'))]
    names = {'app_syscalls_per_req': 'app', 'sidecar_syscalls_per_req': 'sidecar', 'app_cswitch_per_req': 'app',
             'sidecar_cswitch_per_req': 'sidecar', 'pod_lo_pkts_per_req': 'loopback (in pod)',
             'pod_eth_pkts_per_req': 'pod-to-pod (eth0)'}
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.0))
    for ax, (title, keys) in zip(axes, panels):
        bottom = [0.0] * len(cfgs)
        for key, color in zip(keys, ('#2a78d6', '#eb6834')):
            vals = [f(rows[(c, rate)], key) for c in cfgs]
            ax.bar(range(len(cfgs)), vals, 0.72, bottom=bottom, color=color, label=names[key], edgecolor=SURFACE, linewidth=1.0)
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_xticks(range(len(cfgs)), [LABEL[c] for c in cfgs], fontsize=6.5, rotation=40, ha='right', rotation_mode='anchor')
        ax.set_title(f'{title} per HTTP request', fontsize=9, pad=16)
        ax.yaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=7.5, loc='upper left', bbox_to_anchor=(0, -0.3), ncol=2)
        mesh_groups(ax, 1.0)
    fig.suptitle(f'{rate:,} HTTP req/s', fontsize=9.5, y=1.08)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches='tight')


if __name__ == '__main__':
    rows = load(sys.argv[1])
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    rates = sorted({r for _, r in rows})
    fig_breakdown(rows, rates, f'{out}/fig_breakdown.png')
    fig_sidecar(rows, rates[0], f'{out}/fig_sidecar.png')
    fig_kernel(rows, rates[0], f'{out}/fig_kernel.png')
    print('wrote', out)
