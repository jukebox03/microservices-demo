#!/usr/bin/env python3
"""classify_app.py POINT_DIR [...]: app-container CPU by what the code is, from
perf.txt.gz -> app_buckets.json (cycles per service and bucket).

  kernel        leaf frame in the kernel
  rpc           the app's RPC stack: gRPC, HTTP/2, protobuf, and its socket layer
                (Go grpc / x/net/http2 / protobuf / net/http / net / internal/poll;
                Python cygrpc + protobuf; Node http2 / nghttp2 / libuv / stream
                wraps; .NET System.Native; Java nio / net)
  runtime       garbage collection, scheduler, VM services (Go runtime when no
                app caller is found, V8 GC, libjvm, libcoreclr, CPython memory)
  business      application code that can be named: Go code outside the above
                (main, OB packages, templates, encoding, logging)
  unresolved    JIT or interpreted application code perf cannot name: V8 JIT and
                builtins, JVM/CLR JIT, the CPython eval loop. It runs both the
                service logic and, for Node/Java/.NET/Python, their RPC code.

Go allocation, copying and map/slice helpers are charged to their caller by
walking the call chain from the leaf; GC and scheduler frames are runtime."""
import gzip, json, re, sys, collections

GO_RPC = r'^(go\.opentelemetry\.io|google\.golang\.org/grpc|golang\.org/x/net/http2|google\.golang\.org/protobuf|github\.com/golang/protobuf|net/http|net\.|net/|internal/poll|syscall\.|crypto/tls|bufio\.|golang\.org/x/net/)'
GO_GC_SCHED = r'^runtime\.(gc|scan|mark|sweep|bgsweep|bgscavenge|scavenge|lfstack|tryDeferToSpanScan|greyobject|findObject|heapBits|spanOf|wbBuf|findRunnable|schedule|park_m|mcall|stealWork|runqgrab|netpoll|futex|usleep|notesleep|notewakeup|wakep|startm|stopm|mPark|checkTimers|osyield|semasleep|semawakeup|goschedImpl|gopark|goready|ready|runtimer|systemstack|morestack|newstack|copystack|exitsyscall|entersyscall|reentersyscall|handoffp|retake|sysmon|forEachP|preempt|asyncPreempt|lock2|unlock2|mstart|goexit)'
GO_HELPER = r'^(runtime\.|internal/|sync\.|sync/atomic|memeqbody|indexbytebody|aeshash)'   # charged to the caller
NODE_RPC = r'(node::http2|nghttp2_|uv_|uv__|node::StreamBase|node::LibuvStreamWrap|node::TCPWrap|node::crypto|node::Buffer)'
NODE_GC = r'(v8::internal::(Heap|Scavenger|MarkCompact|Sweeper|Concurrent|GC|MinorMarkCompact|ScavengerCollector|IncrementalMarking|MemoryAllocator|Evacuat|ArrayBufferSweeper)|Builtins_RecordWrite)'
PY_RUNTIME = r'^(PyObject_Malloc|PyObject_Free|_PyObject_Malloc|_PyObject_Free|_Py_Dealloc|gc_collect|_PyObject_GC|PyMem_|_PyMem_|pymalloc|object_dealloc|subtype_dealloc|list_dealloc|dict_dealloc)'


def strip(s):
    return re.sub(r'\+0x[0-9a-f]+$', '', s)


def bucket(frames):
    sym, dso = strip(frames[0][0]), frames[0][1]
    if dso.startswith('[kernel'):
        return 'kernel'
    base = dso.rsplit('/', 1)[-1]
    if 'cygrpc' in base or base.startswith('_message') or 'libgrpc' in base or 'libprotobuf' in base:
        return 'rpc'
    if base in ('libSystem.Native.so', 'libnio.so', 'libnet.so') or base.startswith('libnetty'):
        return 'rpc'
    if base == 'libjvm.so' or base == 'libcoreclr.so' or base == 'libclrjit.so':
        return 'runtime'
    if base.startswith('python3'):
        return 'runtime' if re.match(PY_RUNTIME, sym) else 'unresolved'
    if base == 'node':
        if re.search(NODE_RPC, sym):
            return 'rpc'
        if re.search(NODE_GC, sym):
            return 'runtime'
        return 'unresolved'
    if base.startswith('perf-') or base.startswith('memfd:') or sym == '[unknown]' and base in ('[unknown]',):
        return 'unresolved'
    # Go binaries (and libc called from them): walk from the leaf
    gc_leaf = re.match(GO_GC_SCHED, sym) is not None
    for s, d in frames:
        if d.startswith('[kernel'):
            continue
        s = strip(s)
        if s in ('[unknown]', ''):
            continue
        if re.match(GO_RPC, s):
            return 'rpc'
        if re.match(GO_GC_SCHED, s):
            return 'runtime'
        if re.match(GO_HELPER, s):
            continue
        if d.rsplit('/', 1)[-1].startswith(('libc.so', 'ld-linux', '[vdso]')):
            continue
        return 'business'
    return 'runtime' if gc_leaf or re.match(r'^runtime\.', sym) else 'unresolved'


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
