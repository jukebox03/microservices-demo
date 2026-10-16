#!/usr/bin/env python3
"""summarize.py RESULTS_DIR > table.csv

One row per configuration and offered load (median over reps, and per-rep rows
with --reps): throughput and latency from k6; host CPU from the cgroup
snapshots of the measured window, split into app and sidecar, user and system;
per HTTP request: CPU ms, syscalls and context switches (bpftrace window),
pod-network packets (veth) and loopback packets; and, where classify.py has
run, the sidecar and app CPU split into the six buckets."""
import csv, glob, json, os, statistics, sys

BUCKETS = ['kernel', 'mtls', 'l7_parsing', 'l7_policy', 'telemetry', 'other']


def delta(a, b, k, f):
    return b['cg'][k].get(f, 0) - a['cg'][k].get(f, 0)


def cg_delta(a, b, name, f='usage_usec'):
    return (b[name].get(f, 0) - a[name].get(f, 0))


def one(d):
    s = json.load(open(f'{d}/summary.json'))
    m = json.load(open(f'{d}/meta.json'))
    sn = json.load(open(f'{d}/snap.json'))
    a, b = sn['a'], sn['b']
    dt = b['t'] - a['t']
    rps = s['rps'] or float('nan')
    r = {'cfg': s['cfg'], 'rate': s['rate'], 'rep': m['rep'], 'rps': s['rps'], 'p50_ms': s['p50_ms'],
         'p99_ms': s['p99_ms'], 'fail_rate': s['fail_rate'], 'dropped': s['dropped']}
    tot = {}
    for k, c in m['containers'].items():
        if k not in b['cg'] or k not in a['cg']:
            continue
        role = 'sidecar' if c['role'] == 'sidecar' else 'app'
        for f in ('usage_usec', 'user_usec', 'system_usec'):
            tot[(role, f)] = tot.get((role, f), 0) + delta(a, b, k, f)
    for role in ('app', 'sidecar'):
        r[f'{role}_cores'] = tot.get((role, 'usage_usec'), 0) / 1e6 / dt
        r[f'{role}_user_cores'] = tot.get((role, 'user_usec'), 0) / 1e6 / dt
        r[f'{role}_sys_cores'] = tot.get((role, 'system_usec'), 0) / 1e6 / dt
        r[f'{role}_ms_per_req'] = r[f'{role}_cores'] * 1000 / rps
    pods = sum(tot.get((x, 'usage_usec'), 0) for x in ('app', 'sidecar')) / 1e6 / dt
    r['other_pods_cores'] = cg_delta(a, b, 'kubepods') / 1e6 / dt - pods
    r['containerd_cores'] = cg_delta(a, b, 'containerd') / 1e6 / dt
    r['kubelet_cores'] = cg_delta(a, b, 'kubelet') / 1e6 / dt
    r['host_busy'] = s['host_busy']
    r['ms_per_req'] = (r['app_cores'] + r['sidecar_cores']) * 1000 / rps
    r['veth_pkts_per_req'] = (b['veth_pkts'] - a['veth_pkts']) / dt / rps / 2
    # packets inside the pods' network namespaces (rep2 on): lo is app<->sidecar
    # traffic, eth0 the pod-to-pod traffic; rx+tx counts each packet twice
    if 'pod_net' in a and 'pod_net' in b:
        r['pod_lo_pkts_per_req'] = (b['pod_net']['lo_pkts'] - a['pod_net']['lo_pkts']) / dt / rps / 2
        r['pod_eth_pkts_per_req'] = (b['pod_net']['eth_pkts'] - a['pod_net']['eth_pkts']) / dt / rps / 2
    # /proc context switches over the CPU window (threads present at both ends, plus new ones)
    if 'ctxsw' in a and 'ctxsw' in b:
        acc = {}
        for k, c in m['containers'].items():
            role = 'sidecar' if c['role'] == 'sidecar' else 'app'
            ta, tb = a['ctxsw'].get(k, {}), b['ctxsw'].get(k, {})
            for t, (v, n) in tb.items():
                v0, n0 = ta.get(t, [0, 0])
                acc[(role, 'v')] = acc.get((role, 'v'), 0) + v - v0
                acc[(role, 'n')] = acc.get((role, 'n'), 0) + n - n0
        for role in ('app', 'sidecar'):
            r[f'{role}_vol_cs_per_req'] = acc.get((role, 'v'), 0) / dt / rps
            r[f'{role}_invol_cs_per_req'] = acc.get((role, 'n'), 0) / dt / rps
    # bpftrace window: syscalls and context switches per HTTP request, by role
    cgid = {str(c['cgid']): ('sidecar' if c['role'] == 'sidecar' else 'app') for c in m['containers'].values()}
    sysc, sw, invol = {}, {}, {}
    try:
        for line in open(f'{d}/bpf.json'):
            line = line.strip()
            if not line.startswith('{'):
                continue
            o = json.loads(line)
            if o.get('type') != 'map':
                continue
            for name, vals in o['data'].items():
                for key, n in vals.items():
                    if name == '@sys':
                        role = cgid.get(key)
                        if role:
                            sysc[role] = sysc.get(role, 0) + n
                    elif name == '@sw':
                        cg, _, inv = key.partition(',')
                        role = cgid.get(cg)
                        if role:
                            sw[role] = sw.get(role, 0) + n
                            if inv == '1':
                                invol[role] = invol.get(role, 0) + n
        win = float(m.get('c_s', 10))   # bpftrace window length (s)
        for role in ('app', 'sidecar'):
            r[f'{role}_syscalls_per_req'] = sysc.get(role, 0) / win / rps
            r[f'{role}_cswitch_per_req'] = sw.get(role, 0) / win / rps
            r[f'{role}_invol_cswitch_per_req'] = invol.get(role, 0) / win / rps
    except FileNotFoundError:
        pass
    bk = f'{d}/buckets.json'
    if os.path.exists(bk):
        bu = json.load(open(bk))
        # cycles -> cores with the pods' own ratio (their cgroup CPU over their cycles)
        pod_cyc = sum(bu['app'].values()) + sum(bu['sidecar'].values())
        if pod_cyc:
            r['host_net_cores'] = bu.get('host_net_cycles', 0) * (r['app_cores'] + r['sidecar_cores']) / pod_cyc
            r['host_net_ms_per_req'] = r['host_net_cores'] * 1000 / rps
            r['app_gcycles_per_req'] = sum(bu['app'].values()) / 10.0 / rps / 1e9
            r['sidecar_gcycles_per_req'] = sum(bu['sidecar'].values()) / 10.0 / rps / 1e9
        for role, names in (('app', ('kernel', 'app_grpc', 'app_user')), ('sidecar', BUCKETS)):
            share = bu.get(role, {})
            tot_c = sum(share.values()) or 1
            for x in names:
                r[f'{role}_{x}_ms_per_req'] = r[f'{role}_ms_per_req'] * share.get(x, 0) / tot_c
            ks = bu.get(f'{role}_ksub', {})
            for x, v in ks.items():   # kernel sub-buckets, ms per request
                r[f'{role}_k_{x}_ms_per_req'] = r[f'{role}_ms_per_req'] * share.get('kernel', 0) / tot_c * v / (sum(ks.values()) or 1)
    return r


def main():
    res = sys.argv[1]
    per_rep = '--reps' in sys.argv
    rep = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--rep=')), '*')   # --rep=1: one rep only
    rows = [one(os.path.dirname(p)) for p in sorted(glob.glob(f'{res}/*/rep{rep}/r*/summary.json'))]
    if not per_rep:
        groups = {}
        for r in rows:
            groups.setdefault((r['cfg'], r['rate']), []).append(r)
        out = []
        for (cfg, rate), rs in sorted(groups.items()):
            m = {'cfg': cfg, 'rate': rate, 'reps': len(rs)}
            for k in rs[0]:
                if k in ('cfg', 'rate', 'rep'):
                    continue
                vals = [x[k] for x in rs if isinstance(x.get(k), (int, float)) and x.get(k) == x.get(k)]
                m[k] = statistics.median(vals) if vals else None
            out.append(m)
        rows = out
    keys = list(dict.fromkeys(k for r in rows for k in r))
    w = csv.DictWriter(sys.stdout, fieldnames=keys)
    w.writeheader()
    for r in rows:
        w.writerow({k: (f'{v:.4g}' if isinstance(v, float) else v) for k, v in r.items()})


if __name__ == '__main__':
    main()
