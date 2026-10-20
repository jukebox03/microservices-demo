#!/usr/bin/env python3
"""plot_motivation.py RESULTS_DIR [RATE]: one-page motivation figure from the
MeshInsight-style run (summary.csv, <cfg>/latency1/k6.json), written next to
the other figures as figs/fig_motivation.{png,pdf}.

(a) host vCPU at RATE: app user / app kernel / sidecar kernel / sidecar user
    for no sidecar, Linkerd/Istio L4 and L7
(b) the sidecar coalesces the app's traffic: app syscalls, app wakeups and
    pod-to-pod packets per HTTP request, Linkerd/Istio L4 and L7 (no sidecar not drawn)
(c) the sidecar's own syscalls, wakeups and pod-to-pod packets per request, L4
    next to L7 (why its kernel CPU drops at L7)
(d) the sidecar's own CPU by bucket in vCPU, L4 next to L7 for each mesh
(e) latency with one request outstanding
(f) the app containers' CPU by code kind (classify_app.py): business
    logic (bottom, labelled with the mean of the three), kernel, RPC stack, runtime,
    JIT/interpreted code
(g) the app containers' CPU by code kind for no sidecar, Linkerd L7, Istio L7
    and DPUMesh (run_dpumesh.py), with the DPUMesh host stack as a bucket and the
    kernel split by the syscall that entered it (kernel_lang.py): socket I/O,
    waiting and wakeups, other
(h) sidecar vCPU from L4 to L7 and as features are added, the steps that
    matter in order (plot_sequence.draw, without the notes under the bars)
No footnotes: the conditions and reading notes are in figs/fig_motivation.md.
DPUMESH_SRC=<run dir>/<cfg> takes (g)'s DPUMesh bar from another run (e.g.
../results/wake-20261019e/G1-default, the Comch fast-path wake build) and FIG_NAME
names the output (default fig_motivation).
Raw values: vCPU are the cgroup CPU of each point's measured window, split by
the perf shares of the same point."""
import csv, json, os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
APP_K, APP_U = '#8d8c87', '#d6d5cf'
SC = [('kernel', 'Sidecar kernel / IPC', '#2a78d6'), ('mtls', 'Sidecar mTLS', '#eb6834'),
      ('l7_parsing', 'Sidecar L7 parsing', '#1baf7a'), ('l7_policy', 'Sidecar L7 policy', '#eda100'),
      ('telemetry', 'Sidecar telemetry', '#e87ba4'), ('other', 'Sidecar runtime', '#008300')]
MAIN = [('N0-nosidecar', 'No sidecar'), ('L1-opaque', 'Linkerd\nL4'), ('L2-l7', 'Linkerd\nL7'),
        ('I1-l4', 'Istio\nL4'), ('I2-l7', 'Istio\nL7')]

plt.rcParams.update({'font.size': 8, 'axes.edgecolor': INK2, 'axes.labelcolor': INK, 'xtick.color': INK2,
                     'ytick.color': INK2, 'text.color': INK, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
                     'savefig.facecolor': SURFACE, 'axes.spines.top': False, 'axes.spines.right': False})


def vcpu(rows, cfg, rate):
    r = rows[(cfg, rate)]
    g = lambda k: float(r[k]) if r.get(k) not in (None, '') else 0.0
    rps = g('rps')
    v = lambda k: g(k) * rps / 1000          # ms per request -> vCPU
    d = {'app_kernel': v('app_kernel_ms_per_req'),
         'app_user': v('app_app_grpc_ms_per_req') + v('app_app_user_ms_per_req'),
         'app_grpc': v('app_app_grpc_ms_per_req'), 'app_rest': v('app_app_user_ms_per_req')}
    for b, _, _ in SC:
        d[b] = v(f'sidecar_{b}_ms_per_req')
    d['total'] = g('app_cores') + g('sidecar_cores')
    d['sidecar'] = g('sidecar_cores')
    return d


