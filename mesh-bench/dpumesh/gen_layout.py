#!/usr/bin/env python3
"""gen_layout.py <n_fe> <n_cat> <n_cur> <n_rec> <workers> <out_workers_file>

Places the ob.sh processes on DPU workers and sizes each worker's DPA EU range.
Every DPUMesh stream holds a DPA thread, which must have an EU of its own:
  - a client stream per (client process, target address);
  - a backend stream per (client's worker, server address), on the server's
    worker (the DPU proxy keeps one HTTP/2 connection per target per worker);
  - one spare backend stream per server process (DPUMESH_BACKEND_POOL=1).
Frontend i (partitioned) calls catalog (i-1)%n_cat+1, currency (i-1)%n_cur+1,
recommendation (i-1)%n_rec+1 and the single cart, shipping, checkout and ad.
Frontend i runs on worker i-1; the servers are packed onto the workers with
the fewest streams. Prints the stream total and DPUMESH_DPA_EU_OFFSETS."""
import collections, sys

n_fe, n_cat, n_cur, n_rec, W = map(int, sys.argv[1:6])
out = sys.argv[6]
# FE_RR=1: every frontend calls every replica of catalog, currency and
# recommendation (k8sob/gen.py FE_RR) instead of one of each
import os
FE_RR = os.environ.get('FE_RR') == '1'
EU_TOTAL = 190

clients = collections.defaultdict(list)   # client process -> server addresses
for i in range(1, n_fe + 1):
    if FE_RR:
        clients[f'frontend-{i}'] = ([f'productcatalogservice-{r}' for r in range(1, n_cat + 1)] +
                                    [f'currencyservice-{r}' for r in range(1, n_cur + 1)] +
                                    [f'recommendationservice-{r}' for r in range(1, n_rec + 1)] +
                                    ['cartservice', 'shippingservice', 'checkoutservice', 'adservice'])
    else:
        clients[f'frontend-{i}'] = [f'productcatalogservice-{(i - 1) % n_cat + 1}',
                                    f'currencyservice-{(i - 1) % n_cur + 1}',
                                    f'recommendationservice-{(i - 1) % n_rec + 1}',
                                    'cartservice', 'shippingservice', 'checkoutservice', 'adservice']
clients['checkoutservice'] = ['productcatalogservice-1', 'currencyservice-1', 'cartservice',
                              'shippingservice', 'paymentservice', 'emailservice']
for r in range(1, n_rec + 1):
    clients[f'recommendationservice-{r}'] = [f'productcatalogservice-{(r - 1) % n_cat + 1}']

servers = ([f'productcatalogservice-{r}' for r in range(1, n_cat + 1)] +
           [f'currencyservice-{r}' for r in range(1, n_cur + 1)] +
           [f'recommendationservice-{r}' for r in range(1, n_rec + 1)] +
           ['cartservice', 'shippingservice', 'checkoutservice', 'adservice', 'emailservice', 'paymentservice'])

worker = {f'frontend-{i}': (i - 1) % W for i in range(1, n_fe + 1)}
callers = collections.defaultdict(list)
for c, targets in clients.items():
    for t in targets:
        callers[t].append(c)


def server_streams(s):
    # backend streams: one per distinct caller worker (callers placed first:
    # frontends are placed; other callers counted one each) + spare + own clients
    return len(callers[s]) + 1 + len(clients.get(s, []))


load = collections.Counter({k: len(clients[f'frontend-{k + 1}']) if k < n_fe else 0 for k in range(W)})
for s in sorted(servers, key=server_streams, reverse=True):
    k = min(range(W), key=lambda k: load[k])
    worker[s] = k
    load[k] += server_streams(s)

total = sum(load.values())
if total > EU_TOTAL:
    sys.exit(f'{total} streams > {EU_TOTAL} EUs')
spare = EU_TOTAL - total
offsets, acc = [], 0
for k in range(W):
    offsets.append(acc)
    acc += load[k] + spare // W
with open(out, 'w') as f:
    for p, k in sorted(worker.items(), key=lambda x: (x[1], x[0])):
        f.write(f'{p} {k}\n')
print(f'streams {total} of {EU_TOTAL} EUs; per worker {[load[k] for k in range(W)]}')
print('DPUMESH_DPA_EU_OFFSETS=' + ','.join(map(str, offsets)))
