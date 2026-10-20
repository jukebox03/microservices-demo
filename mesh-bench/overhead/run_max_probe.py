#!/usr/bin/env python3
"""run_max_probe.py RESULTS_DIR CFG[,CFG...]: run_max.py's maximum-req/s step search
with every step also recording where the CPU goes, to find what limits the maximum.
Per configuration, after the deploy and light load:
  p1500   one 1,500 req/s step (2 s warm, 15 s measured): app-container cycles and
          instructions per container (perf stat --for-each-cgroup) for the IPC
          comparison with the 1,500 req/s wake runs, plus the per-step probes below
  steps   run_max.py's search (start 2,000 DPUMesh / 4,500 no sidecar, +10% per
          10 s step, pass = no drops, no failures, >= 97% achieved), each step with
          host     busy per CPU (/proc/stat) and system-wide cycles/instructions
          DPU      busy per CPU and per proxy thread (/proc/<pid>/task/*/stat)
          jet1     busy (the k6 load generator)
          pods     cores of every app container (cgroup cpu.stat)
DPU settings: PROXY_ENV (default run_dpumesh.PROXY_ENV, W=14), START_ENV (extra
start.sh variables, e.g. SHARD_BASE / MAIN_CPUS / MOCK_CPUS) and IRQ_CPUS (irq.sh
pin target, default 0-1) from the environment; MAX_START / MAX_STEP set one start
rate and the step factor for a finer search, SKIP_P1500=1 skips the 1,500 req/s step.
A configuration name may carry a '+suffix' (same knobs, another result directory).
OB_N_CUR / OB_N_REC / OB_LAYOUT change the replica layout (mk.py).
Results: RESULTS_DIR/<cfg>/{p1500,max,meta}.json."""
import json, os, subprocess, sys, threading, time
import run as R
import run_mi as M
import run_wake as W
import run_dpumesh as D

START = {'dpumesh': 2000, 'nosidecar': 4500}
if os.environ.get('MAX_START'):   # one start for both, e.g. a finer search near the top
    START = {k: int(os.environ['MAX_START']) for k in START}
STEP = float(os.environ.get('MAX_STEP', '1.10'))
SKIP_P1500 = os.environ.get('SKIP_P1500') == '1'
PROXY_ENV = os.environ.get('PROXY_ENV', D.PROXY_ENV)
START_ENV = os.environ.get('START_ENV', '')
IRQ_CPUS = os.environ.get('IRQ_CPUS', '0-1')
PIDFILE = '~/DPUMesh-ob-mux/ob-bench/run/proxy.pid'


def cpu_lines(text):
    """'cpuN ...' lines of /proc/stat -> {N or 'all': (busy, total)} jiffies."""
    out = {}
    for l in text.splitlines():
        if not l.startswith('cpu'):
            continue
        f = l.split()
        v = [int(x) for x in f[1:9]]
        k = 'all' if f[0] == 'cpu' else int(f[0][3:])
        out[k] = (sum(v) - v[3] - v[4], sum(v))
    return out


def host_probe():
    return {'t': time.time(), 'cpu': cpu_lines(open('/proc/stat').read())}


def dpu_probe():
    out = D.dpu(f"cat /proc/uptime; grep '^cpu' /proc/stat; p=$(cat {PIDFILE} 2>/dev/null); "
                f"[ -n \"$p\" ] && for t in /proc/$p/task/*; do echo \"T ${{t##*/}}|$(cat $t/comm 2>/dev/null)|$(cat $t/stat 2>/dev/null)\"; done",
                check=False)
    lines = out.splitlines()
    up = float(lines[0].split()[0]) if lines and lines[0][:1].isdigit() else None
    tasks = {}
    for l in lines:
        if l.startswith('T '):
            tid, comm, st = l[2:].split('|', 2)
            rest = st.rpartition(')')[2].split()
            if len(rest) > 36:
                tasks[tid] = {'comm': comm, 'ticks': int(rest[11]) + int(rest[12]), 'cpu': int(rest[36])}
    return {'up': up, 'cpu': cpu_lines(out), 'tasks': tasks}


def jet1_probe():
    return {'cpu': cpu_lines(R.j1("grep '^cpu' /proc/stat", check=False))}


