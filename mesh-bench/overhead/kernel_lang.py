#!/usr/bin/env python3
"""kernel_lang.py RUN_DIR...: app kernel time by the syscall that entered it,
per language, next to DPUMesh user time and syscalls and voluntary context
switches per HTTP request -> RUN_DIR/kernel_lang.txt; the kernel cycles per
service and group -> RUN_DIR/kernel_groups.json (plot_motivation.py (g)).

vCPU: the run's app cgroup CPU (summary.csv) split by perf cycles, as
classify_app.py splits it; DPUMesh user time from app_buckets.json. Counts:
bpftrace window (bpf.json, c_s seconds), as summarize.py. A kernel sample goes
to the syscall named in its stack (__x64_sys_*), else to irq/softirq, to
syscall entry/exit when only the entry code is on the stack, or to other."""
import collections, csv, gzip, json, os, re, sys

LANG = {'frontend': 'Go', 'productcatalogservice': 'Go', 'checkoutservice': 'Go', 'shippingservice': 'Go',
        'recommendationservice': 'Python', 'emailservice': 'Python', 'currencyservice': 'Node.js',
        'paymentservice': 'Node.js', 'cartservice': '.NET', 'adservice': 'Java', 'redis-cart': 'redis'}
LANGS = ('Go', 'Python', 'Node.js', '.NET', 'Java', 'redis')
GROUPS = {'socket I/O': ('write', 'read', 'sendmsg', 'recvmsg', 'writev', 'readv', 'sendto', 'recvfrom'),
          'park/wake': ('futex', 'nanosleep', 'clock_nanosleep', 'sched_yield'),
          'event wait': ('epoll_pwait', 'epoll_wait', 'ppoll', 'poll', 'epoll_pwait2'),
          'timerfd': ('timerfd_settime',), 'irq': ('(irq)',), 'entry/exit': ('(entry)',)}
IRQ = ('asm_common_interrupt', 'common_interrupt', 'asm_sysvec', 'sysvec_', '__irq_exit', 'irq_exit',
       'handle_softirqs', '__do_softirq')


def kind(pod):
    return pod.rsplit('-', 1)[0] if pod.rsplit('-', 1)[-1].isdigit() else pod


def entry(k):
    sc = next((re.sub(r'^__(x64|ia32)_sys_', '', s) for s in k if re.match(r'^__(x64|ia32)_sys_', s)), None)
    if sc:
        return sc
    if any(s.startswith(IRQ) for s in k):
        return '(irq)'
    if any(s.startswith(('entry_SYSCALL', 'syscall_return')) for s in k[-2:]):
        return '(entry)'
    return '(other)'


def run(d):
    m = json.load(open(f'{d}/meta.json'))
    apps = [c for c in m['containers'].values() if c['role'] != 'sidecar']
    scope = {c['cgroup'].rsplit('/', 1)[-1]: kind(c['pod']) for c in apps}
    cg = {str(c['cgid']): LANG[kind(c['pod'])] for c in apps}
    cfg, rate = m['cfg'], os.path.basename(d.rstrip('/'))[1:]
    row = next(r for r in csv.DictReader(open(os.path.join(d, '..', '..', '..', 'summary.csv')))
               if r['cfg'] == cfg and r['rate'] == rate)
    cores, rps = float(row['app_cores']), float(row['rps'])

    tot, ks = collections.Counter(), collections.defaultdict(collections.Counter)
    by_kind = collections.defaultdict(collections.Counter)
    hdr, frames = None, []

    def flush():
        if not (hdr and hdr[0] and frames):
            return
        L = LANG[hdr[0]]
        tot[L] += hdr[1]
        if frames[0][1].startswith('[kernel'):
            sc = entry([s for s, dso in frames if dso.startswith('[kernel')])
            ks[L][sc] += hdr[1]
            by_kind[hdr[0]][next((n for n, e in GROUPS.items() if sc in e), 'other')] += hdr[1]
    for line in gzip.open(f'{d}/perf.txt.gz', 'rt', errors='replace'):
        if not line.strip():
            flush(); hdr, frames = None, []
        elif not line.startswith(('\t', ' ')):
            mm = re.search(r'\s(\d+)\s+\S*(cri-containerd-[0-9a-f]+\.scope)', line)
            hdr = (scope.get(mm.group(2)), int(mm.group(1))) if mm else None
            frames = []
        else:
            fm = re.match(r'^\s+[0-9a-f]+\s+(.*?)\s+\((.*)\)$', line)
            if fm:
                frames.append((re.sub(r'\+0x[0-9a-f]+$', '', fm.group(1)), fm.group(2)))
    flush()
    f = cores / sum(tot.values())

    sysc, vcs = collections.Counter(), collections.Counter()
    for line in open(f'{d}/bpf.json'):
        line = line.strip()
        if not line.startswith('{'):
            continue
        o = json.loads(line)
        if o.get('type') != 'map':
            continue
        for name, mp in o['data'].items():
            for key, v in mp.items():
                if name == '@sys' and key in cg:
                    sysc[cg[key]] += v
                elif name == '@sw':
                    c, _, invol = key.partition(',')
                    if c in cg and invol == '0':
                        vcs[cg[c]] += v
    win = float(m.get('c_s', 10))
    dm = collections.Counter()
    for pod, b in json.load(open(f'{d}/app_buckets.json')).items():
        dm[LANG[kind(pod)]] += b.get('dpumesh', 0)

    cols = list(GROUPS) + ['other']
    out = [f'{cfg} at {rate} req/s: app vCPU by language; kernel split by the syscall that entered it',
           f'{"language":<9}{"app":>7}{"kernel":>8}' + ''.join(f'{c:>12}' for c in cols) +
           f'{"DPUMesh user":>14}{"syscalls/req":>14}{"vol cs/req":>12}']

    def line(name, langs):
        g = collections.Counter()
        for L in langs:
            for sc, v in ks[L].items():
                g[next((n for n, e in GROUPS.items() if sc in e), 'other')] += v
        return (f'{name:<9}{sum(tot[L] for L in langs) * f:7.2f}{sum(g.values()) * f:8.2f}' +
                ''.join(f'{g[c] * f:12.2f}' for c in cols) + f'{sum(dm[L] for L in langs) * f:14.2f}' +
                f'{sum(sysc[L] for L in langs) / win / rps:14.1f}{sum(vcs[L] for L in langs) / win / rps:12.1f}')
    out += [line(L, [L]) for L in LANGS] + [line('total', LANGS), '', 'top kernel entries (vCPU):']
    for L in LANGS[:-1]:
        out.append(f'  {L:<8} ' + ', '.join(f'{k} {v * f:.2f}' for k, v in ks[L].most_common(8)))
    open(f'{d}/kernel_lang.txt', 'w').write('\n'.join(out) + '\n')
    json.dump({k: dict(v) for k, v in by_kind.items()}, open(f'{d}/kernel_groups.json', 'w'), indent=1)
    print('\n'.join(out))


if __name__ == '__main__':
    for d in sys.argv[1:]:
        run(d)
