#!/usr/bin/env python3
"""classify.py POINT_DIR [...]: perf.txt.gz -> buckets.json

Splits the cycles of every boutique container (cgroup of the sample) into the
six buckets, separately for the app containers and the sidecars:

  kernel      any kernel frame at the leaf (syscalls, TCP/IP, loopback/veth,
              netfilter, softirq, scheduler, epoll) - with sub-buckets in kernel_sub
  mtls        TLS handshake and record crypto (rustls/aws-lc, BoringSSL)
  l7_parsing  HTTP/2 codec and HTTP stream handling (h2/hyper; nghttp2, HCM)
  l7_policy   routing, load balancing, retries/timeouts, rate limit, authz
  telemetry   metrics, tracing/spans, access log, Istio metadata exchange
  other       proxy runtime and I/O plumbing (tokio/mio, Envoy event loop,
              buffers), control plane

User samples are attributed by walking the call chain from the leaf: generic
frames (memcpy, the allocator, std/core, protobuf, absl) are skipped so their
cost goes to the first caller that belongs to a bucket. App containers are
split only into kernel and user (app_user), plus app_grpc for frames of the
app's own gRPC/HTTP2 library where symbols exist (Go, the grpcio C core)."""
import gzip, json, os, re, sys

KSUB = [('netfilter', r'^(nf_|ipt_|ip6t_|nft_|iptable_|xt_|__nf_|nf_conntrack|ipv4_conntrack|nf_nat)'),
        ('scheduler', r'^(__schedule|schedule|finish_task_switch|try_to_wake_up|ttwu_|pick_next_|enqueue_|dequeue_|update_curr|select_task_rq|psi_|__switch_to|context_switch|sched_)'),
        ('epoll_futex', r'^(ep_|do_epoll|__x64_sys_epoll|futex_|__futex|do_futex)'),
        ('net_stack', r'^(tcp_|__tcp|ip_|__ip_|ip6_|inet_|sock_|__sock|sk_|__sk_|skb_|__skb|kfree_skb|consume_skb|__dev_queue|dev_hard|dev_queue|net_rx|__netif|netif_|napi_|__napi|process_backlog|loopback_xmit|veth_|br_|__br|udp_|raw_|neigh_|dst_|fib_|rt_|__inet|release_sock|lock_sock|tcp4_|sock_def|__kfree_skb|validate_xmit|sch_direct|__qdisc|pfifo)'),
        ('syscall', r'^(entry_SYSCALL|do_syscall|syscall_exit|__x64_sys|x64_sys_call|__do_sys|ksys_|vfs_|do_writev|do_readv|do_iter|sock_write|sock_read|__sys_)'),
        ('memory', r'^(exc_page_fault|do_user_addr_fault|handle_mm_fault|__handle_mm|do_anonymous|clear_page|__alloc_pages|get_page_from|kmem_cache|__kmalloc|kmalloc|__slab|slab_|___slab|kfree|__free_pages|free_unref|page_|folio_|mmap|do_mmap|__mmap)'),
        ]
KGENERIC = r'^(copy_user|rep_movs|_copy_|copy_page|memcpy|memmove|memset|__memcpy|__memset|_raw_spin|raw_spin|native_queued|queued_spin|__rcu|rcu_|preempt|irq_|__irq|asm_|common_interrupt|sysvec|__sysvec|do_softirq|__do_softirq|handle_softirqs|__local_bh|local_bh|srso_|entry_|__entry|refcount|__refcount|mutex_|down_|up_)'

