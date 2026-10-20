#!/usr/bin/env python3
"""run_wake.py RESULTS_DIR [CFG,CFG,...]: how the app processes wait and wake,
no sidecar against DPUMesh, and which DPUMesh wait knob drives the difference.

Same jet2 setup, 24-pod layout and timing as run_mi.py / run_dpumesh.py: latency1
(one request outstanding), then 1,500 HTTP req/s (30 s of load) with cgroup CPU and /proc
context switches over 2.5-10 s, perf 10-14.5 s and bpftrace 15-19 s. Added:
  bpftrace 15-19 s   syscalls per cgroup and syscall number; epoll/poll returns
                     with and without ready fds; reads that returned data
  DPUMesh only       DPUMESH_WAIT_STATS per pod (core idle-wake counters),
                     snapshotted at both ends of the CPU window, and from 21 s a 4 s
                     uretprobe on dmesh_poll_eq: polls, delivered events, and
                     wakes whose first poll found nothing
Configurations (DPU side as run_dpumesh.py, restarted for every DPUMesh one):
  W1-dpumesh   DPUMesh defaults: nap 10->100 us, linger 1 ms
  W2-linger0   DPUMESH_LINGER_US=0: naps only, then the doorbell
  W3-doorbell  DPUMESH_NAP_US=0 DPUMESH_LINGER_US=0: the doorbell after every empty poll
  W0-nosidecar no sidecar (TCP)
  V1-watcher   DPUMESH_WATCHER=1: the idle watcher thread makes the naps and linger
               polls with carrier peeks; the EQ wakes only for work or to sleep
  V3-watcher-doorbell  DPUMESH_WATCHER=1 with W3's knobs: the doorbell after every
               empty poll, the watcher only for outstanding custody
  F1-comchwake DPUMESH_COMCH_WAKE=1: push descriptors arrive as Comch fast-path
               completions (no ARM/DOORBELL), default nap/linger
  F3-comchwake-sleep  F1 with W3's knobs: sleep on the completion after every
               empty poll
  L1-legacy    DPUMESH_COMCH_WAKE=0 on a library whose default is the fast path: W1
  G1-default   the library's defaults: fast path, and with signaled receives no
               naps or linger, no wake on send, sleep with open custody unless a
               sender waits for space
  G2-default-repeat  G1 again (run-to-run spread)
  G3-custody-poll    G1 but open custody keeps the EQ polling (DPUMESH_CUSTODY_SLEEP=0)
  G4-send-wake       G1 but a send wakes a sleeping EQ (DPUMESH_SEND_WAKE=1)
Run as jukebox with HELPERS naming the scratchpad j1/sudo2 helpers and .pw."""
import glob, json, os, subprocess, sys, time
import run as R
import run_mi as M          # sets the 20 s point timing on R
import run_dpumesh as D

RATE = 1500
R.PROF_S = 15               # the load continues to 30 s for the uprobe window
U0, U_S = 21, 4
LIB = '/home/jukebox/DPUMesh/build/lib/libdpumesh.so.5'
WAIT_DIR = '/tmp/dmesh-wait'
CFGS = {
    'W1-dpumesh': {},
    'W2-linger0': {'DPUMESH_LINGER_US': '0'},
    'W3-doorbell': {'DPUMESH_NAP_US': '0', 'DPUMESH_LINGER_US': '0'},
    'W0-nosidecar': None,
    'V1-watcher': {'DPUMESH_WATCHER': '1'},
    'V3-watcher-doorbell': {'DPUMESH_WATCHER': '1', 'DPUMESH_NAP_US': '0', 'DPUMESH_LINGER_US': '0'},
    'F1-comchwake': {'DPUMESH_COMCH_WAKE': '1'},
    'F3-comchwake-sleep': {'DPUMESH_COMCH_WAKE': '1', 'DPUMESH_NAP_US': '0', 'DPUMESH_LINGER_US': '0'},
    # host library with the fast path on by default (from 2026-10-19 evening)
    'L1-legacy': {'DPUMESH_COMCH_WAKE': '0'},
    'G1-default': {},
    'G2-default-repeat': {},
    'G3-custody-poll': {'DPUMESH_CUSTODY_SLEEP': '0'},
    'G4-send-wake': {'DPUMESH_SEND_WAKE': '1'},
}
HOST_REPO = '/home/jukebox/DPUMesh'
DPU_REV = os.environ.get('DPU_REV', 'feature/dpa-mux cd01a50 + linkerd2-proxy 154b428b')


