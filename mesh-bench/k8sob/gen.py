#!/usr/bin/env python3
"""gen.py <tcp|dpumesh> > manifest.yaml

Online Boutique as Kubernetes pods running host-built service binaries: frontend
x N_FE (default 10), productcatalog x4, currency x2, recommendation x5, the rest
x1. With FE_RR=1 every frontend round-robins over all replicas of catalog,
currency and recommendation; otherwise frontend i calls one replica of each.
  tcp-fe4.yaml:  N_FE=4 FE_RR=1 gen.py tcp      (no-sidecar, Linkerd, Istio)
  dpumesh.yaml:  gen.py dpumesh                  (DPUMesh, one frontend per DPU worker)

Each pod is privileged, mounts the host root at /host and chroots into it, so the
binaries, runtimes and DPUMesh library come from the host; the network (veth,
cni0, kube-proxy), cgroups and scheduling are Kubernetes'. Testbed only:
privileged pods with the host root mounted have no isolation from the host.

Service targets are 10.99.<replica>.<service>:<port>. With tcp they are fixed
ClusterIPs (one Service per replica, port named grpc/http so Istio proxies them
at L7); with dpumesh they are DPUMesh service keys and the gRPC traffic goes
over DMA to the DPU proxy, each process attached to the DPU worker given by
LAYOUT (default ../dpumesh/layout10.txt). k6 reaches frontend i through the
ClusterIP 10.99.0.<100+i>:80; cart reaches Redis through 10.99.0.250:6379."""
import json, os, sys

MODE = sys.argv[1]
assert MODE in ('tcp', 'dpumesh', 'tcp-direct')
# tcp-direct: as tcp, but every backend Service is headless and clients dial its
# DNS name, so connections go pod to pod without kube-proxy's DNAT
DIRECT = MODE == 'tcp-direct'
TGT2NAME = {}
POD_IPS = json.load(open(os.environ['DIRECT_IPS'])) if os.environ.get('DIRECT_IPS') else {}
ONLY = set(os.environ['ONLY'].split(',')) if os.environ.get('ONLY') else None
HOME = '/home/jukebox'
FORK = f'{HOME}/microservices-demo'
SRC = f'{FORK}/src'
OB = f'{FORK}/dpumesh/.build'
DPUMESH = f'{HOME}/DPUMesh'
LAYOUT = os.environ.get('LAYOUT') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dpumesh', 'layout10.txt')
N_FE, N_CAT, N_CUR, N_REC, W = int(os.environ.get('N_FE', 10)), 4, 2, 5, 10
# FE_RR=1: every frontend round-robins over all replicas of the replicated
# services (used with few frontends, so no replica sits idle)
FE_RR = os.environ.get('FE_RR') == '1'
NS = 'boutique'

worker = dict(l.split() for l in open(LAYOUT) if l.strip())


def target(r, s, port):
    return f'10.99.{r}.{s}:{port}'


CART = target(1, 3, 7070)
SHIPPING = target(1, 5, 50051)
CHECKOUT = target(1, 6, 5050)
AD = target(1, 7, 9555)
EMAIL = target(1, 8, 5000)
PAYMENT = target(1, 9, 50051)
REDIS = '10.99.0.250:6379'

docs = []
pod_seq = [10]


def service(name, ip, port, target_port, app, proto='grpc', backend=True):
    if DIRECT and backend:
        # the pods chroot into the host and so use its resolver, which cannot
        # resolve cluster names: clients get the backend pod's IP (DIRECT_IPS,
        # filled phase by phase by deploy_direct.sh)
        TGT2NAME[f'{ip}:{port}'] = f'{POD_IPS.get(name, name)}:{port}'
        ip = 'None'
    # Istio picks the protocol from the port name: grpc and http are proxied
    # at L7 like the upstream manifests' ports; Linkerd detects it.
    docs.append({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name, 'namespace': NS},
                 'spec': {'clusterIP': ip, 'selector': {'app': app},
                          'ports': [{'name': proto, 'port': port, 'targetPort': target_port}]}})


def pod(name, workdir, env, cmd, tgt=None, local_port=None):
    """A service process. tgt: its service target; local_port: the port it
    listens on in dpumesh mode (in tcp mode it listens on the target port)."""
    pod_seq[0] += 1
    k = int(worker[name]) % W
    e = {k: ','.join(TGT2NAME.get(a, a) for a in v.split(',')) for k, v in env.items()}
    e.update({'DPUMESH_ENABLE': '1' if MODE == 'dpumesh' else '0', 'DPUMESH_SERVER': f'DPUMesh{k}',
              'DPUMESH_POD_IP': f'10.99.0.{pod_seq[0]}', 'DPUMESH_WORKLOAD': name,
              'DPUMESH_BACKEND_POOL': '1', 'DPUMESH_BACKEND_MAX': '16',
              'DPUMESH_PCI_ADDR': '0b:00.1', 'DPUMESH_REVERSE': 'dpu-dma',
              'LD_LIBRARY_PATH': f'{DPUMESH}/build/lib:{DPUMESH}/build/grpc',
              'DISABLE_PROFILER': '1', 'ENABLE_TRACING': '0', 'DISABLE_TRACING': '1', 'DISABLE_STATS': '1',
              'HOME': HOME})
    if tgt:
        e['DPUMESH_SERVICE'] = tgt
        e.setdefault('PORT', tgt.rsplit(':', 1)[1] if MODE != 'dpumesh' else str(local_port))
    envs = ' '.join(f'{k}={json.dumps(v)}' for k, v in e.items())
    script = f'export HOME={HOME}; source {HOME}/opt/env.sh; cd {workdir} && exec env {envs} {cmd}'
    # One sidecar worker under either mesh (Linkerd's default; Istio's is 2).
    docs.append({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': NS, 'labels': {'app': name, 'ob': '1'},
                                                                 'annotations': {'proxy.istio.io/config': '{"concurrency": 1}'}},
                 'spec': {'terminationGracePeriodSeconds': 5, 'restartPolicy': 'Never',
                          'containers': [{'name': 'server', 'image': 'docker.io/library/redis:alpine',
                                          # RDMA registration needs the host's unlimited memlock; raise it as
                                          # root before dropping to the host user (the container default is 8 MiB).
                                          'command': ['chroot', '/host', '/bin/bash', '-c',
                                                      'ulimit -l unlimited && exec /usr/bin/setpriv --reuid=1002 --regid=1002 '
                                                      '--init-groups /bin/bash -c "$0"', script],
                                          'securityContext': {'privileged': True},
                                          'resources': {'requests': {'cpu': '100m', 'memory': '64Mi'}},
                                          'volumeMounts': [{'name': 'host', 'mountPath': '/host'}]}],
                          'volumes': [{'name': 'host', 'hostPath': {'path': '/'}}]}})
    if tgt and MODE != 'dpumesh':
        ip, port = tgt.rsplit(':', 1)
        service(name, ip, int(port), int(port), name)