# Rules match the head of a symbol: the function's own path without generic
# arguments, impl traits or C++ parameters (see head()), so type parameters that
# name other crates do not decide the bucket.
LINKERD = [
    ('mtls', r'^(rustls|aws_lc_rs|aws_lc_sys|aws_lc_\w+|tokio_rustls|linkerd_meshtls\w*|linkerd_tls|linkerd_rustls|rustls_webpki|webpki|x509_parser|ring)\b|^(aws_lc_0_|_?aes_|aesni_|gcm_|ghash|x25519|ec_|ecp_|bn_|BN_|sha256_|sha512_|EVP_|CRYPTO_)'),
    ('telemetry', r'^(prometheus_client|linkerd_metrics|linkerd_http_metrics|linkerd_http_prom|linkerd_transport_metrics|linkerd_stack_metrics|linkerd_app_inbound::metrics|linkerd_app_outbound::metrics|linkerd_app_core::metrics|tracing_core|tracing_subscriber|tracing::span|tracing::dispatcher|tracing::|linkerd_tracing|linkerd_trace_context|linkerd_opentelemetry|opentelemetry\w*|linkerd_http_access_log|linkerd_proxy_tap)'),
    ('l7_policy', r'^(linkerd_app_inbound::policy|linkerd_proxy_server_policy|linkerd_server_policy|linkerd_http_route|linkerd_router|linkerd_app_outbound::http::(logical|concrete|retry|breaker|require_id_header)|linkerd_distribute|linkerd_proxy_balance\w*|linkerd_pool\w*|linkerd_proxy_client_policy|linkerd_http_retry|linkerd_retry|linkerd_http_stream_timeouts|linkerd_http_classify|linkerd_app_core::classify|linkerd_app_inbound::http::router|governor|linkerd_load_biaser|linkerd_ewma|hyper_balance|tower::balance|tower::load|tower::ready_cache)'),
    ('l7_parsing', r'^(h2|hyper|hyper_util|httparse|http|http_body\w*|linkerd_http_detect|linkerd_detect|linkerd_proxy_http|linkerd_http_box|linkerd_http_body_eos|linkerd_http_upgrade|linkerd_http_insert|linkerd_http_retain|linkerd_http_override_authority|linkerd_http_variant|linkerd_app_inbound::http|linkerd_app_outbound::http|linkerd_app_core::errors|linkerd_error_respond)\b'),
    ('other', r'^(tonic|prost|linkerd_proxy_identity_client|linkerd_tonic\w*|linkerd_service_profiles|linkerd_proxy_api_resolve|linkerd_app_core::control|hickory\w*|linkerd_dns|linkerd_app_admin|tokio|mio|tower|linkerd_\w+|linkerd2_proxy)\b'),
]
# skipped: their cost goes to the caller
LGENERIC = r'^(\w+@plt|bcmp|core|alloc|std|bytes|hashbrown|indexmap|smallvec|parking_lot\w*|lock_api|crossbeam\w*|futures\w*|pin_project\w*|slab|either|arc_swap|once_cell|tokio::sync|tokio::io|tokio_util|tower::util|tower_service|tower_layer|linkerd_stack|linkerd_stack_tracing|linkerd_io|tracing::instrument|tikv_jemalloc\w*|_rjem\w*|je_\w*|__memmove\w*|__memcpy\w*|__memset\w*|__memcmp\w*|memcpy|memmove|memset|memcmp|malloc|free|realloc|calloc|_int_\w+|cfree|__libc_\w+|__vdso\w*|clock_gettime\w*|_ZN4core|_ZN5alloc|_ZN3std)\b'

