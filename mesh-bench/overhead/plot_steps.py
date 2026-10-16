#!/usr/bin/env python3
"""plot_steps.py RESULTS_DIR [RATE]: where the sidecar's CPU grows, step by step
-> figs/fig_steps.{png,pdf}.

One row per mesh. The first panel is the L4 sidecar's vCPU by bucket; each next
panel is the change in each bucket from the previous configuration (L4 -> L7,
+authz, +traffic policy, +telemetry), with the step's net change in its title.
The three feature panels share one x scale. Notes name the components (from
components.json) that moved by at least NOTE_MIN vCPU in a feature step, under
its panel, and a containerd change of at least 0.3 vCPU (log writes outside the sidecar).
Raw values: summary.csv buckets at RATE, one run per point."""
import csv, json, re, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from plot_motivation import SC, SURFACE, INK, INK2, GRID

MESHES = [('Linkerd', ['L1-opaque', 'L2-l7', 'L3-authz', 'L4-traffic', 'L5-telemetry']),
          ('Istio', ['I1-l4', 'I2-l7', 'I3-authz', 'I4-traffic', 'I5-telemetry'])]
STEPS = ['L4 + mTLS', 'L4 \u2192 L7', '+ authz', '+ traffic policy', '+ telemetry']
NAMES = {'kernel': 'Kernel / IPC', 'mtls': 'mTLS', 'l7_parsing': 'L7 parsing', 'l7_policy': 'L7 policy',
         'telemetry': 'Telemetry', 'other': 'Runtime'}
NOTE_MIN = 0.04
# components.json keys -> readable names for the notes, per mesh
LABELS = {
    'Linkerd': [(r'^linkerd_http_retry', 'retry'), (r'^governor', 'rate limit'),
                (r'^(tracing->linkerd_tracing|tracing->linkerd_opentelemetry|tracing->opentelemetry\w*|linkerd_tracing|linkerd_opentelemetry|opentelemetry\w*)',
                 'OTel spans + export'),
                (r'^linkerd_trace_context', 'trace context'), (r'^(tracing->linkerd_http_access_log|linkerd_http_access_log)', 'access log')],
    'Istio': [(r'^(Envoy::Extensions::Tracers|Envoy::Tracing|opentelemetry::)', 'OTel tracer + export'),
              (r'^(Envoy::Formatter|Envoy::AccessLog|Envoy::Extensions::AccessLoggers)', 'access log'),
              (r'^(Envoy::Extensions::HttpFilters::RBACFilter|Envoy::Extensions::Filters::Common::RBAC)', 'RBAC filter'),
              (r'^(Envoy::Extensions::HttpFilters::LocalRateLimit|Envoy::Extensions::Filters::Common::LocalRateLimit)', 'local rate limit'),
              (r'^Envoy::Http::HeaderMap', 'header map'), (r'^nghttp2_hd', 'HPACK')]}


def f(r, k):
    return float(r[k]) if r.get(k) not in (None, '') else 0.0


def buckets(rows, c, rate):
    r = rows[(c, rate)]; rps = f(r, 'rps')
    return {b: f(r, f'sidecar_{b}_ms_per_req') * rps / 1000 for b, _, _ in SC}


def labelled(comp, mesh):
    """{(label, bucket): vCPU} for the components that have a readable name."""
    out = {}
    for b, cc in comp.items():
        for k, v in cc.items():
            lab = next((n for pat, n in LABELS[mesh] if re.match(pat, k)), None)
            if lab:
                out[(lab, b)] = out.get((lab, b), 0) + v
    return out


