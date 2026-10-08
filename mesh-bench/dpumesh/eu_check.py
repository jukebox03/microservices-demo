#!/usr/bin/env python3
"""eu_check.py <proxy log> [layout file]

Checks a DPU proxy run for DPA EUs shared by two DPUMesh streams. Every stream
holds a thread of its shard's DPA pool and runs on that thread's EU. DPA
threads are not preempted, so a busy stream starves another one on its EU:
requests on that stream stall for as long as the other stays busy (seconds,
or the whole run). The proxy logs each pool's range and, with the per-worker
pools of DPUMesh feature/grpc-perf, each thread's EU ("Assigned DPA pool
thread i (EU e)"); older proxies give pools their offsets in creation order
and place thread i on EU (offset + i) % END, spilling into the next pool.

Prints each pool's offset, width, peak thread count and processes (with their
layout workers), then every EU used by more than one thread (of the same pool
or of two pools). Exit status 1 if any EU is shared."""
import collections, re, sys

log = sys.argv[1]
worker = dict(l.split() for l in open(sys.argv[2]) if l.strip()) if len(sys.argv) > 2 else {}
off, used, procs, end = {}, collections.defaultdict(set), collections.defaultdict(set), None
eu_of = {}
for l in open(log, errors='replace'):
    m = re.search(r'\]\[(\d+)\]\[DOCA\].*DPA cooperative pool: .* end (\d+), offset (\d+)', l)
    if m:
        off[m.group(1)], end = int(m.group(3)), int(m.group(2))
    m = re.search(r'\]\[(\d+)\]\[DOCA\].*Assigned DPA pool thread (\d+)(?: \(EU (\d+)\))? to connection', l)
    if m:
        used[m.group(1)].add(int(m.group(2)))
        if m.group(3):
            eu_of[(m.group(1), int(m.group(2)))] = int(m.group(3))
    m = re.search(r'\]\[(\d+)\]\[DOCA\].*flow \S+ -> \S+ \(([^)]+)\)', l)
    if m:
        procs[m.group(1)].add(m.group(2))
if not off:
    sys.exit('no DPA pools in the log')

pools = sorted(off, key=off.get)
owner = collections.defaultdict(set)
print('offset width peak  processes')
for j, t in enumerate(pools):
    width = (off[pools[j + 1]] if j + 1 < len(pools) else end) - off[t]
    peak = max(used[t]) + 1 if used[t] else 0
    for i in used[t]:
        owner[eu_of.get((t, i), (off[t] + i) % end)].add((t, i))
    names = ','.join(f'{p}({worker[p]})' if p in worker else p for p in sorted(procs[t]))
    print(f'{off[t]:6d} {width:5d} {peak:4d}  {names}{"  SPILL" if peak > width else ""}')
shared = sorted(e for e, ts in owner.items() if len(ts) > 1)
print('EUs shared by two streams:', ', '.join(map(str, shared)) if shared else 'none')
sys.exit(1 if shared else 0)
