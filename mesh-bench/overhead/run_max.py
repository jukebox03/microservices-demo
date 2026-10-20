#!/usr/bin/env python3
"""run_max.py RESULTS_DIR CFG[,CFG...]: maximum HTTP req/s of Online Boutique on the
jet2 setup (24 pods, 2.3 GHz fixed), by run_mi.py's step search: k6 open loop,
10 s steps (2 s warm, 8 s measured) from a start rate up by 10% until a step
sheds, fails, or achieves under 97% of the offered rate; the maximum is the
achieved rate of the last passing step. Each step also records host and DPU CPU
busy (/proc/stat over the step) to show which side saturates.
Configurations are run_wake.py's (DPUMesh ones restart the DPU proxy, L7 by
default: env.sh OB_L7=1). Results: RESULTS_DIR/<cfg>/max.json."""
import json, os, subprocess, sys, time
import run as R
import run_mi as M
import run_wake as W
import run_dpumesh as D

START = {'dpumesh': 2000, 'nosidecar': 4500}
STEP = 1.10


def proc_stat(host_cmd=None):
    """Aggregate CPU jiffies (busy, total) from /proc/stat, locally or on the DPU."""
    out = D.dpu('head -1 /proc/stat') if host_cmd == 'dpu' else open('/proc/stat').readline()
    v = [int(x) for x in out.split()[1:]]
    idle = v[3] + v[4]
    return sum(v) - idle, sum(v)


def busy_cores(a, b, ncpu):
    db, dt = b[0] - a[0], b[1] - a[1]
    return db / dt * ncpu if dt else 0.0


def maxrate(cfg, mesh, d, ctrs):
    os.makedirs(d, exist_ok=True)
    host_n = os.cpu_count()
    dpu_n = int(D.dpu('nproc'))
    rate, steps, best, direction = START[mesh], [], None, 0
    for _ in range(30):
        R.wait_quiet(ctrs)
        tag = f'max-{cfg}-{rate}-{int(time.time())}'
        t0 = R.k6_start(tag, rate, 2, 8, 0)
        time.sleep(max(0, t0 + 2.2 - time.time()))
        h0, d0 = proc_stat(), proc_stat('dpu')
        time.sleep(max(0, t0 + 9.8 - time.time()))
        h1, d1 = proc_stat(), proc_stat('dpu')
        res = R.k6_wait(tag, timeout=120)
        ach = res['reqs']['count'] / 8
        drop = (res.get('dropped') or {}).get('count', 0)
        ok = drop == 0 and res['failed']['rate'] == 0 and ach >= 0.97 * rate
        step = {'offered': rate, 'achieved': ach, 'drop': drop, 'fail': res['failed']['rate'],
                'p50': res['dur']['p(50)'], 'p99': res['dur']['p(99)'], 'pass': ok,
                'host_busy_cores': busy_cores(h0, h1, host_n), 'dpu_busy_cores': busy_cores(d0, d1, dpu_n),
                'host_cpus': host_n, 'dpu_cpus': dpu_n}
        steps.append(step)
        R.log(f"  {cfg} max-step {rate}: {ach:.0f} req/s p50 {step['p50']:.1f} p99 {step['p99']:.0f} ms drop {drop} "
              f"fail {step['fail']:.4f} | host {step['host_busy_cores']:.1f}/{host_n} dpu "
              f"{step['dpu_busy_cores']:.1f}/{dpu_n} cores {'pass' if ok else 'FAIL'}")
        if ok:
            best = ach
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
    R.log(f"  {cfg} max: {mx:.0f} req/s")
    return mx


def run_cfg(res, cfg):
    knobs = W.CFGS[cfg]
    dpumesh = knobs is not None
    tag = f'{cfg}-max-{int(time.time())}'
    os.environ['EXTRA_ENV'] = ','.join(f'{k}={v}' for k, v in (knobs or {}).items())
    R.log(f'== {cfg}', json.dumps({'knobs': knobs, 'extra_env': os.environ['EXTRA_ENV']}))
    try:
        W.wait_for_others()
        if dpumesh:
            D.dpu_sudo(f'bash {D.OB}/irq.sh pin')
            D.dpu(f'cd {D.OB} && ./start.sh mocks')
            time.sleep(1)
            R.log('dpu proxy:', D.dpu(f'cd {D.OB} && {D.PROXY_ENV} ./start.sh proxy {tag}', sudo_pw=True))
        R.deploy('dpumesh' if dpumesh else 'nosidecar', None)
        bad = R.smoke()
        if bad:
            raise RuntimeError(f'smoke failed: {bad[:4]}')
        ctrs = R.containers()
        assert len(ctrs) == 24, f'{len(ctrs)} containers'
        M.CTRS = ctrs
        R.light_load(30)
        d = f'{res}/{cfg}'
        os.makedirs(d, exist_ok=True)
        json.dump({'cfg': cfg, 'knobs': knobs, 'extra_env': os.environ['EXTRA_ENV'],
                   'host_lib': W.host_lib_rev() if dpumesh else None,
                   'dpu': {'proxy_env': D.PROXY_ENV, 'rev': W.DPU_REV} if dpumesh else None},
                  open(f'{d}/meta.json', 'w'), indent=1)
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
    R.log('start max run', json.dumps({'cfgs': cfgs, 'start': START, 'step': STEP}))
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