def main():
    res = sys.argv[1]
    rate = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    rows = {(r['cfg'], int(r['rate'])): r for r in csv.DictReader(open(f'{res}/summary.csv'))}
    order = [b for b, _, _ in SC]
    color = {b: c for b, _, c in SC}
    plt.rcParams.update({'font.size': 8, 'axes.edgecolor': INK2, 'axes.labelcolor': INK, 'xtick.color': INK2,
                         'ytick.color': INK, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE})
    fig = plt.figure(figsize=(12.5, 6.6))
    gs = GridSpec(4, 5, figure=fig, width_ratios=[1.0, 1.3, 1, 1, 1], height_ratios=[1, 0.36, 1, 0.36],
                  wspace=0.12, hspace=0.5, left=0.1, right=0.99, top=0.9, bottom=0.08)
    data = {}
    for mesh, cfgs in MESHES:
        B = [buckets(rows, c, rate) for c in cfgs]
        comp = [labelled(json.load(open(f'{res}/{c}/rep1/r{rate}/components.json')), mesh) for c in cfgs]
        cd = [f(rows[(c, rate)], 'containerd_cores') for c in cfgs]
        sc = [f(rows[(c, rate)], 'sidecar_cores') for c in cfgs]
        data[mesh] = (cfgs, B, comp, cd, sc)
    # shared x ranges: base panels, the L4 -> L7 panels, and all feature panels
    lim_base = max(max(B[0].values()) for _, B, _, _, _ in data.values()) * 1.25
    d1 = [B[1][b] - B[0][b] for _, B, _, _, _ in data.values() for b in order]
    dn = [B[i][b] - B[i - 1][b] for _, B, _, _, _ in data.values() for i in range(2, 5) for b in order]
    lim1 = (min(d1) * 1.7, max(d1) * 1.3)
    limn = (min(dn) * 1.6 - 0.12, max(dn) * 1.35)
    ys = list(range(len(order)))[::-1]
    for row, (mesh, _) in enumerate(MESHES):
        cfgs, B, comp, cd, sc = data[mesh]
        for col in range(5):
            ax = fig.add_subplot(gs[2 * row, col])
            if col == 0:
                vals = [B[0][b] for b in order]
                ax.set_xlim(0, lim_base)
                title = f'{STEPS[0]}: {sc[0]:.2f} vCPU'
            else:
                vals = [B[col][b] - B[col - 1][b] for b in order]
                ax.set_xlim(*(lim1 if col == 1 else limn))
                net = sc[col] - sc[col - 1]
                title = f'{STEPS[col]}: {net:+.2f} vCPU'.replace('-', '\u2212')
                ax.axvline(0, color=INK2, lw=0.8)
            ax.barh(ys, vals, 0.62, color=[color[b] for b in order], edgecolor=SURFACE, linewidth=0.8)
            span = ax.get_xlim()[1] - ax.get_xlim()[0]
            for y, v in zip(ys, vals):
                txt = f'{v:.2f}' if col == 0 else '0.00' if abs(v) < 0.005 else f'{v:+.2f}'.replace('-', '\u2212')
                small = abs(v) < 0.05 and col > 0
                ax.text(v + (0.012 * span if v >= 0 else -0.012 * span), y, txt, va='center',
                        ha='left' if v >= 0 else 'right', fontsize=7, color=INK2 if small else INK)
            ax.set_title(title, fontsize=8.5, loc='left', color=INK)
            ax.set_yticks(ys, [NAMES[b] for b in order] if col == 0 else [])
            ax.tick_params(axis='y', length=0)
            ax.xaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
            for s in ('top', 'right'):
                ax.spines[s].set_visible(False)
            if col == 0:
                pos = ax.get_position()
                fig.text(0.012, (pos.y0 + pos.y1) / 2, mesh, rotation=90, va='center', ha='left',
                         fontsize=11, fontweight='bold', color=INK)
            ax.set_xlabel('Sidecar vCPU' if col == 0 else '\u0394 sidecar vCPU', fontsize=7.5)
            if col >= 2:
                notes = []
                keys = set(comp[col]) | set(comp[col - 1])
                for k in sorted(keys, key=lambda k: -abs(comp[col].get(k, 0) - comp[col - 1].get(k, 0))):
                    d = comp[col].get(k, 0) - comp[col - 1].get(k, 0)
                    if abs(d) >= NOTE_MIN:
                        notes.append(f'{NAMES[k[1]]}: {k[0]} {d:+.2f}'.replace('-', '\u2212'))
                dcd = cd[col] - cd[col - 1]
                if abs(dcd) >= 0.3:
                    notes.append(f'containerd {dcd:+.2f} (log writes;\noutside the sidecar, not shown)')
                nax = fig.add_subplot(gs[2 * row + 1, col]); nax.axis('off')
                nax.text(0.0, 1.0, '\n'.join(notes[:6]) if notes else 'no component moved by \u2265 0.04',
                         transform=nax.transAxes, ha='left', va='top', fontsize=6.8,
                         color=INK if notes else INK2, linespacing=1.35)
    fig.suptitle(f'Where the sidecar\u2019s CPU grows, step by step ({rate:,} HTTP req/s, all sidecars on the node)',
                 x=0.1, ha='left', fontsize=10.5, color=INK)
    fig.text(0.1, 0.008, 'First panel: sidecar vCPU of the L4 configuration. Next panels: change in each bucket from the '
             'configuration to its left. One run per point; buckets a step does not touch move by up to ~0.1 vCPU.\n'
             'Text under each step: named components that moved by at least 0.04 vCPU in that step (perf, deciding frame). '
             'vCPU = cgroup CPU of the measured window, split by perf cycles.', fontsize=6.5, color=INK2, va='bottom')
    for ext in ('png', 'pdf'):
        fig.savefig(f'{res}/figs/fig_steps.{ext}', dpi=200)
    print('wrote', f'{res}/figs/fig_steps.png')


if __name__ == '__main__':
    main()
