#!/usr/bin/env python3
"""run_diag.py RESULTS_DIR CFG[,CFG...]: what stops the host short of 100% busy at the
maximum. Deploy, DPU settings and layout as run_max_probe.py; instead of the step
search, one step per rate in DIAG_RATES ('dpumesh:5188,7846;nosidecar:6971', req/s),
3 s warm + 16 s at that rate, recording
  3.2-11.2 s  host   PSI cpu 'some' (/proc/pressure/cpu) and per-CPU run time and
                     runqueue wait (/proc/schedstat)
              pods   cgroup CPU and cpu.pressure some/full per container
              threads CPU and runqueue wait of every app thread
                     (/proc/<pid>/task/<tid>/stat, schedstat)
              DPU / jet1  run_max_probe's probes (per CPU, per proxy thread)
  11.5-16.5 s DPU    perf record -F 499 of the proxy (DPUMesh only); reported after
                     the last step (perf report --sort comm / dso / dso,sym)
Results: RESULTS_DIR/<cfg>/diag-<rate>.json, perf-<rate>.txt."""
import json, os, subprocess, sys, threading, time
import run as R
import run_max_probe as P
import run_dpumesh as D

RUN = '~/DPUMesh-ob-mux/ob-bench/run'


def rates(mesh):
    for part in os.environ['DIAG_RATES'].split(';'):
        m, _, r = part.partition(':')
        if m == mesh:
            return [int(x) for x in r.split(',')]
    return []


def schedstat():
    out = {}
    for l in open('/proc/schedstat'):
        f = l.split()
        if f[0].startswith('cpu') and f[0] != 'cpu':
            out[int(f[0][3:])] = (int(f[7]), int(f[8]))   # rq_cpu_time, rq_run_delay (ns)
    return out


def psi(path):
    out = {}
    try:
        for l in open(path):
            k, *kv = l.split()
            out[k] = int(dict(x.split('=') for x in kv)['total'])
    except OSError:
        pass
    return out


def threads(ctrs):
    out = {}
    for cid, c in ctrs.items():
        try:
            pids = open(f"{c['cgroup']}/cgroup.procs").read().split()
        except OSError:
            continue
        for pid in pids:
            try:
                tids = os.listdir(f'/proc/{pid}/task')
            except OSError:
                continue
            for tid in tids:
                try:
                    st = open(f'/proc/{pid}/task/{tid}/stat').read()
                    run_ns, wait_ns, _ = (int(x) for x in open(f'/proc/{pid}/task/{tid}/schedstat').read().split())
                except (OSError, ValueError):
                    continue
                comm = st[st.index('(') + 1:st.rindex(')')]
                out[tid] = (cid, comm, run_ns, wait_ns)
    return out


def snap(ctrs):
    return {'t': time.time(), 'psi': psi('/proc/pressure/cpu'), 'sched': schedstat(), 'thr': threads(ctrs),
            'cg': {k: (R.cpustat(c['cgroup']).get('usage_usec', 0), psi(f"{c['cgroup']}/cpu.pressure"))
                   for k, c in ctrs.items()}}


def diff(a, b, ctrs):
    dt = b['t'] - a['t']
    sched = {c: {'run': (b['sched'][c][0] - a['sched'][c][0]) / 1e9 / dt,
                 'wait': (b['sched'][c][1] - a['sched'][c][1]) / 1e9 / dt} for c in b['sched'] if c in a['sched']}
    pods = {}
    for k, (u, p) in b['cg'].items():
        u0, p0 = a['cg'].get(k, (0, {}))
        pods[f"{ctrs[k]['pod']}/{ctrs[k]['container']}"] = {
            'cores': (u - u0) / 1e6 / dt,
            'some': (p.get('some', 0) - p0.get('some', 0)) / 1e6 / dt,
            'full': (p.get('full', 0) - p0.get('full', 0)) / 1e6 / dt}
    thr = []
    for tid, (cid, comm, r, w) in b['thr'].items():
        if tid in a['thr']:
            thr.append({'tid': tid, 'pod': ctrs[cid]['pod'], 'comm': comm,
                        'cores': (r - a['thr'][tid][2]) / 1e9 / dt, 'wait': (w - a['thr'][tid][3]) / 1e9 / dt})
    thr.sort(key=lambda t: -t['cores'])
    return {'dt': dt, 'psi_some': (b['psi'].get('some', 0) - a['psi'].get('some', 0)) / 1e6 / dt,
            'sched': sched, 'run_cores': sum(s['run'] for s in sched.values()),
            'wait_tasks': sum(s['wait'] for s in sched.values()), 'pods': pods, 'threads': thr}


def diag_steps(cfg, mesh, d, ctrs):
    perfs = []
    for rate in rates(mesh):
        R.wait_quiet(ctrs)
        tag = f'diag-{cfg}-{rate}-{int(time.time())}'
        t0 = R.k6_start(tag, rate, 3, 16, 0)
        t0 = max(t0, time.time() - 0.4)
        time.sleep(max(0, t0 + 3.2 - time.time()))
        a, p0 = snap(ctrs), P.probes()
        time.sleep(max(0, t0 + 11.2 - time.time()))
        b, p1 = snap(ctrs), P.probes()
        th = None
        if mesh == 'dpumesh':
            f = f'{RUN}/perf-{cfg}-{rate}.data'
            th = threading.Thread(target=D.dpu_sudo, args=(
                f'perf record -q -F 499 -o {f} -p $(cat {P.PIDFILE}) -- sleep 5',), kwargs={'check': False})
            time.sleep(max(0, t0 + 11.5 - time.time()))
            th.start()
            perfs.append((rate, f))
        res = R.k6_wait(tag, timeout=120)
        if th:
            th.join()
        out = dict(P.k6_result(res, rate, 16), **diff(a, b, ctrs), **P.summarize(p0, p1))
        json.dump(out, open(f'{d}/diag-{rate}.json', 'w'), indent=1)
        top = ', '.join(f"{t['pod'].split('-')[0]}/{t['comm']}:{t['cores']:.2f}+w{t['wait']:.2f}" for t in out['threads'][:6])
        R.log(f"  {cfg} diag {rate}: {out['achieved']:.0f} req/s p50 {out['p50']:.1f} p99 {out['p99']:.0f} drop {out['drop']} "
              f"| host {out['host_busy']:.1f} run {out['run_cores']:.1f} rq-wait {out['wait_tasks']:.2f} psi {out['psi_some']:.2f} "
              f"| dpu {out['dpu_busy']:.1f} | {top}")
    # perf reports after the load, so the report does not disturb a step
    for rate, f in perfs:
        rep = f'perf report -i {f} --stdio --no-children -q -g none'
        # dpu_sudo puts sudo in front of the first command only
        txt = '## by comm\n' + D.dpu_sudo(f'{rep} --sort comm 2>/dev/null; echo "## by dso"; sudo {rep} --sort dso 2>/dev/null; '
                                          f'echo "## by dso,sym"; sudo {rep} --sort dso,sym --percent-limit 0.02 2>/dev/null; rm -f {f}',
                                          check=False)
        open(f'{d}/perf-{rate}.txt', 'w').write(txt)
        R.log(f'  perf {rate}: {len(txt.splitlines())} lines')


if __name__ == '__main__':
    P.SKIP_P1500 = True
    P.maxrate = diag_steps
    P.main()
