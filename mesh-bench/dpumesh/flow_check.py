#!/usr/bin/env python3
"""flow_check.py <proxy log>

Checks a run of a DPU proxy that has the flow dispatcher (DPUMesh 80363ab and
later; eu_check.py covers the older per-worker EU ranges). The dispatcher, not
the process's DPUMESH_SERVER, places every client flow on a worker (fewest
flows first); a backend flow goes to the worker that asked for it. Every flow
holds a DPA forward resource on its worker: a pool thread, or with
DMESH_DPA_MUX=n a ring slot of one of the worker's n mux threads (8 each).

Prints per worker the client and backend flows opened and the highest flow
slot used, how the forward rings were served (mux threads or pool threads),
and the DPA and flow errors in the log. Exit status 1 if there is any."""
import collections, re, sys

ERRORS = [  # (label, pattern): any match makes the run suspect
    ('mux full', r'raise DMESH_DPA_MUX'),
    ('mux add failed', r'Failed to add the flow to a DPA mux thread'),
    ('mux ring stopped', r'forward ring stopped, error'),
    ('mux thread stalled', r'DPA mux thread \d+ (is stalled|is not running)'),
    ('mux close timeout', r'not closed within \d+ ms'),
    ('pool exhausted', r'DPA thread pool exhausted'),
    ('no DPA thread', r'No DPA thread available'),
    ('DPA device error', r'DPA context reported a device-side error'),
    ('backend timeout', r'dmesh backend creation timed out'),
    ('backend gone', r'dmesh DMA backend gone'),
]

opens = collections.defaultdict(lambda: [0, 0])  # worker -> [client, backend]
peak = collections.Counter()                     # worker -> highest slot + 1
mux_threads, mux_adds, pool_assigns = {}, 0, 0
errors = collections.Counter()
doca_err = collections.Counter()
for l in open(sys.argv[1], errors='replace'):
    m = re.search(r'\[dispatcher\] session=\S+ flow=\S+ owner=(\d+) slot=(\d+) epoch=\d+ backend=(\d)', l)
    if m:
        w, slot, backend = int(m.group(1)), int(m.group(2)), int(m.group(3))
        opens[w][backend] += 1
        peak[w] = max(peak[w], slot + 1)
        continue
    m = re.search(r'DPA mux: (\d+) threads on worker (\d+)', l)
    if m:
        mux_threads[int(m.group(2))] = int(m.group(1))
    if 'on DPA mux thread' in l:
        mux_adds += 1
    if 'Assigned DPA pool thread' in l:
        pool_assigns += 1
    for label, pat in ERRORS:
        if re.search(pat, l):
            errors[label] += 1
    m = re.search(r'\]\[ERR\]\[[^]]*\]\[[^]]*\]\[[^]]*\] (.*)', l)
    if m:
        doca_err[re.sub(r'\d+', 'N', m.group(1))[:110]] += 1

if not opens:
    sys.exit('no dispatcher flow lines in the log (a proxy without the dispatcher? use eu_check.py)')
print('worker  client  backend  peak_slot  mux_threads')
for w in sorted(opens):
    c, b = opens[w]
    print(f'{w:6d} {c:7d} {b:8d} {peak[w]:10d} {mux_threads.get(w, 0):12d}')
for msg, n in doca_err.most_common(8):
    print(f'DOCA ERR x{n}: {msg}')
c = sum(v[0] for v in opens.values())
b = sum(v[1] for v in opens.values())
busiest = max(opens, key=lambda w: sum(opens[w]))
dpa = (f'mux {min(mux_threads.values())}-{max(mux_threads.values())} threads/worker, {mux_adds} ring adds'
       if mux_threads else f'one pool thread per flow, {pool_assigns} assigns')
err = ', '.join(f'{k} x{v}' for k, v in errors.items()) or 'none'
print(f'flows: {c} client + {b} backend opens on {len(opens)} workers (worker {busiest}: '
      f'{sum(opens[busiest])}, highest slot {max(peak.values())}); DPA: {dpa}; errors: {err}')
sys.exit(1 if errors else 0)