def service_cpu(d):
    """App-container vCPU per service in the measured window (cgroup counters)."""
    m = json.load(open(f'{d}/meta.json')); sn = json.load(open(f'{d}/snap.json'))
    a, b = sn['a'], sn['b']; dt = b['t'] - a['t']
    cpu = {}
    for k, c in m['containers'].items():
        if c['role'] == 'sidecar':
            continue
        kind = c['pod'].rsplit('-', 1)[0] if c['pod'].rsplit('-', 1)[-1].isdigit() else c['pod']
        cpu[kind] = cpu.get(kind, 0) + (b['cg'][k]['usage_usec'] - a['cg'][k]['usage_usec']) / 1e6 / dt
    return cpu


def src(res, cfg):
    """(run dir, cfg) a bar is read from: DPUMESH_SRC moves the DPUMesh one."""
    if cfg == 'D1-dpumesh' and os.environ.get('DPUMESH_SRC'):
        return os.path.split(os.environ['DPUMESH_SRC'].rstrip('/'))
    return res, cfg


def app_parts(res, cfg, rate):
    """App-container vCPU by bucket: each service's cgroup CPU split by its perf shares."""
    res, cfg = src(res, cfg)
    d = f'{res}/{cfg}/rep1/r{rate}'
    cpu = service_cpu(d)
    out = {x: 0.0 for x in ('kernel', 'rpc', 'runtime', 'business', 'unresolved', 'dpumesh')}
    for kind, cc in json.load(open(f'{d}/app_buckets.json')).items():
        t = sum(cc.values()) or 1
        for x in out:
            out[x] += cpu.get(kind, 0) * cc.get(x, 0) / t
    return out


# the app kernel by the syscall that entered it (kernel_lang.py groups)
KGROUPS = [('k_socket', 'Kernel: socket I/O', '#4f4e4a', ('socket I/O',)),
           ('k_wait', 'Kernel: waiting and wakeups\n(futex, epoll, ppoll, timerfd, sleep)', APP_K,
            ('park/wake', 'event wait', 'timerfd')),
           ('k_other', 'Kernel: other (syscall entry, irq)', '#b4b3ad', ('entry/exit', 'irq', 'other'))]


def app_kernel_split(res, cfg, rate):
    """Each service's kernel vCPU (as app_parts) split by its kernel_groups.json cycles."""
    res, cfg = src(res, cfg)
    d = f'{res}/{cfg}/rep1/r{rate}'
    cpu = service_cpu(d)
    kg = json.load(open(f'{d}/kernel_groups.json'))
    out = {k: 0.0 for k, _, _, _ in KGROUPS}
    for kind, cc in json.load(open(f'{d}/app_buckets.json')).items():
        kv = cpu.get(kind, 0) * cc.get('kernel', 0) / (sum(cc.values()) or 1)
        g = kg.get(kind, {}); gt = sum(g.values()) or 1
        for k, _, _, groups in KGROUPS:
            out[k] += kv * sum(g.get(x, 0) for x in groups) / gt
    return out


def grid(ax):
    ax.yaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)


def panel_label(ax, s):
    ax.text(-0.08, 1.04, s, transform=ax.transAxes, fontsize=10, fontweight='bold', va='bottom')


EVENT_COLORS = {'N0-nosidecar': '#8d8c87', 'L1-opaque': '#2a78d6', 'L2-l7': '#86b6ef', 'I1-l4': '#6250d6', 'I2-l7': '#a99ff0'}
APP_EVENTS = [('app_syscalls_per_req', 'App syscalls per request'), ('app_vol_cs_per_req', 'App wakeups per request'),
              ('pod_eth_pkts_per_req', 'Pod-to-pod packets per request')]
SIDECAR_EVENTS = [('sidecar_syscalls_per_req', 'Sidecar syscalls per request'),
                  ('sidecar_vol_cs_per_req', 'Sidecar wakeups per request'),
                  ('pod_eth_pkts_per_req', 'Pod-to-pod packets per request')]