def probes():
    """Host, DPU and jet1 probes at once (the remote two over ssh in threads)."""
    res = {}
    th = [threading.Thread(target=lambda k=k, f=f: res.__setitem__(k, f())) for k, f in
          (('dpu', dpu_probe), ('jet1', jet1_probe))]
    for t in th:
        t.start()
    res['host'] = host_probe()
    for t in th:
        t.join()
    return res


def busy(a, b):
    """{cpu: busy fraction} between two cpu_lines dicts."""
    out = {}
    for k in b:
        if k in a:
            db, dt = b[k][0] - a[k][0], b[k][1] - a[k][1]
            out[k] = db / dt if dt else 0.0
    return out


def summarize(p0, p1):
    hb, db, jb = busy(p0['host']['cpu'], p1['host']['cpu']), busy(p0['dpu']['cpu'], p1['dpu']['cpu']), \
        busy(p0['jet1']['cpu'], p1['jet1']['cpu'])
    nh = len([k for k in hb if k != 'all'])
    nd = len([k for k in db if k != 'all'])
    nj = len([k for k in jb if k != 'all'])
    s = {'host_busy': hb.get('all', 0) * nh, 'host_cpu': {k: v for k, v in hb.items() if k != 'all'},
         'dpu_busy': db.get('all', 0) * nd, 'dpu_cpu': {k: v for k, v in db.items() if k != 'all'},
         'jet1_busy': jb.get('all', 0) * nj, 'jet1_cpus': nj}
    d0, d1 = p0['dpu'], p1['dpu']
    if d0.get('up') and d1.get('up'):
        dt = d1['up'] - d0['up']
        s['dpu_threads'] = {tid: {'comm': t['comm'], 'cores': (t['ticks'] - d0['tasks'][tid]['ticks']) / 100 / dt,
                                  'last_cpu': t['cpu']}
                            for tid, t in d1['tasks'].items() if tid in d0['tasks']}
    return s


def perf_start(seconds, cgroups=None):
    cmd = [R.SUDO, 'perf', 'stat', '-a', '-x,', '-e', 'cycles,instructions']
    if cgroups:
        cmd += ['--for-each-cgroup', ','.join(cgroups)]
    return subprocess.Popen(cmd + ['--', 'sleep', str(seconds)], stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True)


def perf_read(p):
    """perf stat -x, output -> {cgroup or 'all': {'cycles': n, 'instructions': n}}."""
    _, err = p.communicate(timeout=60)
    out = {}
    for l in err.splitlines():
        f = l.split(',')
        if len(f) < 4 or not f[0].isdigit():
            continue
        if f[2] in ('cycles', 'instructions'):
            cg = f[3] if len(f) >= 8 else 'all'
            out.setdefault(cg, {})[f[2]] = int(f[0])
    return out


def k6_result(res, rate, seconds):
    ach = res['reqs']['count'] / seconds
    drop = (res.get('dropped') or {}).get('count', 0)
    return {'offered': rate, 'achieved': ach, 'drop': drop, 'fail': res['failed']['rate'],
            'p50': res['dur']['p(50)'], 'p99': res['dur']['p(99)'],
            'pass': drop == 0 and res['failed']['rate'] == 0 and ach >= 0.97 * rate}