def host_lib_rev():
    """Branch, commit and whether the host library's tree had local changes."""
    git = lambda *a: subprocess.run(['git', '-C', HOST_REPO, *a], capture_output=True, text=True).stdout.strip()
    return {'branch': git('rev-parse', '--abbrev-ref', 'HEAD'), 'commit': git('rev-parse', '--short', 'HEAD'),
            'dirty': bool(git('status', '--porcelain', '--untracked-files=no')),
            'lib_mtime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(LIB)))}

R.BPF = r'''
tracepoint:raw_syscalls:sys_enter { @sys[cgroup] = count(); @sysid[cgroup, args->id] = count(); }
tracepoint:sched:sched_switch { @sw[cgroup, args->prev_state == 0 ? 1 : 0] = count(); }
tracepoint:irq:softirq_entry { @sirq[args->vec] = count(); }
tracepoint:syscalls:sys_exit_epoll_pwait, tracepoint:syscalls:sys_exit_epoll_wait,
tracepoint:syscalls:sys_exit_ppoll, tracepoint:syscalls:sys_exit_poll { @pollret[cgroup, probe, args->ret > 0 ? 1 : 0] = count(); }
tracepoint:syscalls:sys_exit_read, tracepoint:syscalls:sys_exit_recvfrom,
tracepoint:syscalls:sys_exit_recvmsg { @rx[cgroup, probe, args->ret > 0 ? 1 : 0] = count(); }
interval:s:%d { exit(); }
'''

BPF_POLL = r'''
uretprobe:%s:dmesh_poll_eq {
  $r = (int32)retval;
  @polls[cgroup] = count();
  if (@prev[tid] == 0) {
    if ($r > 0) { @wake_work[cgroup] = count(); } else { @wake_empty[cgroup] = count(); }
  }
  if ($r > 0) { @events[cgroup] = sum($r); @prev[tid] = 1; } else { @prev[tid] = 0; }
}
interval:s:%d { clear(@prev); exit(); }
'''


def wait_snap():
    """DPUMESH_WAIT_STATS files: pod/file -> counters and the file's write time."""
    out = {}
    for f in glob.glob(f'{WAIT_DIR}/*/dpumesh-wait.*'):
        try:
            st = os.stat(f)
            vals = dict(kv.split('=') for kv in open(f).read().split())
            out[os.path.relpath(f, WAIT_DIR)] = {'mtime': st.st_mtime, **{k: int(v) for k, v in vals.items()}}
        except (OSError, ValueError):
            pass
    return out


def measure(cfg, rate, d, ctrs, dpumesh):
    """R.measure plus the wait-stat snapshots and the dmesh_poll_eq window."""
    os.makedirs(d, exist_ok=True)
    outside0 = R.wait_quiet(ctrs)
    tag = f'{cfg}-{rate}-{int(time.time())}'
    t0 = R.k6_start(tag, rate, R.WARM_S, R.MEASURE_S, R.PROF_S)
    until = lambda s: time.sleep(max(0, t0 + s - time.time()))
    if time.time() - t0 > 5:
        raise RuntimeError(f'k6 start took {time.time() - t0:.0f} s')
    until(R.A0); a = R.snap(ctrs); wa = wait_snap()
    until(R.A1); b = R.snap(ctrs); wb = wait_snap()
    until(R.B0)
    R.sh([R.SUDO, 'perf', 'record', '-q', '-a', '-e', 'cycles', '-F', '499', '--call-graph', 'lbr', '--all-cgroups',
          '-o', f'{d}/perf.data', '--', 'sleep', str(R.B_S)])
    until(R.C0)
    bpf = R.sh([R.SUDO, 'bpftrace', '-f', 'json', '-e', R.BPF % R.C_S], check=False)
    bpf2 = ''
    if dpumesh:
        until(U0)
        bpf2 = R.sh([R.SUDO, 'bpftrace', '-f', 'json', '-e', BPF_POLL % (LIB, U_S)], check=False)
    res = R.k6_wait(tag)
    json.dump(res, open(f'{d}/k6.json', 'w'), indent=1)
    json.dump({'a': a, 'b': b}, open(f'{d}/snap.json', 'w'))
    json.dump({'a': wa, 'b': wb}, open(f'{d}/wait_stats.json', 'w'), indent=1)
    open(f'{d}/bpf.json', 'w').write(bpf)
    open(f'{d}/bpf_poll.json', 'w').write(bpf2)
    host, outside = R.busy_cores(a, b)
    dt = b['t'] - a['t']
    app = sum(b['cg'][k].get('usage_usec', 0) - a['cg'][k].get('usage_usec', 0) for k in ctrs) / 1e6 / dt
    rps = res['reqs']['count'] / R.MEASURE_S if res.get('reqs') else 0
    summ = {'cfg': cfg, 'rate': rate, 'rps': rps, 'p50_ms': res['dur']['p(50)'], 'p99_ms': res['dur']['p(99)'],
            'fail_rate': res['failed']['rate'], 'dropped': (res.get('dropped') or {}).get('count', 0),
            'app_cores': app, 'sidecar_cores': 0.0, 'host_busy': host, 'outside': outside, 'outside_before': outside0,
            'ms_per_req': app * 1000 / rps if rps else None}
    json.dump(summ, open(f'{d}/summary.json', 'w'), indent=1)
    R.log(f'  {cfg} r{rate}: {rps:.0f} rps p50 {summ["p50_ms"]:.1f} p99 {summ["p99_ms"]:.1f} ms fail {summ["fail_rate"]:.4f} '
          f'drop {summ["dropped"]} | app {app:.2f} host {host:.2f} outside {outside:.2f} cores | wait files {len(wb)}')
    t = time.time()
    R.sh(f"{R.SUDO} nice -n 10 perf script -i {d}/perf.data --no-inline -F comm,pid,tid,cpu,time,period,ip,sym,dso,cgroup "
         f"2>/dev/null | gzip -1 > {d}/perf.txt.gz && {R.SUDO} rm -f {d}/perf.data", check=False)
    R.log(f'  perf script {time.time() - t:.0f} s')


def wait_for_others(limit_s=4 * 3600):
    t = time.time()
    while R.others_running():
        if time.time() - t > limit_s:
            raise RuntimeError('another user kept running')
        R.log('  WAIT another user is running:', R.others_running().splitlines()[0][:100])
        time.sleep(60)


def run_cfg(res, cfg, knobs):
    dpumesh = knobs is not None
    tag = f'{cfg}-{int(time.time())}'
    if dpumesh:
        subprocess.run(['rm', '-rf', WAIT_DIR])
        env = {'DPUMESH_WAIT_STATS': f'{WAIT_DIR}/$HOSTNAME', **knobs}
        os.environ['EXTRA_ENV'] = ','.join(f'{k}={v}' for k, v in env.items())
    else:
        os.environ['EXTRA_ENV'] = ''
    R.log(f'== {cfg}', json.dumps({'knobs': knobs, 'extra_env': os.environ['EXTRA_ENV']}))
    try:
        wait_for_others()
        if dpumesh:
            D.dpu_sudo(f'bash {D.OB}/irq.sh pin')
            D.dpu(f'cd {D.OB} && ./start.sh mocks')
            time.sleep(1)
            R.log('dpu proxy:', D.dpu(f'cd {D.OB} && {D.PROXY_ENV} ./start.sh proxy {tag}', sudo_pw=True))
        R.deploy('dpumesh' if dpumesh else 'nosidecar', None)
        if dpumesh:
            for p in json.loads(R.kubectl('-n', R.NS, 'get', 'pods', '-o', 'json'))['items']:
                os.makedirs(f"{WAIT_DIR}/{p['metadata']['name']}", exist_ok=True)
        bad = R.smoke()
        if bad:
            raise RuntimeError(f'smoke failed: {bad[:4]}')
        M.CTRS = ctrs = R.containers()
        assert len(ctrs) == 24, f'{len(ctrs)} containers'
        R.light_load(30)
        meta = {'cfg': cfg, 'deployment': 'dpumesh' if dpumesh else 'nosidecar', 'group': 'dpumesh' if dpumesh else 'nosidecar',
                'pre': [], 'steps': [], 'rep': '1', 'containers': ctrs, 'mesh': 'dpumesh' if dpumesh else None,
                'max_rps': RATE, 'c_s': R.C_S, 'b_s': R.B_S, 'u_s': U_S, 'knobs': knobs,
                'extra_env': os.environ['EXTRA_ENV']}
        if dpumesh:
            meta['host_lib'] = host_lib_rev()
            meta['dpu'] = {'proxy_env': D.PROXY_ENV, 'rev': DPU_REV,
                           'pci': 'DPU 03:00.1 / host 0b:00.1', 'proxy_log': f'proxy-{tag}.log'}
        M.latency1(cfg, f'{res}/{cfg}/latency1')
        d = f'{res}/{cfg}/rep1/r{RATE}'
        os.makedirs(d, exist_ok=True)
        json.dump(dict(meta, frac=1.0), open(f'{d}/meta.json', 'w'), indent=1)
        measure(cfg, RATE, d, ctrs, dpumesh)
    except Exception as e:
        R.log(f'!! {cfg}: {e}')
    finally:
        R.kubectl('delete', 'ns', R.NS, '--ignore-not-found', '--wait=true', '--timeout=180s', check=False)
        if dpumesh:
            R.log('dpu stop:', D.dpu(f'cd {D.OB} && ./start.sh stop', sudo_pw=True, check=False))
            R.log('dpu irq restore:', D.dpu_sudo(f'bash {D.OB}/irq.sh restore', check=False))
            os.makedirs(f'{res}/{cfg}', exist_ok=True)
            log = f'{res}/{cfg}/proxy-{tag}.log'
            subprocess.run(['scp', '-q', f'{D.DPU}:DPUMesh-ob-mux/ob-bench/run/proxy-{tag}.log', log], check=False)
            if os.path.exists(log):
                fc = subprocess.run([sys.executable, D.FLOW_CHECK, log], capture_output=True, text=True)
                open(f'{res}/{cfg}/flow_check.txt', 'w').write(fc.stdout + fc.stderr)
                R.log(f'flow_check exit {fc.returncode}:', (fc.stdout + fc.stderr).strip()[-300:])


def main():
    res = sys.argv[1]
    only = sys.argv[2].split(',') if len(sys.argv) > 2 else list(CFGS)
    os.makedirs(res, exist_ok=True)
    R.LOG = f'{res}/run.log'
    R.log('start wake run', json.dumps({'cfgs': only, 'rate': RATE}))
    wait_for_others()
    R.log('cpu fix:', R.sh([R.SUDO, 'bash', f'{R.HERE}/cpu.sh', 'fix']).strip())
    try:
        for cfg in only:
            run_cfg(res, cfg, CFGS[cfg])
    finally:
        R.log('cpu restore:', R.sh([R.SUDO, 'bash', f'{R.HERE}/cpu.sh', 'restore'], check=False).strip())
        R.log('done')


if __name__ == '__main__':
    main()
