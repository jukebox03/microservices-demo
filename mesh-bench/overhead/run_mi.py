#!/usr/bin/env python3
"""run_mi.py RESULTS_DIR: the overhead ladder measured the MeshInsight way.

Per configuration, once each, as short as possible:
  latency1  one request outstanding (1 k6 VU, closed loop), 2 s warm + 13 s
  max       the configuration's maximum throughput on this setup, by a step
            search (maxrate): +10% per 10 s step until a step sheds or fails
  r<rate>   25/50/75/100% of that maximum. k6 open loop, 20 s: 2 s warm, cgroup CPU and /proc
            context switches over 2.5-10 s, perf 10-14.5 s, bpftrace 15-19 s.
Everything else (deployments, in-place steps, collection) is run.py's."""
import json, os, sys, time
import run as R

START = {'nosidecar': 4500, 'l5d': 2000, 'istio': 2000}
STEP = 1.10
# maximum load per configuration, given by the user (2026-10-15 14:05):
# no-sidecar 6,000, Linkerd 3,000, Istio 3,000 HTTP req/s
MAXRPS = {'N0-nosidecar': 6000, 'N0t-nosidecar-trace': 6000,
          'L1-opaque': 3000, 'L2-l7': 3000, 'L3-authz': 3000, 'L4-traffic': 3000, 'L5-telemetry': 3000,
          'I1-l4': 3000, 'I2n-l7-notls': 3000, 'I2-l7': 3000, 'I3-authz': 3000, 'I4-traffic': 3000, 'I5-telemetry': 3000}
FRACS = (0.25, 0.50, 0.75, 1.00)
# 20 s per point (user, 2026-10-15): 2 s warm, cgroup CPU and /proc context switches
# over 2.5-10 s, perf 10-14.5 s, bpftrace (syscalls, switches) 15-19 s
R.WARM_S, R.MEASURE_S, R.PROF_S = 2, 13, 5
R.A0, R.A1, R.B0, R.B_S, R.C0, R.C_S = 2.5, 10, 10, 4.5, 15, 4


def maxrate(cfg, mesh, d):
    """Maximum throughput by a step search: 10 s k6 runs (2 s warm, 8 s measured)
    from START up by STEP; a step passes when it sheds nothing, fails nothing and
    achieves >= 97% of the offered rate. The maximum is the achieved rate of the
    last passing step (if the first step fails, the search walks down)."""
    os.makedirs(d, exist_ok=True)
    rate, steps, best = START[mesh or 'nosidecar'], [], None
    direction = 0
    for _ in range(25):
        R.wait_quiet(CTRS)
        tag = f'max-{cfg}-{rate}-{int(time.time())}'
        R.k6_start(tag, rate, 2, 8, 0)
        res = R.k6_wait(tag, timeout=120)
        ach = res['reqs']['count'] / 8
        drop = (res.get('dropped') or {}).get('count', 0)
        ok = drop == 0 and res['failed']['rate'] == 0 and ach >= 0.97 * rate
        steps.append({'offered': rate, 'achieved': ach, 'drop': drop, 'fail': res['failed']['rate'],
                      'p50': res['dur']['p(50)'], 'p99': res['dur']['p(99)'], 'pass': ok})
        R.log(f"  {cfg} max-step {rate}: {ach:.0f} req/s p99 {res['dur']['p(99)']:.0f} ms drop {drop} "
              f"fail {res['failed']['rate']:.4f} {'pass' if ok else 'FAIL'}")
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
    json.dump({'cfg': cfg, 'max_rps': mx, 'steps': steps}, open(f'{d}/max.json', 'w'), indent=1)
    R.log(f"  {cfg} max: {mx:.0f} req/s")
    return mx


def latency1(cfg, d):
    os.makedirs(d, exist_ok=True)
    R.wait_quiet(CTRS)
    tag = f'lat1-{cfg}-{int(time.time())}'
    R.j1(f"cd {R.K6}; rm -f out-{tag}.json; nohup taskset -c 4-15 ./k6 run -q --no-color -e TARGET={R.FRONTENDS[0]} "
         f"-e WARM_S=2 -e MEASURE_S=13 -e OUT={R.K6}/out-{tag}.json latency1.js > k6-{tag}.log 2>&1 < /dev/null & echo $! > {R.K6}/pid-{tag}")
    res = R.k6_wait(tag, timeout=120)
    json.dump(res, open(f'{d}/k6.json', 'w'), indent=1)
    dur = res['dur']
    R.log(f"  {cfg} latency1: {res['reqs']['count'] / 13:.0f} req/s  avg {dur['avg']:.2f} p50 {dur['p(50)']:.2f} "
          f"p90 {dur['p(90)']:.2f} p99 {dur['p(99)']:.2f} ms  fail {res['failed']['rate']:.4f}")


def main():
    global CTRS
    res = sys.argv[1]
    os.makedirs(res, exist_ok=True)
    R.LOG = f'{res}/run.log'
    R.log('start MeshInsight-style', json.dumps({'start': START, 'step': STEP, 'fracs': FRACS}), 'cpu:',
          R.sh('cat /sys/devices/system/cpu/smt/control /sys/devices/system/cpu/intel_pstate/no_turbo '
               '/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor').split())
    for dep, group, pre, cfgs in R.PLAN:
        mesh = 'l5d' if group.startswith('l5d') else ('istio' if group.startswith('istio') else None)
        try:
            R.log(f'== deploy {dep} ({group}, pre {pre})')
            R.deploy(group, mesh)
            R.apply_steps(group, pre)
            if pre:
                time.sleep(15)
            bad = R.smoke()
            if bad:
                raise RuntimeError(f'smoke failed: {bad[:4]}')
            CTRS = R.containers()
            assert len(CTRS) == (48 if mesh else 24), f'{len(CTRS)} containers'
            R.light_load(30)
            for cfg, steps in cfgs:
                if steps:
                    R.apply_steps(group, steps)
                    R.light_load(50 if mesh == 'istio' else 25)
                    bad = R.smoke()
                    if bad:
                        raise RuntimeError(f'smoke failed after {steps}: {bad[:4]}')
                mx = MAXRPS[cfg]
                meta = {'cfg': cfg, 'deployment': dep, 'group': group, 'pre': pre, 'steps': steps, 'rep': '1',
                        'containers': CTRS, 'mesh': mesh, 'max_rps': mx, 'c_s': R.C_S, 'b_s': R.B_S}
                latency1(cfg, f'{res}/{cfg}/latency1')
                for frac in FRACS:
                    rate = round(mx * frac)
                    d = f'{res}/{cfg}/rep1/r{rate}'
                    os.makedirs(d, exist_ok=True)
                    json.dump(dict(meta, frac=frac), open(f'{d}/meta.json', 'w'), indent=1)
                    R.measure(cfg, rate, d, CTRS)
        except Exception as e:
            R.log(f'!! {dep}: {e}')
    R.kubectl('delete', 'ns', R.NS, '--ignore-not-found', '--wait=false', check=False)
    R.log('done')


CTRS = {}
if __name__ == '__main__':
    main()
