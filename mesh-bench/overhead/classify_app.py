#!/usr/bin/env python3
"""classify_app.py POINT_DIR [...]: app-container CPU by what the code is, from
perf.txt.gz -> app_buckets.json (cycles per service and bucket).

  kernel        leaf frame in the kernel
  rpc           the app's RPC stack: gRPC, HTTP/2, protobuf, and its socket layer
                (Go grpc / x/net/http2 / protobuf / OB genproto / net/http / net /
                internal/poll; Python cygrpc + protobuf; Node http2 / nghttp2 /
                libuv / stream wraps; .NET System.Native; Java nio / net)
  runtime       garbage collection, scheduler, VM services (Go GC and scheduler,
                V8 GC, libjvm, libcoreclr, CPython memory)
  business      the application's own code: OB's Go code (main, OB packages other
                than genproto) and redis-server
  unresolved    JIT or interpreted application code perf cannot name: V8 JIT and
                builtins, JVM/CLR JIT, the CPython eval loop. It runs both the
                service logic and, for Node/Java/.NET/Python, their RPC code.
  dpumesh       the DPUMesh host stack (DPUMesh runs only): libdpumesh.so.5 and
                the DOCA / verbs libraries under it, libdpumesh_stream.so, the
                Node addon dpumesh_grpc.node, libdpumesh_jni*.so, dpumesh::
                symbols in the patched cygrpc, the Go packages dmeshgo* and
                their cgo stubs; a Go cgo call (runtime.cgocall) made by dmeshgo
                is DPUMesh too. The .NET adapter (Dpumesh.Grpc) is JIT code and
                stays unresolved.

Each sample walks its call chain from the leaf and takes the first frame that
belongs to one of the buckets. Library code is charged to its caller: Go
standard library and third-party packages (context, reflect, time, templates,
encoding/json, logrus, gorilla/mux, ...), Go runtime helpers (allocation,
copying, maps), libc and libstdc++. A Go chain that ends in library code
without reaching a bucket frame (LBR depth runs out, almost all in deep
text/template recursion under the frontend's handlers) is business."""
import gzip, json, re, sys, collections

GO_RPC = r'^(go\.opentelemetry\.io|google\.golang\.org/grpc|golang\.org/x/net/http2|google\.golang\.org/protobuf|google\.golang\.org/genproto|github\.com/golang/protobuf|github\.com/GoogleCloudPlatform/microservices-demo/src/[^/]+/genproto|net/http|net\.|net/|internal/poll|syscall\.|crypto/tls|bufio\.|golang\.org/x/net/)'
GO_GC_SCHED = r'^runtime\.(gc|scan|mark|sweep|bgsweep|bgscavenge|scavenge|lfstack|tryDeferToSpanScan|greyobject|findObject|heapBits|spanOf|wbBuf|findRunnable|schedule|park_m|mcall|stealWork|runqgrab|netpoll|futex|usleep|notesleep|notewakeup|wakep|startm|stopm|mPark|checkTimers|osyield|semasleep|semawakeup|goschedImpl|gopark|goready|ready|runtimer|systemstack|morestack|newstack|copystack|exitsyscall|entersyscall|reentersyscall|handoffp|retake|sysmon|forEachP|preempt|asyncPreempt|lock2|unlock2|mstart|goexit)'
GO_APP = r'^(main\.|github\.com/GoogleCloudPlatform/microservices-demo/)'   # after GO_RPC, which takes genproto
GO_BIN = ('frontend', 'productcatalogservice', 'checkoutservice', 'shippingservice')
APP_BIN = ('redis-server',)
NODE_RPC = r'(node::http2|nghttp2_|uv_|uv__|node::StreamBase|node::LibuvStreamWrap|node::TCPWrap|node::crypto|node::Buffer)'
NODE_GC = r'(v8::internal::(Heap|Scavenger|MarkCompact|Sweeper|Concurrent|GC|MinorMarkCompact|ScavengerCollector|IncrementalMarking|MemoryAllocator|Evacuat|ArrayBufferSweeper)|Builtins_RecordWrite)'
PY_RUNTIME = r'^(PyObject_Malloc|PyObject_Free|_PyObject_Malloc|_PyObject_Free|_Py_Dealloc|gc_collect|_PyObject_GC|PyMem_|_PyMem_|pymalloc|object_dealloc|subtype_dealloc|list_dealloc|dict_dealloc)'


def strip(s):
    return re.sub(r'\+0x[0-9a-f]+$', '', s)


