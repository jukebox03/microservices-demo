#!/usr/bin/env python3
"""plot_sequence.py RESULTS_DIR [RATE]: sidecar vCPU by bucket for the feature
ladder in order, keeping only the steps that matter -> figs/fig_sequence.{png,pdf}.
draw() puts the same panels into another figure (plot_motivation.py, panel f).

A step is drawn only if some bucket moved by at least STEP_MIN vCPU from the
configuration before it, or listed in FORCE (Istio +traffic, drawn to show it
costs nothing); the others (+authz) stay enabled in the later bars. In each
later bar, the growth since the bar on its left is hatched and labelled only
for the buckets the step is expected to change (EXPECT) and only if it is at
least NOTE_MIN vCPU; buckets that should stay put carry no change. Under each
step, the components behind it (components.json), by name. Raw values:
summary.csv buckets at RATE, one run per point."""
import csv, json, sys, textwrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Patch
from plot_motivation import SC, SURFACE, INK, INK2, GRID
from plot_steps import labelled

LADDER = {'Linkerd': [('L1-opaque', 'L4'), ('L2-l7', 'L7'), ('L3-authz', '+ authz'), ('L4-traffic', '+ traffic policy'),
                      ('L5-telemetry', '+ telemetry')],
          'Istio': [('I1-l4', 'L4'), ('I2-l7', 'L7'), ('I3-authz', '+ authz'), ('I4-traffic', '+ traffic policy'),
                    ('I5-telemetry', '+ telemetry')]}
NAMES = {'kernel': 'Kernel / IPC', 'mtls': 'mTLS', 'l7_parsing': 'L7 parsing', 'l7_policy': 'L7 policy',
         'telemetry': 'Telemetry', 'other': 'Runtime'}
# buckets a step changes by design. L7 adds HTTP/2 termination, routing/LB, HTTP
# metrics and per-request proxy work, and coalesces requests (fewer syscalls);
# mTLS encrypts the same bytes. Telemetry also adds trace headers (L7 parsing).
EXPECT = {'L7': {'l7_parsing', 'l7_policy', 'telemetry', 'other', 'kernel'},
          '+ authz': {'l7_policy'}, '+ traffic policy': {'l7_policy'}, '+ telemetry': {'telemetry', 'l7_parsing'}}
L7_WHY = 'HTTP/2 termination,\nrouting and LB, HTTP metrics;\nfewer syscalls per request'
STEP_MIN, NOTE_MIN = 0.1, 0.15
# drawn even though nothing moved, to show that it costs nothing
FORCE = {('Istio', '+ traffic policy')}
CAPTION = ('Each bar adds to the one on its left. Changes are shown only for the parts a step is designed to change '
           f'(L7: all but mTLS; policies: L7 policy; telemetry: telemetry, L7 parsing) and only if \u2265 {NOTE_MIN} vCPU.\n'
           f'Steps that changed no part by \u2265 {STEP_MIN} vCPU are not drawn but stay on in later bars ({{skipped}}). '
           '* Linkerd writes the access log to stdout; that cost is in containerd, outside the sidecar.')


def f(r, k):
    return float(r[k]) if r.get(k) not in (None, '') else 0.0