def events(fig, spec, rows, rate, cfgs, metrics, title, label=None):
    """Kernel events per HTTP request, one small panel per metric, one bar per configuration."""
    sub = spec.subgridspec(1, len(metrics), wspace=0.28)
    for j, (key, name) in enumerate(metrics):
        ax = fig.add_subplot(sub[0, j])
        if j == 0:
            if label:
                ax.text(-0.25, 1.22, label, transform=ax.transAxes, fontsize=10, fontweight='bold', va='bottom')
            ax.text(-0.02, 1.22, title, transform=ax.transAxes, fontsize=9.5, va='bottom')
        vals = [float(rows[(c, rate)][key]) for c, _ in cfgs]
        ax.bar(range(len(cfgs)), vals, 0.7, color=[EVENT_COLORS[c] for c, _ in cfgs], edgecolor=SURFACE)
        for x, v in enumerate(vals):
            ax.text(x, v * 1.02, f'{v:.0f}', ha='center', va='bottom', fontsize=7)
        ax.set_xticks(range(len(cfgs)), [n.replace('No sidecar', 'None') for _, n in cfgs], fontsize=6.8)
        ax.set_title(name, fontsize=8); grid(ax); ax.tick_params(axis='y', labelsize=7)
        ax.set_ylim(0, max(vals) * 1.18)


