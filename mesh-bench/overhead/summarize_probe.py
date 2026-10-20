#!/usr/bin/env python3
"""summarize_probe.py RESULTS_DIR: tables from run_max_probe.py.
  1. The 1,500 req/s step: app-container cores, cycles and instructions (per
     request and IPC), by language group and in total.
  2. Each max-search step: achieved req/s, latency, host busy and IPC, jet1 busy,
     DPU busy split into the shard CPUs and the rest, the busiest and idlest shard.
A step whose probe window was not fully under load (k6 started late: jet1 busy
under half of the neighbouring steps') is marked '~'."""
import collections, json, os, sys

LANG = {'frontend': 'Go', 'productcatalogservice': 'Go', 'checkoutservice': 'Go', 'shippingservice': 'Go',
        'currencyservice': 'Node.js', 'paymentservice': 'Node.js', 'adservice': 'Java', 'cartservice': '.NET',
        'recommendationservice': 'Python', 'emailservice': 'Python', 'redis': 'redis'}


def p1500(res, cfgs):
    print('## 1,500 req/s: app containers (cycles and instructions from perf stat per container cgroup)\n')
    rows = collections.OrderedDict()
    for cfg in cfgs:
        f = f'{res}/{cfg}/p1500.json'
        if not os.path.exists(f):
            continue
        p = json.load(open(f))
        n = p['achieved'] * 15
        g = collections.defaultdict(lambda: [0.0, 0, 0])
        for c in p['containers'].values():
            if c['role'] == 'sidecar':
                continue
            lang = LANG.get(c['pod'].split('-')[0], '?')
            for k in (lang, 'all'):
                g[k][0] += c['cores']; g[k][1] += c.get('cycles', 0); g[k][2] += c.get('instructions', 0)
        rows[cfg] = (p, n, g)
    langs = ['all', 'Go', 'Node.js', 'Java', '.NET', 'Python', 'redis']
    print('| group | ' + ' | '.join(f'{c} cores / IPC / Minstr/req / Mcyc/req' for c in rows) + ' |')
    print('|---|' + '---|' * len(rows))
    for l in langs:
        cells = []
        for cfg, (p, n, g) in rows.items():
            c, cy, ins = g[l]
            cells.append(f'{c:.2f} / {ins / cy if cy else 0:.3f} / {ins / n / 1e6:.2f} / {cy / n / 1e6:.2f}')
        print(f'| {l} | ' + ' | '.join(cells) + ' |')
    print()
    for cfg, (p, n, g) in rows.items():
        print(f"{cfg}: {p['achieved']:.0f} req/s p50 {p['p50']:.1f} ms, host {p['host_busy']:.1f}, DPU {p['dpu_busy']:.1f}, jet1 {p['jet1_busy']:.1f}")
    print()


def steps(res, cfgs):
    for cfg in cfgs:
        f = f'{res}/{cfg}/max.json'
        if not os.path.exists(f):
            continue
        m = json.load(open(f))
        meta = json.load(open(f'{res}/{cfg}/meta.json'))
        pe = (meta.get('dpu') or {}).get('proxy_env', '') or ''
        start_env = (meta.get('dpu') or {}).get('start_env', '') or ''
        w = int(next((x[2:] for x in pe.split() if x.startswith('W=')), 14))
        base = int(next((x[11:] for x in start_env.split() if x.startswith('SHARD_BASE=')), 2))
        shard = [str(c) for c in range(base, base + w)]
        print(f"## {cfg}: max {m['max_rps']:.0f} req/s ({pe or 'no DPU proxy'} {start_env})\n")
        print('| offered | achieved | p50 / p99 ms | host busy /32 | host IPC | jet1 busy | DPU busy /16 | shard CPUs mean (min-max) % | other DPU CPUs % | pass |')
        print('|---|---|---|---|---|---|---|---|---|---|')
        jb = [s['jet1_busy'] for s in m['steps']]
        for i, s in enumerate(m['steps']):
            nb = [x for j, x in enumerate(jb) if abs(j - i) == 1]
            mark = '~' if nb and s['jet1_busy'] < 0.5 * min(nb) else ''
            ipc = s['ipc'].get('instructions', 0) / max(1, s['ipc'].get('cycles', 1))
            dc = s['dpu_cpu']
            sh = [dc[c] * 100 for c in shard if c in dc]
            other = [f'{c}:{dc[c] * 100:.0f}' for c in sorted(dc, key=int) if c not in shard]
            shs = f'{sum(sh) / len(sh):.0f} ({min(sh):.0f}-{max(sh):.0f})' if sh else '-'
            print(f"| {s['offered']} | {s['achieved']:.0f}{mark} | {s['p50']:.0f} / {s['p99']:.0f} | {s['host_busy']:.1f} | {ipc:.2f} | "
                  f"{s['jet1_busy']:.1f} | {s['dpu_busy']:.1f} | {shs} | {' '.join(other) if sh else '-'} | {'pass' if s['pass'] else 'FAIL'} |")
        last = [s for s in m['steps'] if s['pass']][-1] if any(s['pass'] for s in m['steps']) else None
        for s in m['steps']:
            if s.get('pods') and (s is last or (not s['pass'] and last and s['offered'] > last['offered'])):
                top = sorted(s['pods'].items(), key=lambda x: -x[1])
                print(f"\npods at {s['offered']} ({'pass' if s['pass'] else 'FAIL'}, cores): " +
                      ', '.join(f"{k.split('/')[0]} {v:.2f}" for k, v in top[:14]))
        if last and last.get('dpu_threads'):
            th = collections.Counter()
            for t in last['dpu_threads'].values():
                th[t['comm'] if t['comm'].startswith('dmesh-shard') else t['comm'].split('-')[0] if '-' in t['comm'] else t['comm']] += t['cores']
            print(f"\nproxy threads at {last['offered']} (cores): " + ', '.join(f'{k} {v:.2f}' for k, v in th.most_common() if v >= 0.01))
        print()


if __name__ == '__main__':
    res = sys.argv[1]
    cfgs = sorted(d for d in os.listdir(res) if os.path.isdir(f'{res}/{d}'))
    order = ['W0-nosidecar', 'L1-legacy', 'G1-default']
    cfgs = [c for c in order if c in cfgs] + [c for c in cfgs if c not in order]
    p1500(res, cfgs)
    steps(res, cfgs)