def point1500(cfg, d, ctrs):
    """One 1,500 req/s step: per-container cycles/instructions and cgroup CPU."""
    rate, warm, meas = 1500, 2, 15
    R.wait_quiet(ctrs)
    tag = f'p1500-{cfg}-{int(time.time())}'
    t0 = R.k6_start(tag, rate, warm, meas, 0)
    until = lambda s: time.sleep(max(0, t0 + s - time.time()))
    until(2.5)
    a, p0 = R.snap(ctrs), probes()
    cgs = {v['cgroup'].replace(f'{R.CG}/', ''): k for k, v in ctrs.items()}
    perf = perf_start(13, list(cgs) + ['/'])
    until(16.5)
    b, p1 = R.snap(ctrs), probes()
    pc = perf_read(perf)
    res = R.k6_wait(tag, timeout=120)
    dt = b['t'] - a['t']
    per = {}
    for cg, cid in cgs.items():
        c = ctrs[cid]
        per[cid] = {'pod': c['pod'], 'container': c['container'], 'role': c['role'],
                    'cores': (b['cg'][cid].get('usage_usec', 0) - a['cg'][cid].get('usage_usec', 0)) / 1e6 / dt,
                    **pc.get(cg, {})}
    out = dict(k6_result(res, rate, meas), containers=per, all_cgroups=pc.get('/', {}), **summarize(p0, p1))
    app = [v for v in per.values() if v['role'] == 'app' and v.get('cycles')]
    cyc, ins = sum(v['cycles'] for v in app), sum(v['instructions'] for v in app)
    R.log(f"  {cfg} p1500: {out['achieved']:.0f} req/s p50 {out['p50']:.1f} ms | app {sum(v['cores'] for v in per.values() if v['role'] == 'app'):.2f} cores "
          f"IPC {ins / cyc if cyc else 0:.3f} ({ins / out['achieved'] / meas / 1e6 if out['achieved'] else 0:.2f} M instr/req) | host {out['host_busy']:.1f} "
          f"dpu {out['dpu_busy']:.1f} jet1 {out['jet1_busy']:.1f}")
    json.dump(out, open(f'{d}/p1500.json', 'w'), indent=1)


def cg_cores(ctrs):
    return {'t': time.time(), 'cg': {k: R.cpustat(c['cgroup']).get('usage_usec', 0) for k, c in ctrs.items()}}


def maxrate(cfg, mesh, d, ctrs):
    rate, steps, best, direction = START[mesh], [], None, 0
    for _ in range(30):
        R.wait_quiet(ctrs)
        tag = f'max-{cfg}-{rate}-{int(time.time())}'
        t0 = R.k6_start(tag, rate, 2, 8, 0)
        # k6 starts when the ssh returns: anchor the window there if the ssh was slow
        k6_ssh = time.time() - t0
        t0 = max(t0, time.time() - 0.4)
        time.sleep(max(0, t0 + 2.2 - time.time()))
        c0, p0 = cg_cores(ctrs), probes()
        perf = perf_start(7.0)
        time.sleep(max(0, t0 + 9.8 - time.time()))
        c1, p1 = cg_cores(ctrs), probes()
        pc = perf_read(perf).get('all', {})
        res = R.k6_wait(tag, timeout=120)
        dt = c1['t'] - c0['t']
        pods = {f"{ctrs[k]['pod']}/{ctrs[k]['container']}": (c1['cg'][k] - c0['cg'].get(k, 0)) / 1e6 / dt for k in c1['cg']}
        step = dict(k6_result(res, rate, 8), ipc=pc, k6_ssh_s=k6_ssh, pods=pods, **summarize(p0, p1))
        steps.append(step)
        ok = step['pass']
        sh = sorted(((t['cores'], t['comm']) for t in step.get('dpu_threads', {}).values()), reverse=True)
        dcpu = [step['dpu_cpu'][k] for k in sorted(step['dpu_cpu'])]
        R.log(f"  {cfg} max-step {rate}: {step['achieved']:.0f} req/s p50 {step['p50']:.1f} p99 {step['p99']:.0f} ms "
              f"drop {step['drop']} | host {step['host_busy']:.1f} IPC {pc.get('instructions', 0) / max(1, pc.get('cycles', 1)):.2f} "
              f"jet1 {step['jet1_busy']:.1f} | dpu {step['dpu_busy']:.1f} per-cpu " + ' '.join(f'{x * 100:.0f}' for x in dcpu) +
              f" | top threads " + ' '.join(f'{c}:{v:.2f}' for v, c in sh[:4]) + f" {'pass' if ok else 'FAIL'}")
        if ok:
            best = step['achieved']
            if direction < 0:
                break
            direction = 1
            rate = round(rate * STEP)
        else:
            if direction > 0:
                break
            direction = -1
            rate = round(rate / STEP)
    mx = best if best else steps[-1]['achieved']
    json.dump({'cfg': cfg, 'max_rps': mx, 'start': START[mesh], 'step': STEP, 'steps': steps},
              open(f'{d}/max.json', 'w'), indent=1)
    R.log(f'  {cfg} max: {mx:.0f} req/s')