def main():
    res = sys.argv[1]
    rate = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    rows = {(r['cfg'], int(r['rate'])): r for r in csv.DictReader(open(f'{res}/summary.csv'))}
    V = {c: vcpu(rows, c, rate) for c, _ in MAIN}

    fig = plt.figure(figsize=(12.5, 23.2))
    # (a)-(d), (g), (h) span the page; (e) and (f) share a row. Large on purpose:
    # the panels are cut out one by one.
    gs = GridSpec(7, 2, figure=fig, height_ratios=[0.75, 0.7, 0.7, 0.8, 1.0, 1.0, 1.2], hspace=0.6, wspace=0.25,
                  left=0.07, right=0.98, top=0.95, bottom=0.04)
    fig.suptitle(f'Sidecar CPU overhead, Online Boutique ({rate:,} HTTP req/s offered to every configuration)',
                 fontsize=11, y=0.975)
    SC_USER = '#6250d6'

    # (a) host vCPU: app user / app kernel / sidecar kernel / sidecar user
    ax = fig.add_subplot(gs[0, :]); panel_label(ax, '(a)')
    for c, _ in MAIN:
        V[c]['sc_user'] = sum(V[c][b] for b, _, _ in SC[1:])
    segs = [('app_kernel', 'App kernel', APP_K), ('app_user', 'App user', APP_U),
            ('kernel', 'Sidecar kernel', '#2a78d6'), ('sc_user', 'Sidecar user', SC_USER)]
    xs = range(len(MAIN)); bottom = [0.0] * len(MAIN)
    for key, name, color in segs:
        vals = [V[c][key] for c, _ in MAIN]
        ax.bar(xs, vals, 0.62, bottom=bottom, color=color, label=name, edgecolor=SURFACE, linewidth=1.0)
        bottom = [b + v for b, v in zip(bottom, vals)]
    base = V['N0-nosidecar']['total']
    for x, (c, _) in zip(xs, MAIN):
        t = V[c]['total']
        lab = f'{t:.1f}' if c == 'N0-nosidecar' else f'{t:.1f}  (+{(t - base) / base * 100:.0f}%)'
        ax.text(x, t + 0.3, lab, ha='center', va='bottom', fontsize=7.5)
    ax.set_xticks(list(xs), [n for _, n in MAIN], fontsize=8.5)
    ax.set_ylabel('Host vCPU'); ax.set_ylim(0, 25); grid(ax)
    ax.set_title('Host CPU', fontsize=9.5, loc='left')
    h, l = ax.get_legend_handles_labels()
    ax.legend(h[::-1], l[::-1], loc='center left', bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=7.5)
    ax.set_position([0.07, ax.get_position().y0, 0.74, ax.get_position().height])

    cfgs = MAIN[1:]

    # (d) the sidecar's CPU by bucket, in vCPU, L4 next to L7 for each mesh
    ax = fig.add_subplot(gs[3, :]); panel_label(ax, '(d)')
    order = [('L1-opaque', 'Linkerd L4'), ('L2-l7', 'Linkerd L7'), ('I1-l4', 'Istio L4'), ('I2-l7', 'Istio L7')]
    ys = [0, 1, 2.5, 3.5]
    left = [0.0] * len(order)
    for b, name, color in SC:
        vals = [V[c][b] for c, _ in order]
        ax.barh(ys, vals, 0.72, left=left, color=color, edgecolor=SURFACE, linewidth=1.0, label=name.replace('Sidecar ', ''))
        for y, l0, v in zip(ys, left, vals):
            if v >= 0.45:
                ax.text(l0 + v / 2, y, f'{v:.1f}', ha='center', va='center', fontsize=7)
        left = [a + v for a, v in zip(left, vals)]
    for y, (c, _), t in zip(ys, order, left):
        ax.text(t + 0.12, y, f'{t:.1f}', ha='left', va='center', fontsize=7.5)
    ax.set_yticks(ys, [n for _, n in order]); ax.invert_yaxis()
    ax.set_xlim(0, max(left) * 1.08); ax.set_xlabel('Sidecar vCPU')
    ax.xaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
    ax.set_title('Inside the sidecar', fontsize=9.5, loc='left')
    h, l = ax.get_legend_handles_labels()
    ax.legend(h, l, loc='center left', bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=7.5)
    ax.set_position([0.07, ax.get_position().y0, 0.74, ax.get_position().height])

    # (b) the sidecar coalesces the app's traffic: per HTTP request, app syscalls,
    # app thread wakeups (voluntary context switches) and pod-to-pod packets
    events(fig, gs[1, :], rows, rate, MAIN[1:], APP_EVENTS, 'Sidecar coalesces the app\'s traffic', '(b)')

    # (c) the sidecar's own kernel events per request, L4 next to L7: why its kernel CPU drops at L7
    events(fig, gs[2, :], rows, rate, MAIN[1:], SIDECAR_EVENTS, 'L7 sidecar makes fewer kernel events per request', '(c)')

    # (e) latency, one outstanding request
    ax = fig.add_subplot(gs[4, 0]); panel_label(ax, '(e)')
    lat = []
    for c, n in MAIN:
        d = json.load(open(f'{res}/{c}/latency1/k6.json'))['dur']
        lat.append((n, d['avg'], d['p(99)']))
    xs = range(len(lat))
    ax.bar(xs, [a for _, a, _ in lat], 0.6, color='#2a78d6', label='mean', edgecolor=SURFACE)
    ax.scatter(xs, [p for _, _, p in lat], marker='_', s=240, color='#eb6834', linewidths=2.5, label='p99', zorder=3)
    for x, (_, a, p) in zip(xs, lat):
        ax.text(x, a / 2, f'{a:.1f}', ha='center', va='center', fontsize=7, color='#ffffff')
        ax.text(x, p + 1, f'{p:.0f}', ha='center', va='bottom', fontsize=7)
    ax.set_xticks(list(xs), [n for n, _, _ in lat], fontsize=7.5); ax.set_ylabel('Latency per HTTP request (ms)'); grid(ax)
    ax.set_title('Latency, one request outstanding', fontsize=9.5, loc='left')
    ax.legend(frameon=False, fontsize=7, loc='upper left')

    # (f) the app containers' CPU by what the code is (classify_app.py): business
    # logic (bottom) stays, kernel / runtime / RPC stack shrink with the sidecar
    ax = fig.add_subplot(gs[4, 1]); panel_label(ax, '(f)')
    cfgs3 = [('N0-nosidecar', 'No sidecar'), ('L2-l7', 'Linkerd L7'), ('I2-l7', 'Istio L7')]
    parts = [('business', 'Business logic', '#eda100', None), ('kernel', 'Kernel', APP_K, None),
             ('rpc', 'RPC stack (gRPC, HTTP/2, protobuf)', '#1baf7a', None),
             ('runtime', 'Runtime (GC, scheduler, VM)', '#008300', None),
             ('unresolved', 'JIT / interpreted code', '#d6d5cf', '////')]
    A = {c: app_parts(res, c, rate) for c, _ in cfgs3}
    xs = range(len(cfgs3)); bottom = [0.0] * len(cfgs3)
    for key, name, color, hatch in parts:
        vals = [A[c][key] for c, _ in cfgs3]
        ax.bar(xs, vals, 0.55, bottom=bottom, color=color, label=name, edgecolor=SURFACE, linewidth=1.0, hatch=hatch)
        for x, b0, v in zip(xs, bottom, vals):
            if key == 'business':      # the small one that stays put: one value (the mean), beside the bar
                ax.annotate(f'\u2248{sum(vals) / len(vals):.2f}', (x + 0.28, b0 + v / 2), xytext=(x + 0.36, b0 + v / 2), fontsize=7,
                            va='center', color=INK, arrowprops=dict(arrowstyle='-', color=INK2, lw=0.6))
            elif v >= 1.0:
                ax.text(x, b0 + v / 2, f'{v:.1f}', ha='center', va='center', fontsize=7,
                        bbox=dict(boxstyle='round,pad=0.1', fc=SURFACE, ec='none', alpha=0.7) if hatch else None)
        bottom = [b0 + v for b0, v in zip(bottom, vals)]
    for x, t in zip(xs, bottom):
        ax.text(x, t + 0.3, f'{t:.1f}', ha='center', va='bottom', fontsize=7.5)
    ax.set_xticks(list(xs), [n for _, n in cfgs3]); ax.set_ylabel('App vCPU'); grid(ax)
    ax.set_title('Inside the app containers', fontsize=9.5, loc='left')
    h, l = ax.get_legend_handles_labels()
    ax.legend(h[::-1], l[::-1], loc='upper center', bbox_to_anchor=(0.45, -0.14), ncol=2, frameon=False,
              fontsize=6.3, handlelength=1.4, columnspacing=1.0)
    ax.set_ylim(0, max(bottom) * 1.15); ax.set_xlim(-0.5, len(cfgs3) - 0.2)

    # (g) the app containers with DPUMesh next to the sidecar meshes: the kernel,
    # split by the syscall that entered it, loses its socket I/O and gains
    # waiting; the DPUMesh host stack appears (stacked right above the kernel)
    cfgs4 = [(c, n) for c, n in [('N0-nosidecar', 'No sidecar'), ('L2-l7', 'Linkerd L7'), ('I2-l7', 'Istio L7'),
                                  ('D1-dpumesh', 'DPUMesh')] if os.path.exists('{}/{}/rep1/r{}/app_buckets.json'.format(*src(res, c), rate))]
    sub = gs[5, :].subgridspec(1, 2, width_ratios=[1.6, 1], wspace=0.05)
    ax = fig.add_subplot(sub[0, 0]); panel_label(ax, '(g)')
    parts4 = ([('business', 'Business logic', '#eda100', None)] + [(k, n, c, None) for k, n, c, _ in KGROUPS] +
              [('dpumesh', 'DPUMesh host stack', '#2a78d6', None),
               ('rpc', 'RPC stack (gRPC, HTTP/2, protobuf)', '#1baf7a', None),
               ('runtime', 'Runtime (GC, scheduler, VM)', '#008300', None),
               ('unresolved', 'JIT / interpreted code', '#d6d5cf', '////')])
    A4 = {c: dict(app_parts(res, c, rate), **app_kernel_split(res, c, rate)) for c, _ in cfgs4}
    xs = range(len(cfgs4)); bottom = [0.0] * len(cfgs4)
    W = 0.55
    for key, name, color, hatch in parts4:
        vals = [A4[c][key] for c, _ in cfgs4]
        ax.bar(xs, vals, W, bottom=bottom, color=color, label=name, edgecolor=SURFACE, linewidth=1.0, hatch=hatch)
        for x, b0, v in zip(xs, bottom, vals):
            if v >= 0.6:
                ax.text(x, b0 + v / 2, f'{v:.1f}', ha='center', va='center', fontsize=7,
                        color='#ffffff' if key in ('dpumesh', 'k_socket') else INK,
                        bbox=dict(boxstyle='round,pad=0.1', fc=SURFACE, ec='none', alpha=0.7) if hatch else None)
            elif key == 'k_socket':    # too thin to hold its value: beside the bar
                ax.annotate(f'{v:.1f}', (x + W / 2, b0 + v / 2), xytext=(x + W / 2 + 0.08, b0 + v / 2), fontsize=7,
                            va='center', color=INK, arrowprops=dict(arrowstyle='-', color=INK2, lw=0.6))
        bottom = [b0 + v for b0, v in zip(bottom, vals)]
    for x, t in zip(xs, bottom):
        ax.text(x, t + 0.3, f'{t:.1f}', ha='center', va='bottom', fontsize=7.5)
    # the kernel total, bracketed left of each bar
    for x, (c, _) in enumerate(cfgs4):
        k0 = A4[c]['business']; k1 = k0 + sum(A4[c][k] for k, _, _, _ in KGROUPS)
        bx = x - W / 2 - 0.05
        ax.plot([bx + 0.03, bx, bx, bx + 0.03], [k0 + 0.05, k0 + 0.05, k1 - 0.05, k1 - 0.05], color=INK2, lw=0.7)
        ax.text(bx - 0.03, (k0 + k1) / 2, f'Kernel\n{k1 - k0:.1f}', ha='right', va='center', fontsize=6.5,
                color=INK2, linespacing=1.1)
    ax.set_xticks(list(xs), [n for _, n in cfgs4]); ax.set_ylabel('App vCPU'); grid(ax)
    ax.set_title('Inside the app containers, with DPUMesh', fontsize=9.5, loc='left')
    ax.set_ylim(0, max(bottom) * 1.15); ax.set_xlim(-0.75, len(cfgs4) - 0.45)
    lax = fig.add_subplot(sub[0, 1]); lax.axis('off')
    h, l = ax.get_legend_handles_labels()
    lax.legend(h[::-1], l[::-1], loc='center left', frameon=False, fontsize=7.5)

    # (h) sidecar CPU from L4 to L7 and as features are added, the steps that
    # matter in order (plot_sequence.py)
    from plot_sequence import draw
    seq_axes, _ = draw(fig, gs[6, :], res, rate, legend_w=1.25, notes=False)
    seq_axes[0].text(-0.1, 1.1, '(h)', transform=seq_axes[0].transAxes, fontsize=10, fontweight='bold', va='bottom')
    seq_axes[0].text(0.0, 1.1, 'From L4 to L7, then features added', transform=seq_axes[0].transAxes,
                     fontsize=9.5, va='bottom')

    os.makedirs(f'{res}/figs', exist_ok=True)
    name = os.environ.get('FIG_NAME', 'fig_motivation')
    fig.savefig(f'{res}/figs/{name}.png', dpi=400)
    fig.savefig(f'{res}/figs/{name}.pdf')
    print('wrote', f'{res}/figs/{name}.png')


if __name__ == '__main__':
    main()
