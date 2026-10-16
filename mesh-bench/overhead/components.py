#!/usr/bin/env python3
"""components.py POINT_DIR [...]: sidecar vCPU by bucket and by the frame that
decided the bucket (classify.py's rules) -> components.json.

{bucket: {component: vCPU}}; a component is the deciding frame's crate or module
(Rust: crate, or crate::module for linkerd_app_*; C++: namespace path, three
levels, four under Envoy::Extensions, five under its Filters::Common). Linkerd
`tracing` frames are reported as tracing->runtime, or tracing->CRATE for the
telemetry crate above them. vCPU is the point's sidecar cgroup CPU split by
perf cycles; kernel leaves are one component, 'kernel'."""
import gzip, json, os, re, sys, collections
import classify as C


def component(frames, rules, generic):
    for i, (addr, sym, dso) in enumerate(frames):
        if dso.startswith('[kernel'):
            continue
        s = C.strip(sym)
        if s in ('[unknown]', '', '_'):
            continue
        if any(re.match(pat, s) for _, pat in C.OVERRIDE):
            return s
        if re.match(generic, s):
            continue
        if rules is C.LINKERD and re.match(C.TRACING, s):
            up = next((C.strip(x) for _, x, d in frames[i + 1:] if re.match(C.TRACING_TELEMETRY, C.strip(x))), None)
            return 'tracing->' + (up.split('::')[0] if up else 'runtime')
        if any(re.match(pat, s) for _, pat in rules):
            return s
    return ''


def group(s, istio):
    if s.startswith('tracing->'):
        return s
    p = s.split('::')
    if istio:
        n = 5 if p[:4] == ['Envoy', 'Extensions', 'Filters', 'Common'] else 4 if p[:2] == ['Envoy', 'Extensions'] else 3
        return '::'.join(p[:n])
    return '::'.join(p[:2]) if p[0] in ('linkerd_app_inbound', 'linkerd_app_outbound', 'linkerd_app_core') else p[0]


def run(d):
    meta = json.load(open(f'{d}/meta.json'))
    istio = meta.get('mesh') == 'istio'
    rules, generic = (C.ENVOY, C.EGENERIC) if istio else (C.LINKERD, C.LGENERIC)
    cores = json.load(open(f'{d}/summary.json'))['sidecar_cores']
    by_scope = {os.path.basename(c['cgroup']): c for c in meta['containers'].values()}
    cyc = collections.defaultdict(collections.Counter)
    total = 0
    cur = None

    def flush(x):
        nonlocal total
        if not x:
            return
        hdr, frames = x
        m = re.search(r'(cri-containerd-[0-9a-f]+\.scope)', hdr['rest'])
        c = by_scope.get(m.group(1)) if m else None
        if not c or c['role'] != 'sidecar' or not frames:
            return
        per = int(hdr['period']); total += per
        if frames[0][2].startswith('[kernel'):
            cyc['kernel']['kernel'] += per
            return
        cyc[C.user_bucket(frames, rules, generic)][group(component(frames, rules, generic), istio)] += per

    with gzip.open(f'{d}/perf.txt.gz', 'rt', errors='replace') as f:
        for line in f:
            if not line.strip():
                flush(cur); cur = None
                continue
            m = C.HDR.match(line)
            if m and not line.startswith(('\t', ' ')):
                flush(cur); cur = (m.groupdict(), [])
                continue
            fm = C.FRAME.match(line)
            if fm and cur:
                cur[1].append((fm.group(1), fm.group(2), fm.group(3)))
        flush(cur)
    out = {b: {k: cores * v / total for k, v in sorted(cc.items(), key=lambda x: -x[1])} for b, cc in cyc.items()}
    json.dump(out, open(f'{d}/components.json', 'w'), indent=1)
    return out


if __name__ == '__main__':
    for d in sys.argv[1:]:
        run(d)
        print(d)
