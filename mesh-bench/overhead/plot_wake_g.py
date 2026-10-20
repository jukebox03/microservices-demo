#!/usr/bin/env python3
"""plot_wake_g.py OUT_DIR: panel (g) of fig_motivation (the app containers' CPU
by code kind, the kernel split by the syscall that entered it) for no sidecar
and DPUMesh before and after the Comch fast-path wake, from the 2026-10-19
wake runs. Same buckets, colours and helpers as plot_motivation.py (g); each
bar comes from its own run directory:
  No sidecar          wake-20261019e/W0-nosidecar
  DPUMesh, before     wake-20261019d/L1-legacy   (ARM/DOORBELL wake, nap 10->100 us, linger 1 ms)
  DPUMesh, now        wake-20261019e/G1-default  (Comch fast-path wake, sleep on every empty poll)
All at 1,500 HTTP req/s, jet2 at 2.3 GHz, DPU proxy feature/dpa-mux + comch-wake.
Writes OUT_DIR/fig_wake_g.{png,pdf}."""
import os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import plot_motivation as M

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')
BARS = [('wake-20261019e', 'W0-nosidecar', 'No sidecar'),
        ('wake-20261019d', 'L1-legacy', 'DPUMesh, before\n(DOORBELL + polling)'),
        ('wake-20261019e', 'G1-default', 'DPUMesh, now\n(fast-path wake)')]
RATE = 1500


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RES, 'wake-20261019e', 'figs')
    parts = ([('business', 'Business logic', '#eda100', None)] + [(k, n, c, None) for k, n, c, _ in M.KGROUPS] +
             [('dpumesh', 'DPUMesh host stack', '#2a78d6', None),
              ('rpc', 'RPC stack (gRPC, HTTP/2, protobuf)', '#1baf7a', None),
              ('runtime', 'Runtime (GC, scheduler, VM)', '#008300', None),
              ('unresolved', 'JIT / interpreted code', '#d6d5cf', '////')])
    A = [dict(M.app_parts(f'{RES}/{run}', cfg, RATE), **M.app_kernel_split(f'{RES}/{run}', cfg, RATE))
         for run, cfg, _ in BARS]

    fig = plt.figure(figsize=(9.4, 3.7), facecolor=M.SURFACE)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.6, 1], wspace=0.05, left=0.08, right=0.99, top=0.88, bottom=0.17)
    ax = fig.add_subplot(gs[0, 0]); ax.set_facecolor(M.SURFACE)
    xs = range(len(BARS)); bottom = [0.0] * len(BARS); W = 0.55
    for key, name, color, hatch in parts:
        vals = [a[key] for a in A]
        ax.bar(xs, vals, W, bottom=bottom, color=color, label=name, edgecolor=M.SURFACE, linewidth=1.0, hatch=hatch)
        for x, b0, v in zip(xs, bottom, vals):
            if v >= 0.6:
                ax.text(x, b0 + v / 2, f'{v:.1f}', ha='center', va='center', fontsize=7,
                        color='#ffffff' if key in ('dpumesh', 'k_socket') else M.INK,
                        bbox=dict(boxstyle='round,pad=0.1', fc=M.SURFACE, ec='none', alpha=0.7) if hatch else None)
            elif key == 'k_socket':
                ax.annotate(f'{v:.1f}', (x + W / 2, b0 + v / 2), xytext=(x + W / 2 + 0.08, b0 + v / 2), fontsize=7,
                            va='center', color=M.INK, arrowprops=dict(arrowstyle='-', color=M.INK2, lw=0.6))
        bottom = [b0 + v for b0, v in zip(bottom, vals)]
    for x, t in zip(xs, bottom):
        ax.text(x, t + 0.3, f'{t:.1f}', ha='center', va='bottom', fontsize=7.5)
    for x, a in enumerate(A):
        k0 = a['business']; k1 = k0 + sum(a[k] for k, _, _, _ in M.KGROUPS)
        bx = x - W / 2 - 0.05
        ax.plot([bx + 0.03, bx, bx, bx + 0.03], [k0 + 0.05, k0 + 0.05, k1 - 0.05, k1 - 0.05], color=M.INK2, lw=0.7)
        ax.text(bx - 0.03, (k0 + k1) / 2, f'Kernel\n{k1 - k0:.1f}', ha='right', va='center', fontsize=6.5,
                color=M.INK2, linespacing=1.1)
    ax.set_xticks(list(xs), [n for _, _, n in BARS]); ax.set_ylabel('App vCPU'); M.grid(ax)
    ax.set_title('Inside the app containers, DPUMesh before and after the fast-path wake',
                 fontsize=9.5, loc='left')
    ax.set_ylim(0, max(bottom) * 1.15); ax.set_xlim(-0.75, len(BARS) - 0.45)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    lax = fig.add_subplot(gs[0, 1]); lax.axis('off')
    h, l = ax.get_legend_handles_labels()
    lax.legend(h[::-1], l[::-1], loc='center left', frameon=False, fontsize=7.5)
    os.makedirs(out, exist_ok=True)
    fig.savefig(f'{out}/fig_wake_g.png', dpi=300, facecolor=M.SURFACE)
    fig.savefig(f'{out}/fig_wake_g.pdf', facecolor=M.SURFACE)
    for (_, cfg, n), a in zip(BARS, A):
        print(f"{n.splitlines()[0]:18} total {sum(a[k] for k in ('business','dpumesh','rpc','runtime','unresolved','k_socket','k_wait','k_other')):5.2f} " +
              ' '.join(f'{k} {a[k]:.2f}' for k in ('business', 'k_socket', 'k_wait', 'k_other', 'dpumesh', 'rpc', 'runtime', 'unresolved')))
    print('wrote', f'{out}/fig_wake_g.png')


if __name__ == '__main__':
    main()
