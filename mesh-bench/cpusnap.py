#!/usr/bin/env python3
"""CPU snapshot: per-pod cgroup usage (usec), whole-host busy jiffies, and the
busy time outside kubepods. `cpusnap.py snap > a.json`, then
`cpusnap.py diff a.json b.json` prints cores used per pod / per bucket."""
import glob, json, os, subprocess, sys, time

CG = '/sys/fs/cgroup/kubepods.slice'


def usage(path, key='usage_usec'):
    with open(os.path.join(path, 'cpu.stat')) as f:
        for line in f:
            k, v = line.split()
            if k == key:
                return int(v)
    return 0


def pod_names():
    out = subprocess.run(['kubectl', 'get', 'pods', '-A', '-o',
                          'jsonpath={range .items[*]}{.metadata.uid} {.metadata.namespace}/{.metadata.name}{"\\n"}{end}'],
                         capture_output=True, text=True).stdout
    return {u.replace('-', '_'): n for u, n in (l.split() for l in out.splitlines() if l)}


def container_names():
    out = subprocess.run(['kubectl', 'get', 'pods', '-n', 'boutique', '-o',
                          'jsonpath={range .items[*]}{range .status.containerStatuses[*]}{.containerID} {.name}{"\\n"}{end}'
                          '{range .status.initContainerStatuses[*]}{.containerID} {.name}{"\\n"}{end}{end}'],
                         capture_output=True, text=True).stdout
    return {l.split()[0].split('//')[-1]: l.split()[1] for l in out.splitlines() if len(l.split()) == 2}


def host_busy_usec():
    with open('/proc/stat') as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle = v[3] + v[4]
    hz = os.sysconf('SC_CLK_TCK')
    return (sum(v[:8]) - idle) * 1_000_000 // hz


def snap():
    names = pod_names()
    pods = {}
    for p in glob.glob(CG + '/**/kubepods*-pod*.slice', recursive=True):
        uid = p.rsplit('-pod', 1)[1][:-len('.slice')]
        pods[names.get(uid, uid)] = usage(p)
    cnames, ctrs, thr = container_names(), {}, {}
    for p in glob.glob(CG + '/**/cri-containerd-*.scope', recursive=True):
        n = cnames.get(p.rsplit('cri-containerd-', 1)[1][:-len('.scope')])
        if n:
            uid = os.path.dirname(p).rsplit('-pod', 1)[1][:-len('.slice')]
            n = names.get(uid, uid).split('/')[-1] + '/' + n
            ctrs[n] = ctrs.get(n, 0) + usage(p)
            thr[n] = thr.get(n, 0) + usage(p, 'throttled_usec')
    return {'t': time.time(), 'host_busy': host_busy_usec(), 'kubepods': usage(CG), 'pods': pods, 'ctrs': ctrs, 'thr': thr}


def diff(a, b):
    dt = b['t'] - a['t']
    c = lambda x: x / 1e6 / dt
    res = {'dt': dt, 'host_busy': c(b['host_busy'] - a['host_busy']),
           'kubepods': c(b['kubepods'] - a['kubepods']), 'pods': {}}
    res['outside'] = res['host_busy'] - res['kubepods']
    for k, v in b['pods'].items():
        if k in a['pods']:
            res['pods'][k] = c(v - a['pods'][k])
    res['ctrs'] = {k: c(v - a.get('ctrs', {}).get(k, v)) for k, v in b.get('ctrs', {}).items()}
    res['thr'] = {k: c(v - a.get('thr', {}).get(k, v)) for k, v in b.get('thr', {}).items()}
    return res


if __name__ == '__main__':
    if sys.argv[1] == 'snap':
        json.dump(snap(), sys.stdout)
    else:
        a, b = (json.load(open(x)) for x in sys.argv[2:4])
        print(json.dumps(diff(a, b), indent=1))