# Redis: the same image the Kubernetes runs use.
docs.append({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'redis-cart', 'namespace': NS, 'labels': {'app': 'redis-cart', 'ob': '1'}},
             'spec': {'containers': [{'name': 'redis', 'image': 'docker.io/library/redis:alpine',
                                      'resources': {'requests': {'cpu': '70m', 'memory': '200Mi'}}}]}})
service('redis-cart', '10.99.0.250', 6379, 6379, 'redis-cart', 'tcp-redis')

for r in range(1, N_CAT + 1):
    pod(f'productcatalogservice-{r}', f'{SRC}/productcatalogservice', {}, f'{OB}/bin/productcatalogservice', target(r, 1, 3550), 3550)
for r in range(1, N_CUR + 1):
    pod(f'currencyservice-{r}', f'{SRC}/currencyservice', {}, 'node server.js', target(r, 2, 7000), 17000)
cart_port = CART.rsplit(':', 1)[1] if MODE != 'dpumesh' else '17070'
pod('cartservice', f'{OB}/bin/cartservice',
    {'REDIS_ADDR': REDIS, 'ASPNETCORE_URLS': f'http://+:{cart_port}', 'DOTNET_CLI_TELEMETRY_OPTOUT': '1'},
    f'{OB}/toolchains/dotnet/dotnet cartservice.dll', CART, 17070)
pod('shippingservice', f'{SRC}/shippingservice', {}, f'{OB}/bin/shippingservice', SHIPPING, 50051)
pod('adservice', f'{SRC}/adservice', {'JAVA_HOME': f'{OB}/toolchains/jdk'},
    f'{SRC}/adservice/build/install/hipstershop/bin/AdService', AD, 19555)
pod('emailservice', f'{SRC}/emailservice', {}, f'{OB}/venv/emailservice/bin/python email_server.py', EMAIL, 15000)
pod('paymentservice', f'{SRC}/paymentservice', {}, 'node index.js', PAYMENT, 15051)
for r in range(1, N_REC + 1):
    pod(f'recommendationservice-{r}', f'{SRC}/recommendationservice',
        {'PRODUCT_CATALOG_SERVICE_ADDR': target((r - 1) % N_CAT + 1, 1, 3550), 'MAX_WORKERS': '40'},
        f'{OB}/venv/recommendationservice/bin/python recommendation_server.py', target(r, 4, 8080), 18081)
pod('checkoutservice', f'{SRC}/checkoutservice',
    {'PRODUCT_CATALOG_SERVICE_ADDR': target(1, 1, 3550), 'SHIPPING_SERVICE_ADDR': SHIPPING, 'PAYMENT_SERVICE_ADDR': PAYMENT,
     'EMAIL_SERVICE_ADDR': EMAIL, 'CURRENCY_SERVICE_ADDR': target(1, 2, 7000), 'CART_SERVICE_ADDR': CART},
    f'{OB}/bin/checkoutservice', CHECKOUT, 5050)
for r in range(1, N_FE + 1):
    pod(f'frontend-{r}', f'{SRC}/frontend',
        {'LISTEN_ADDR': '0.0.0.0', 'PORT': '8080',
         'PRODUCT_CATALOG_SERVICE_ADDR': ','.join(target(i, 1, 3550) for i in range(1, N_CAT + 1)) if FE_RR else target((r - 1) % N_CAT + 1, 1, 3550),
         'CURRENCY_SERVICE_ADDR': ','.join(target(i, 2, 7000) for i in range(1, N_CUR + 1)) if FE_RR else target((r - 1) % N_CUR + 1, 2, 7000),
         'CART_SERVICE_ADDR': CART,
         'RECOMMENDATION_SERVICE_ADDR': ','.join(target(i, 4, 8080) for i in range(1, N_REC + 1)) if FE_RR else target((r - 1) % N_REC + 1, 4, 8080),
         'SHIPPING_SERVICE_ADDR': SHIPPING,
         'CHECKOUT_SERVICE_ADDR': CHECKOUT, 'AD_SERVICE_ADDR': AD, 'SHOPPING_ASSISTANT_SERVICE_ADDR': '127.0.0.1:1'},
        f'{OB}/bin/frontend')
    service(f'frontend-{r}', f'10.99.0.{100 + r}', 80, 8080, f'frontend-{r}', 'http', backend=False)

if ONLY is not None:  # one deploy phase: only these pods (Services always)
    docs = [d for d in docs if d['kind'] != 'Pod' or d['metadata']['name'] in ONLY]
print('\n---\n'.join(json.dumps(d) for d in docs))