def run_cfg(res, cfg):
    knobs = W.CFGS[cfg.split('+')[0]]
    dpumesh = knobs is not None
    tag = f'{cfg}-probe-{int(time.time())}'
    os.environ['EXTRA_ENV'] = ','.join(f'{k}={v}' for k, v in (knobs or {}).items())
    R.log(f'== {cfg}', json.dumps({'knobs': knobs, 'extra_env': os.environ['EXTRA_ENV'],
                                   'proxy_env': PROXY_ENV if dpumesh else None,
                                   'start_env': START_ENV if dpumesh else None, 'irq_cpus': IRQ_CPUS}))
    try:
        W.wait_for_others()
        if dpumesh:
            D.dpu_sudo(f'env CPUS={IRQ_CPUS} bash {D.OB}/irq.sh pin')
            D.dpu(f'cd {D.OB} && {START_ENV} ./start.sh mocks')
            time.sleep(1)
            R.log('dpu proxy:', D.dpu(f'cd {D.OB} && {PROXY_ENV} {START_ENV} ./start.sh proxy {tag}', sudo_pw=True))
        R.deploy('dpumesh' if dpumesh else 'nosidecar', None)
        bad = R.smoke()
        if bad:
            raise RuntimeError(f'smoke failed: {bad[:4]}')
        ctrs = R.containers()
        assert len(ctrs) == R.NPODS, f'{len(ctrs)} containers'
        M.CTRS = ctrs
        R.light_load(30)
        d = f'{res}/{cfg}'
        os.makedirs(d, exist_ok=True)
        json.dump({'cfg': cfg, 'knobs': knobs, 'extra_env': os.environ['EXTRA_ENV'], 'containers': ctrs,
                   'layout': {k: os.environ.get(k) for k in ('OB_N_CUR', 'OB_N_REC', 'OB_LAYOUT')},
                   'host_lib': W.host_lib_rev() if dpumesh else None,
                   'dpu': {'proxy_env': PROXY_ENV, 'start_env': START_ENV, 'irq_cpus': IRQ_CPUS,
                           'rev': W.DPU_REV} if dpumesh else None},
                  open(f'{d}/meta.json', 'w'), indent=1)
        if not SKIP_P1500:
            point1500(cfg, d, ctrs)
        maxrate(cfg, 'dpumesh' if dpumesh else 'nosidecar', d, ctrs)
    except Exception as e:
        R.log(f'!! {cfg}: {e}')
    finally:
        R.kubectl('delete', 'ns', R.NS, '--ignore-not-found', '--wait=true', '--timeout=180s', check=False)
        if dpumesh:
            R.log('dpu stop:', D.dpu(f'cd {D.OB} && ./start.sh stop', sudo_pw=True, check=False))
            R.log('dpu irq restore:', D.dpu_sudo(f'bash {D.OB}/irq.sh restore', check=False))
            log = f'{res}/{cfg}/proxy-{tag}.log'
            os.makedirs(f'{res}/{cfg}', exist_ok=True)
            subprocess.run(['scp', '-q', f'{D.DPU}:DPUMesh-ob-mux/ob-bench/run/proxy-{tag}.log', log], check=False)
            if os.path.exists(log):
                fc = subprocess.run([sys.executable, D.FLOW_CHECK, log], capture_output=True, text=True)
                open(f'{res}/{cfg}/flow_check.txt', 'w').write(fc.stdout + fc.stderr)
                R.log(f'flow_check exit {fc.returncode}:', (fc.stdout + fc.stderr).strip()[-300:])


def main():
    res = sys.argv[1]
    cfgs = sys.argv[2].split(',')
    os.makedirs(res, exist_ok=True)
    R.LOG = f'{res}/run.log'
    R.log('start max probe run', json.dumps({'cfgs': cfgs, 'start': START, 'step': STEP, 'proxy_env': PROXY_ENV,
                                              'start_env': START_ENV, 'irq_cpus': IRQ_CPUS}))
    W.wait_for_others()
    R.log('cpu fix:', R.sh([R.SUDO, 'bash', f'{R.HERE}/cpu.sh', 'fix']).strip())
    try:
        for cfg in cfgs:
            run_cfg(res, cfg)
    finally:
        R.log('cpu restore:', R.sh([R.SUDO, 'bash', f'{R.HERE}/cpu.sh', 'restore'], check=False).strip())
        R.log('done')


if __name__ == '__main__':
    main()