DPUMESH_DSO = ('libdpumesh.so', 'libdpumesh_stream', 'dpumesh_grpc.node', 'libdpumesh_jni', 'libdoca_', 'libflexio',
               'libmlx5', 'libibverbs')
DPUMESH_GO = r'^(dmeshgo[./]|type:\.eq\.dmeshgo|_cgo_[0-9a-f]+_Cfunc_dmesh|dmesh_go_)'


def frame_kind(sym, dso):
    """Bucket of one frame, or None for code that is charged to its caller."""
    base = dso.rsplit('/', 1)[-1]
    if dso.startswith('[kernel'):
        return None
    if base.startswith(DPUMESH_DSO) or 'dpumesh::' in sym or re.match(DPUMESH_GO, sym):
        return 'dpumesh'
    if 'cygrpc' in base or base.startswith('_message') or 'libgrpc' in base or 'libprotobuf' in base:
        return 'rpc'
    if base in ('libSystem.Native.so', 'libnio.so', 'libnet.so') or base.startswith('libnetty'):
        return 'rpc'
    if base in ('libjvm.so', 'libcoreclr.so', 'libclrjit.so'):
        return 'runtime'
    if base.startswith('python3'):
        return 'runtime' if re.match(PY_RUNTIME, sym) else 'unresolved'
    if base == 'node':
        if re.search(NODE_RPC, sym):
            return 'rpc'
        if re.search(NODE_GC, sym):
            return 'runtime'
        return 'unresolved'
    if base.startswith(('perf-', 'memfd:')):
        return 'unresolved'
    if sym in ('[unknown]', ''):
        return None
    if base in APP_BIN:
        return 'business'
    if base in GO_BIN:
        if re.match(GO_RPC, sym):
            return 'rpc'
        if re.match(GO_GC_SCHED, sym):
            return 'runtime'
        if re.match(GO_APP, sym):
            return 'business'
    return None     # Go std/third-party libraries and runtime helpers, libc, libstdc++


def bucket(frames):
    sym, dso = strip(frames[0][0]), frames[0][1]
    if dso.startswith('[kernel'):
        return 'kernel'
    if sym == '[unknown]' and dso.rsplit('/', 1)[-1] == '[unknown]':
        return 'unresolved'
    # a Go cgo call into DPUMesh: the runtime frames under runtime.cgocall
    # (entersyscall, exitsyscall, systemstack) belong to the call
    names = [strip(x) for x, _ in frames]
    if 'runtime.cgocall' in names:
        up = next((n for n in names[names.index('runtime.cgocall') + 1:]
                   if not n.startswith(('runtime.', 'internal/', '[unknown]'))), '')
        if re.match(DPUMESH_GO, up):
            return 'dpumesh'
    go_lib = False
    for s, d in frames:
        s = strip(s)
        k = frame_kind(s, d)
        if k:
            return k
        if d.rsplit('/', 1)[-1] in GO_BIN and s not in ('[unknown]', '') and not s.startswith(('runtime.', 'internal/', 'sync.', 'sync/atomic', 'type:', 'go:')):
            go_lib = True
    if go_lib:
        return 'business'
    return 'runtime' if re.match(r'^runtime\.', sym) else 'unresolved'


def classify(d):
    m = json.load(open(f'{d}/meta.json'))
    scope = {}
    for c in m['containers'].values():
        if c['role'] == 'sidecar':
            continue
        kind = c['pod'].rsplit('-', 1)[0] if c['pod'].rsplit('-', 1)[-1].isdigit() else c['pod']
        scope[c['cgroup'].rsplit('/', 1)[-1]] = kind
    out = collections.defaultdict(collections.Counter)
    hdr, frames = None, []

    def flush():
        if hdr and hdr[0] and frames:
            out[hdr[0]][bucket(frames)] += hdr[1]
    for line in gzip.open(f'{d}/perf.txt.gz', 'rt', errors='replace'):
        if not line.strip():
            flush(); hdr, frames = None, []
            continue
        if not line.startswith(('\t', ' ')):
            mm = re.search(r'\s(\d+)\s+\S*(cri-containerd-[0-9a-f]+\.scope)', line)
            hdr = (scope.get(mm.group(2)), int(mm.group(1))) if mm else None
            frames = []
        else:
            fm = re.match(r'^\s+[0-9a-f]+\s+(.*?)\s+\((.*)\)$', line)
            if fm:
                frames.append((fm.group(1), fm.group(2)))
    flush()
    json.dump({k: dict(v) for k, v in out.items()}, open(f'{d}/app_buckets.json', 'w'), indent=1)
    return out


if __name__ == '__main__':
    for d in sys.argv[1:]:
        classify(d)
        print(d)