ENVOY = [
    ('mtls', r'^(bssl::|SSL_|ssl_|tls13_|tls_|aes_|aesni_|gcm_|ghash|ecp_nistz|fiat_|x25519|X25519|rsaz_|bn_|BN_|EVP_|CRYPTO_|sha256_block|sha512_block|chacha|ChaCha|poly1305|ec_|EC_|RSA_|rsa_|x509|X509|Envoy::Extensions::TransportSockets::Tls|Envoy::Ssl::|Envoy::Tls::)'),
    ('telemetry', r'^(Envoy::Stats::|Envoy::Extensions::HttpFilters::IstioStats|Envoy::Extensions::Filters::Http::IstioStats|Envoy::Extensions::\w+::IstioStats|Envoy::Extensions::HttpFilters::GrpcStats|Envoy::Grpc::ContextImpl|Envoy::Grpc::FrameInspector|Envoy::Tracing::|Envoy::Extensions::Tracers|opentelemetry|Envoy::AccessLog|Envoy::Extensions::AccessLoggers|Envoy::Formatter|Envoy::Extensions::HttpFilters::PeerMetadata|Envoy::Extensions::\w+::PeerMetadata|Istio::|Envoy::Extensions::Filters::Common::Expr|Envoy::Extensions::RequestId|Envoy::Tcp::MetadataExchange|Envoy::Extensions::\w+::MetadataExchange|hist_)'),
    ('l7_policy', r'^(Envoy::Router::|Envoy::Upstream::|Envoy::ConnectionPool|Envoy::Http::MultiplexedActiveClient|Envoy::Http::ConnPool|Envoy::Http::Http2::ConnPool|Envoy::Http::FixedHttpConnPool|Envoy::Extensions::LoadBalancingPolicies|Envoy::Extensions::HttpFilters::RBACFilter|Envoy::Extensions::Filters::Common::RBAC|Envoy::Extensions::HttpFilters::LocalRateLimit|Envoy::Extensions::Filters::Common::LocalRateLimit|Envoy::Extensions::HttpFilters::Fault|Envoy::Extensions::HttpFilters::Cors|Envoy::Http::Alpn|Envoy::Extensions::Retry)'),
    ('l7_parsing', r'^(nghttp2_|http2::|spdy::|llhttp|http_parser|Envoy::Http::)'),
    ('other', r'^(Envoy::|event_|evmap|epoll_dispatch|evutil|tcmalloc|TCMalloc)'),
]
EGENERIC = r'^(\w+@plt|bcmp|decltype|std::|absl::|google::protobuf|__memmove|__memcpy|__memset|__memcmp|memcpy|memmove|memset|memcmp|tcmalloc::|TCMalloc|operator new|operator delete|malloc|free|realloc|calloc|_int_|__libc_|re2::|fmt::|spdlog::|Envoy::Buffer::|Envoy::Random::|__vdso|clock_gettime)'

GOGRPC = r'^(google\.golang\.org/grpc|golang\.org/x/net/http2|google\.golang\.org/protobuf|grpc_core::|grpc_chttp2|grpc_|_grpc_|hpack|cython)'


def _legacy_demangle(s):
    # _ZN4core3ptr13drop_in_place... -> core::ptr::drop_in_place (enough for a head)
    i, parts = 3, []
    while i < len(s) and s[i].isdigit():
        j = i
        while j < len(s) and s[j].isdigit():
            j += 1
        n = int(s[i:j]); parts.append(s[j:j + n]); i = j + n
        if len(parts) >= 3:
            break
    return '::'.join(parts)


def _drop_generics(s):
    out, depth = [], 0
    for ch in s:
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return ''.join(out)


def head(sym):
    s = re.sub(r'\+0x[0-9a-f]+$', '', sym)
    for p in ('non-virtual thunk to ', 'virtual thunk to '):
        if s.startswith(p):
            s = s[len(p):]
    if s.startswith('_ZN'):
        s = _legacy_demangle(s)
    if s.startswith('<'):
        # <Type<..> as Trait<..>>::method -> Type
        depth, k = 0, 1
        for k in range(1, len(s)):
            if s[k] == '<':
                depth += 1
            elif s[k] == '>':
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and s.startswith(' as ', k):
                break
        s = s[1:k]
    s = s.split('$')[0]
    # C++: drop parameters (first '(' outside template brackets)
    depth = 0
    for k, ch in enumerate(s):
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
        elif ch == '(' and depth == 0:
            s = s[:k]
            break
    s = _drop_generics(s)
    if s.startswith(('&', '*')):
        s = s.lstrip('&*').lstrip('mut ').lstrip()
    return s.strip()


HDR = re.compile(r'^(?P<comm>.+?)\s+(?P<pid>\d+)/(?P<tid>\d+)\s+\[(?P<cpu>\d+)\]\s+(?P<time>[\d.]+):\s+(?P<period>\d+)\s*(?P<rest>.*)$')
FRAME = re.compile(r'^\s+([0-9a-f]+)\s+(.*?)\s+\((.*)\)$')


def strip(sym):
    return head(sym)


def ksub(frames):
    for addr, sym, dso in frames:
        if not dso.startswith('[kernel'):
            break
        s = strip(sym)
        if re.match(KGENERIC, s):
            continue
        for name, pat in KSUB:
            if re.match(pat, s):
                return name
    return 'kernel_other'


