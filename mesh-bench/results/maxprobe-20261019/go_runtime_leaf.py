#!/usr/bin/env python3
"""go_runtime_leaf.py POINT_DIR...: the Go services' "Runtime" bucket (classify_app.py)
split by the runtime function that claimed the sample, in vCPU (cycles share of the
service x the service's cgroup CPU over the CPU window)."""
import collections, gzip, json, re, sys
sys.path.insert(0, '/home/jukebox/microservices-demo/mesh-bench/overhead')
import classify_app as C

GROUPS = [
    ('idle: findRunnable/steal/netpoll/park', r'^runtime\.(findRunnable|stealWork|runqgrab|netpoll|park_m|schedule|mcall|checkTimers|runtimer|stopm|mPark|notesleep|futex|usleep|osyield|semasleep|lock2|unlock2|gopark|goexit)'),
    ('wake: wakep/startm/ready', r'^runtime\.(wakep|startm|notewakeup|semawakeup|ready|goready|handoffp)'),
    ('syscall enter/exit', r'^runtime\.(entersyscall|reentersyscall|exitsyscall)'),
    ('GC', r'^runtime\.(gc|scan|mark|sweep|bgsweep|bgscavenge|scavenge|lfstack|tryDeferToSpanScan|greyobject|findObject|heapBits|spanOf|wbBuf)'),
    ('stack/preempt/other', r'.'),
]


def kind_of(c):
    return c['pod'].rsplit('-', 1)[0] if c['pod'].rsplit('-', 1)[-1].isdigit() else c['pod']


def main(d):
    m = json.load(open(f'{d}/meta.json'))
    snap = json.load(open(f'{d}/snap.json'))
    a, b = snap['a'], snap['b']
    dt = b['t'] - a['t']
    scope, cores = {}, collections.Counter()
    for cid, c in m['containers'].items():
        if c['role'] == 'sidecar':
            continue
        k = kind_of(c)
        scope[c['cgroup'].rsplit('/', 1)[-1]] = k
        cores[k] += (b['cg'][cid].get('usage_usec', 0) - a['cg'][cid].get('usage_usec', 0)) / 1e6 / dt
    tot = collections.Counter()
    rt = collections.defaultdict(collections.Counter)
    leaf = collections.defaultdict(collections.Counter)
    hdr, frames = None, []

    def flush():
        if not (hdr and hdr[0] and frames):
            return
        k, p = hdr
        tot[k] += p
        if k not in C.GO_BIN or C.bucket(frames) != 'runtime':
            return
        sym = next((C.strip(s) for s, dd in frames if C.frame_kind(C.strip(s), dd) == 'runtime'),
                   C.strip(frames[0][0]))
        g = next(n for n, pat in GROUPS if re.match(pat, sym))
        rt[k][g] += p
        leaf[k][sym] += p
    for line in gzip.open(f'{d}/perf.txt.gz', 'rt', errors='replace'):
        if not line.strip():
            flush(); hdr, frames = None, []
            continue
        if not line.startswith(('\t', ' ')):
            mm = re.search(r'\s(\d+)\s+\S*(cri-containerd-[0-9a-f]+\.scope)', line)
            hdr = (scope.get(mm.group(2)), int(mm.group(1))) if mm else None
            frames = []
        else:
            fm = re.match(r'^\s+[0-9a-f]+\s+(.*?)\s+\((.*)\)$', line)
            if fm:
                frames.append((fm.group(1), fm.group(2)))
    flush()
    out = {'groups': collections.Counter(), 'leaf': collections.Counter(), 'go_cores': 0.0}
    for k in C.GO_BIN:
        if not tot[k]:
            continue
        f = cores[k] / tot[k]
        out['go_cores'] += cores[k]
        for g, p in rt[k].items():
            out['groups'][g] += p * f
        for s, p in leaf[k].items():
            out['leaf'][s] += p * f
    return out


if __name__ == '__main__':
    res = {}
    for d in sys.argv[1:]:
        res[d] = main(d)
    names = [g for g, _ in GROUPS]
    print(f"{'':40}" + ''.join(f'{d.split("/")[-3][:14]:>16}' for d in res))
    print(f"{'Go services cgroup CPU':40}" + ''.join(f"{r['go_cores']:16.2f}" for r in res.values()))
    for g in names:
        print(f'{g:40}' + ''.join(f"{r['groups'][g]:16.3f}" for r in res.values()))
    print(f"{'runtime total':40}" + ''.join(f"{sum(r['groups'].values()):16.3f}" for r in res.values()))
    syms = collections.Counter()
    for r in res.values():
        syms.update(r['leaf'])
    print('--- top claiming runtime functions (vCPU)')
    for s, _ in syms.most_common(18):
        print(f'{s[:40]:40}' + ''.join(f"{r['leaf'][s]:16.3f}" for r in res.values()))