def draw(fig, spec, res, rate, fs=1.0, legend_w=1.25, wrap=None, notes=True):
    """Draw the Linkerd and Istio panels and a legend into the SubplotSpec spec;
    returns (axes, skipped steps per mesh). fs scales the fonts; wrap breaks the
    text under the bars at that many characters (narrow figures); notes=False
    leaves that text out."""
    rows = {(r['cfg'], int(r['rate'])): r for r in csv.DictReader(open(f'{res}/summary.csv'))}
    order = [b for b, _, _ in SC]
    color = {b: c for b, _, c in SC}

    def buckets(c):
        r = rows[(c, rate)]; rps = f(r, 'rps')
        return {b: f(r, f'sidecar_{b}_ms_per_req') * rps / 1000 for b in order}

    # drawn steps, each with the set of buckets expected to change since the drawn bar before it
    shown, skipped = {}, {}
    for mesh, lad in LADDER.items():
        keep, prev, pending = [(lad[0][0], lad[0][1], set())], buckets(lad[0][0]), set()
        skipped[mesh] = []
        for c, name in lad[1:]:
            cur = buckets(c)
            pending |= EXPECT[name]
            if (mesh, name) in FORCE or max(abs(cur[b] - prev[b]) for b in order) >= STEP_MIN:
                keep.append((c, name, pending)); pending = set()
            else:
                skipped[mesh].append(name.replace('+ ', ''))
            prev = cur
        shown[mesh] = keep
    sub = spec.subgridspec(1, 3, width_ratios=[len(shown['Linkerd']), len(shown['Istio']), legend_w], wspace=0.08)
    axes, ax0 = [], None
    for i, mesh in enumerate(LADDER):
        ax = fig.add_subplot(sub[0, i], sharey=ax0)
        ax0 = ax0 or ax
        axes.append(ax)
        cfgs = shown[mesh]
        B = [buckets(c) for c, _, _ in cfgs]
        comp = [labelled(json.load(open(f'{res}/{c}/rep1/r{rate}/components.json')), mesh) for c, _, _ in cfgs]
        sc = [f(rows[(c, rate)], 'sidecar_cores') for c, _, _ in cfgs]
        xs = list(range(len(cfgs)))
        W = 0.5
        bottom = [0.0] * len(cfgs)
        for b in order:
            vals = [Bi[b] for Bi in B]
            ax.bar(xs, vals, W, bottom=bottom, color=color[b], edgecolor=SURFACE, linewidth=1.0, label=NAMES[b])
            for x, b0, v in zip(xs, bottom, vals):
                d = v - B[x - 1][b] if x else 0.0
                if not x or b not in cfgs[x][2] or abs(d) < NOTE_MIN:
                    continue
                if d > 0:      # the added part of the segment
                    ax.bar(x, d, W, bottom=b0 + v - d, facecolor='none', edgecolor=SURFACE, hatch='////', linewidth=0)
                ax.text(x + W / 2 + 0.03, b0 + v - d / 2 if d > 0 else b0 + v / 2, f'{d:+.1f}'.replace('-', '\u2212'),
                        ha='left', va='center', fontsize=8 * fs, color=INK, fontweight='bold')
            bottom = [b0 + v for b0, v in zip(bottom, vals)]
        for x, t in enumerate(sc):
            ax.text(x, t + 0.2, f'{t:.1f}', ha='center', va='bottom', fontsize=9 * fs, color=INK, fontweight='bold')
        # under each step: what the change is made of, by name
        for k in range(1, len(cfgs) if notes else 1):
            if k == 1:
                txt = L7_WHY
            else:
                cand = {}
                for key in set(comp[k]) | set(comp[k - 1]):
                    d = comp[k].get(key, 0) - comp[k - 1].get(key, 0)
                    if key[1] in cfgs[k][2] and d >= 0.04:
                        cand[key[0]] = cand.get(key[0], 0) + d
                txt = '\n'.join(lab for lab, _ in sorted(cand.items(), key=lambda x: -x[1])[:3])
                if not any(abs(B[k][b] - B[k - 1][b]) >= NOTE_MIN for b in cfgs[k][2]):
                    txt = 'almost no change'
                if mesh == 'Linkerd' and cfgs[k][1] == '+ telemetry':
                    txt += '\naccess log writes: containerd*'
            if wrap:
                txt = '\n'.join(textwrap.fill(line, wrap) for line in txt.replace(',\n', ', ').replace(';\n', '; ').split('\n'))
            ax.annotate(txt, xy=(k, 0), xycoords=('data', 'axes fraction'), xytext=(0, -22 * fs),
                        textcoords='offset points', ha='center', va='top', fontsize=7 * fs, color=INK2, linespacing=1.3)
        ax.set_xticks(xs, [n for _, n, _ in cfgs], fontsize=9 * fs)
        ax.set_xlim(-0.45, len(cfgs) - 0.4)
        ax.set_ylim(0, 13)
        ax.set_title(mesh, fontsize=10 * fs, loc='left', color=INK, fontweight='bold')
        ax.yaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
        ax.tick_params(axis='y', labelsize=8 * fs)
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
        if i == 0:
            ax.set_ylabel('Sidecar vCPU', fontsize=9 * fs)
        else:
            ax.tick_params(axis='y', labelleft=False)
    lax = fig.add_subplot(sub[0, 2]); lax.axis('off')
    h, l = ax0.get_legend_handles_labels()
    h = h[::-1] + [Patch(facecolor='#b4b3ad', edgecolor=SURFACE, hatch='////', linewidth=0)]
    l = l[::-1] + ['Added by the step']
    lax.legend(h, l, loc='center left', frameon=False, fontsize=8 * fs, handlelength=1.4, handleheight=1.2)
    return axes, skipped


def caption(skipped):
    return CAPTION.format(skipped='; '.join(f"{m}: {', '.join(s)}" for m, s in skipped.items() if s))


def main():
    res = sys.argv[1]
    rate = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    plt.rcParams.update({'font.size': 8, 'axes.edgecolor': INK2, 'axes.labelcolor': INK, 'xtick.color': INK,
                         'ytick.color': INK2, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
                         'hatch.linewidth': 0.9})
    fig = plt.figure(figsize=(12.5, 5.6))
    gs = GridSpec(1, 1, figure=fig, left=0.065, right=0.995, top=0.9, bottom=0.25)
    axes, skipped = draw(fig, gs[0, 0], res, rate)
    fig.suptitle(f'Sidecar CPU as the mesh moves from L4 to L7 and features are added ({rate:,} HTTP req/s, all sidecars on the node)',
                 x=0.065, ha='left', fontsize=10.5, color=INK)
    fig.text(0.065, 0.012, caption(skipped) + '\nOne run per point; vCPU = cgroup CPU of the measured window, split by perf cycles.',
             fontsize=6.5, color=INK2, va='bottom')
    for ext in ('png', 'pdf'):
        fig.savefig(f'{res}/figs/fig_sequence.{ext}', dpi=200)
    print('wrote', f'{res}/figs/fig_sequence.png', 'skipped', skipped)


if __name__ == '__main__':
    main()
