#!/usr/bin/env python3
"""run_dpumesh.py RESULTS_DIR [RATE]: the DPUMesh point of the overhead run.

The same 24 Online Boutique processes on jet2 (mk.py dpumesh: no sidecar, gRPC
over DPUMesh) with the proxy on jet2's DPU (PF1; DPUMesh feature/dpa-mux =
main + DPA mux, 14 workers, DMESH_DPA_MUX=8, event-driven), measured exactly
as run_mi.py measures a point: latency1 (one request outstanding), then RATE
(default 1,500 HTTP req/s) for 20 s with cgroup CPU, perf and bpftrace in
their windows. Results go to RESULTS_DIR/D1-dpumesh/.

DPU side: ~/DPUMesh-ob-mux/ob-bench/{start.sh,env.sh,irq.sh} (../dpumesh/dpu-jet2),
run as jukebox with the sudo password on stdin; the proxy is stopped by its own
PID, irq placement and irqbalance are restored, and the proxy log is copied next
to the results and checked with ../dpumesh/flow_check.py."""
import json, os, subprocess, sys, time
import run as R
import run_mi as M

CFG = 'D1-dpumesh'
DPU = 'jukebox@192.168.100.2'
# DPU_OB / DPU_PROXY_ENV: another DPU tree (its ob-bench) or proxy environment
OB = os.environ.get('DPU_OB', '~/DPUMesh-ob-mux/ob-bench')
PROXY_ENV = os.environ.get('DPU_PROXY_ENV', 'W=14 DMESH_DPA_MUX=8 DMESH_BUSY_POLL=0')
PW = os.path.join(R.HELPERS, '.pw')
FLOW_CHECK = os.path.join(R.HERE, '..', 'dpumesh', 'flow_check.py')


def dpu(cmd, sudo_pw=False, check=True):
    """Run cmd on the DPU; with sudo_pw the password arrives on stdin as SUDO_PW."""
    if sudo_pw:
        cmd = f'read -r SUDO_PW; export SUDO_PW; {cmd}'
    with open(PW) if sudo_pw else open(os.devnull) as inp:
        p = subprocess.run(['ssh', '-o', 'BatchMode=yes', DPU, cmd], stdin=inp, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    if check and p.returncode:
        raise RuntimeError(f'dpu: {cmd[-120:]}: exit {p.returncode}: {out[-400:]}')
    return out


def dpu_sudo(cmd, check=True):
    return dpu(f'echo "$SUDO_PW" | sudo -S -p "" true && sudo {cmd}', sudo_pw=True, check=check)


def main():
    res = sys.argv[1]
    rate = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    os.makedirs(res, exist_ok=True)
    R.LOG = f'{res}/run.log'
    tag = f'{CFG}-{int(time.time())}'
    R.log('start DPUMesh point', json.dumps({'cfg': CFG, 'rate': rate, 'proxy_env': PROXY_ENV}), 'cpu:',
          R.sh('cat /sys/devices/system/cpu/smt/control /sys/devices/system/cpu/intel_pstate/no_turbo '
               '/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor').split())
    try:
        R.log('dpu:', dpu(f'cat ~/DPUMesh-ob-mux/.rev; ls -la --time-style=+%m-%d_%H:%M '
                          f'~/DPUMesh-ob-mux/linkerd2-proxy/target/release/linkerd2-proxy'))
        dpu_sudo(f'bash {OB}/irq.sh pin')
        dpu(f'cd {OB} && ./start.sh mocks')
        time.sleep(1)
        R.log('dpu proxy:', dpu(f'cd {OB} && {PROXY_ENV} ./start.sh proxy {tag}', sudo_pw=True))
        R.log(f'== deploy dpumesh')
        R.deploy('dpumesh', None)
        bad = R.smoke()
        if bad:
            raise RuntimeError(f'smoke failed: {bad[:4]}')
        M.CTRS = ctrs = R.containers()
        assert len(ctrs) == 24, f'{len(ctrs)} containers'
        R.light_load(30)
        meta = {'cfg': CFG, 'deployment': 'dpumesh', 'group': 'dpumesh', 'pre': [], 'steps': [], 'rep': '1',
                'containers': ctrs, 'mesh': 'dpumesh', 'max_rps': rate, 'c_s': R.C_S, 'b_s': R.B_S,
                'dpu': {'proxy_env': PROXY_ENV, 'rev': 'feature/dpa-mux cd01a50 + linkerd2-proxy 154b428b',
                        'pci': 'DPU 03:00.1 / host 0b:00.1', 'proxy_log': f'proxy-{tag}.log'}}
        M.latency1(CFG, f'{res}/{CFG}/latency1')
        d = f'{res}/{CFG}/rep1/r{rate}'
        os.makedirs(d, exist_ok=True)
        json.dump(dict(meta, frac=1.0), open(f'{d}/meta.json', 'w'), indent=1)
        R.measure(CFG, rate, d, ctrs)
    except Exception as e:
        R.log(f'!! {CFG}: {e}')
    finally:
        R.kubectl('delete', 'ns', R.NS, '--ignore-not-found', '--wait=true', '--timeout=180s', check=False)
        R.log('dpu stop:', dpu(f'cd {OB} && ./start.sh stop', sudo_pw=True, check=False))
        R.log('dpu irq restore:', dpu_sudo(f'bash {OB}/irq.sh restore', check=False))
        os.makedirs(f'{res}/{CFG}', exist_ok=True)
        log = f'{res}/{CFG}/proxy-{tag}.log'
        subprocess.run(['scp', '-q', f'{DPU}:{OB.removeprefix("~/")}/run/proxy-{tag}.log', log], check=False)
        if os.path.exists(log):
            fc = subprocess.run([sys.executable, FLOW_CHECK, log], capture_output=True, text=True)
            open(f'{res}/{CFG}/flow_check.txt', 'w').write(fc.stdout + fc.stderr)
            R.log(f'flow_check exit {fc.returncode}:', (fc.stdout + fc.stderr).strip()[-600:])
        R.log('done')


if __name__ == '__main__':
    main()