# checked before the generic skip: generic-looking crates whose code is a bucket's
OVERRIDE = [('telemetry', r'^(linkerd_io::sensor|linkerd_transport_metrics)')]


def user_bucket(frames, rules, generic):
    for addr, sym, dso in frames:
        if dso.startswith('[kernel'):
            continue
        s = strip(sym)
        if s in ('[unknown]', '', '_'):
            continue
        hit = next((n for n, pat in OVERRIDE if re.match(pat, s)), None)
        if hit:
            return hit
        if re.match(generic, s):
            continue
        for name, pat in rules:
            if re.match(pat, s):
                return name
    return 'other'


def classify(d):
    meta = json.load(open(f'{d}/meta.json'))
    # cgroup path suffix -> (role, mesh proxy kind)
    by_scope = {}
    for cid, c in meta['containers'].items():
        by_scope[os.path.basename(c['cgroup'])] = c
    mesh = meta.get('mesh')
    out = {'app': {}, 'sidecar': {}, 'app_ksub': {}, 'sidecar_ksub': {}, 'unmatched_cycles': 0, 'samples': 0,
           'sidecar_top': {}}
    cur = None

    def flush(s):
        if not s:
            return
        hdr, frames = s
        scope = None
        m = re.search(r'(cri-containerd-[0-9a-f]+\.scope)', hdr['rest'])
        if m:
            scope = m.group(1)
        c = by_scope.get(scope)
        per = int(hdr['period'])
        out['samples'] += 1
        if not c:
            out['unmatched_cycles'] += per
            # network softirq run on an idle CPU or by ksoftirqd: no pod's cgroup
            # gets it, but it is the pods' traffic (veth, bridge, netfilter)
            if re.match(r'(swapper|ksoftirqd)', hdr['comm']) and any(
                    re.match(KSUB[0][1] + '|' + KSUB[3][1], strip(sym)) for _, sym, dso in frames if dso.startswith('[kernel')):
                out['host_net_cycles'] = out.get('host_net_cycles', 0) + per
            return
        role = 'sidecar' if c['role'] == 'sidecar' else 'app'
        leaf_kernel = bool(frames) and frames[0][2].startswith('[kernel')
        if leaf_kernel:
            b = 'kernel'
            ks = ksub(frames)
            out[f'{role}_ksub'][ks] = out[f'{role}_ksub'].get(ks, 0) + per
        elif role == 'sidecar':
            rules, generic = (ENVOY, EGENERIC) if mesh == 'istio' else (LINKERD, LGENERIC)
            b = user_bucket(frames, rules, generic)
            leaf = strip(frames[0][1]) if frames else '?'
            k = f'{b}|{leaf[:90]}'
            out['sidecar_top'][k] = out['sidecar_top'].get(k, 0) + per
        else:
            b = 'app_user'
            for addr, sym, dso in frames:
                s = strip(sym)
                if re.match(GOGRPC, s):
                    b = 'app_grpc'
                    break
        out[role][b] = out[role].get(b, 0) + per

    with gzip.open(f'{d}/perf.txt.gz', 'rt', errors='replace') as f:
        for line in f:
            if not line.strip():
                flush(cur); cur = None
                continue
            m = HDR.match(line)
            if m and not line.startswith(('\t', ' ')):
                flush(cur)
                cur = (m.groupdict(), [])
                continue
            fm = FRAME.match(line)
            if fm and cur:
                cur[1].append((fm.group(1), fm.group(2), fm.group(3)))
        flush(cur)
    top = sorted(out['sidecar_top'].items(), key=lambda x: -x[1])[:60]
    out['sidecar_top'] = dict(top)
    json.dump(out, open(f'{d}/buckets.json', 'w'), indent=1)
    return out


if __name__ == '__main__':
    for d in sys.argv[1:]:
        o = classify(d)
        tot = lambda r: sum(o[r].values()) or 1
        print(d, {r: {k: round(v / tot(r), 3) for k, v in sorted(o[r].items())} for r in ('app', 'sidecar')},
              'unmatched', round(o['unmatched_cycles'] / max(1, o['unmatched_cycles'] + tot('app') + tot('sidecar')), 3))
