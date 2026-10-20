#!/usr/bin/env python3
"""run_threads.py RESULTS_DIR RATE CFG[,CFG...]: one step at RATE req/s (2 s warm,
8 s measured) per configuration with run_max_probe.py's probes plus the CPU of
every thread in every app container (cgroup.procs, /proc/<pid>/task/<tid>/stat) and each
container's cgroup CPU, to find a thread that saturates before the host does.
Deploy, DPU settings and environment as run_max_probe.py.
Results: RESULTS_DIR/<cfg>/threads.json."""
import json, os, sys, time
import run as R
import run_max_probe as P


def host_threads(ctrs):
    out = {}
    for cid, c in ctrs.items():
        try:
            pids = open(f"{c['cgroup']}/cgroup.procs").read().split()
        except OSError:
            continue
        # /proc/<tid>/stat of a non-leader thread shows the whole process: go through task/
        tids = [(pid, tid) for pid in pids for tid in (os.listdir(f'/proc/{pid}/task') if os.path.isdir(f'/proc/{pid}/task') else [])]
        for pid, tid in tids:
            try:
                st = open(f'/proc/{pid}/task/{tid}/stat').read()
            except OSError:
                continue
            comm = st[st.index('(') + 1:st.rindex(')')]
            rest = st[st.rindex(')') + 2:].split()
            out[tid] = (cid, comm, int(rest[11]) + int(rest[12]))
    return out


def cg_usage(ctrs):
    return {cid: R.cpustat(c['cgroup']).get('usage_usec', 0) for cid, c in ctrs.items()}


def thread_step(cfg, mesh, d, ctrs):
    rate = int(os.environ['THREAD_RATE'])
    R.wait_quiet(ctrs)
    tag = f'thr-{cfg}-{rate}-{int(time.time())}'
    t0 = R.k6_start(tag, rate, 2, 8, 0)
    t0 = max(t0, time.time() - 0.4)
    time.sleep(max(0, t0 + 2.2 - time.time()))
    a_t, a_c, a_time, p0 = host_threads(ctrs), cg_usage(ctrs), time.time(), P.probes()
    time.sleep(max(0, t0 + 9.8 - time.time()))
    b_t, b_c, b_time, p1 = host_threads(ctrs), cg_usage(ctrs), time.time(), P.probes()
    res = R.k6_wait(tag, timeout=120)
    dt = b_time - a_time
    hz = os.sysconf('SC_CLK_TCK')
    threads = [{'tid': tid, 'pod': ctrs[cid]['pod'], 'container': ctrs[cid]['container'], 'comm': comm,
                'cores': (ticks - a_t[tid][2]) / hz / dt}
               for tid, (cid, comm, ticks) in b_t.items() if tid in a_t]
    threads.sort(key=lambda t: -t['cores'])
    cont = {cid: {'pod': ctrs[cid]['pod'], 'container': ctrs[cid]['container'],
                  'cores': (b_c[cid] - a_c.get(cid, 0)) / 1e6 / dt} for cid in b_c}
    out = dict(P.k6_result(res, rate, 8), threads=threads, containers=cont, **P.summarize(p0, p1))
    json.dump(out, open(f'{d}/threads.json', 'w'), indent=1)
    R.log(f"  {cfg} step {rate}: {out['achieved']:.0f} req/s p50 {out['p50']:.1f} p99 {out['p99']:.0f} ms drop {out['drop']} "
          f"| host {out['host_busy']:.1f} dpu {out['dpu_busy']:.1f} | top threads " +
          ', '.join(f"{t['pod'].split('-')[0]}/{t['comm']}:{t['cores']:.2f}" for t in threads[:8]))


if __name__ == '__main__':
    os.environ['THREAD_RATE'] = sys.argv[2]
    P.SKIP_P1500 = True
    P.maxrate = thread_step
    sys.argv = [sys.argv[0], sys.argv[1], sys.argv[3]]
    P.main()
