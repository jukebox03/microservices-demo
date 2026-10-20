#!/usr/bin/env python3
"""mk.py <group> [step ...] > manifest.yaml

Online Boutique on jet2 for the sidecar CPU-overhead ladder. <group> is a
deployment (what needs fresh pods); the steps are policy objects applied on top
of a running deployment (see STEPS). Every group uses the same layout:
frontend x6 round-robin over catalog x4, currency x2, recommendation x5, the
rest x1 (24 pods, ../k8sob/gen.py tcp). OB_N_CUR / OB_N_REC change the currency
and recommendation counts for every group (dpumesh then needs OB_LAYOUT, a
layout file that places the extra pods).

  nosidecar, nosidecar-trace       no mesh (-trace: app tracing at 1%)
  l5d-opaque, l5d, l5d-trace       Linkerd, sidecars injected by `linkerd inject --manual`
  istio-l4, istio, istio-trace     Istio (namespace injection; -l4: tcp- port names)
  dpumesh                          DPUMesh: no sidecar, the proxy on jet2's DPU (gen.py dpumesh)

-trace groups turn on OB's own OpenTelemetry tracing, parent-based 1% sampling,
to the collector at 10.99.0.240:4317 (otel.yaml); the l5d-trace proxies export
spans and access logs, the istio-trace ones get them from the Telemetry step."""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser('~')
GEN = os.path.join(HERE, '..', 'k8sob', 'gen.py')
NS = 'boutique'
OPAQUE = '3550,5000,5050,6379,7000,7070,8080,9555,50051'
COLLECTOR = '10.99.0.240:4317'
TRACE_ENV = {'ENABLE_TRACING': '1', 'COLLECTOR_SERVICE_ADDR': COLLECTOR, 'TRACE_SAMPLE_RATIO': '0.01',
             'OTEL_TRACES_SAMPLER': 'parentbased_traceidratio', 'OTEL_TRACES_SAMPLER_ARG': '0.01'}
L5D_TRACE_ENV = {'LINKERD2_PROXY_TRACE_PROTOCOL': 'opentelemetry',
                 'LINKERD2_PROXY_TRACE_SERVICE_NAME': 'linkerd-proxy',
                 'LINKERD2_PROXY_TRACE_COLLECTOR_SVC_ADDR': 'otel-collector.otel.svc.cluster.local:4317',
                 'LINKERD2_PROXY_TRACE_COLLECTOR_SVC_NAME': 'otel-collector.otel.serviceaccount.identity.linkerd.cluster.local',
                 'LINKERD2_PROXY_ACCESS_LOG': 'json'}
# backend kind -> (port, gRPC service); pods are <kind> or <kind>-<r>
KINDS = {'productcatalogservice': (3550, 'ProductCatalogService'), 'currencyservice': (7000, 'CurrencyService'),
         'cartservice': (7070, 'CartService'), 'shippingservice': (50051, 'ShippingService'),
         'adservice': (9555, 'AdService'), 'emailservice': (5000, 'EmailService'),
         'paymentservice': (50051, 'PaymentService'), 'recommendationservice': (8080, 'RecommendationService'),
         'checkoutservice': (5050, 'CheckoutService')}
GROUPS = {'nosidecar', 'nosidecar-trace', 'l5d-opaque', 'l5d', 'l5d-trace', 'istio-l4', 'istio', 'istio-trace', 'dpumesh'}


def kind_of(pod):
    k = pod.rsplit('-', 1)[0] if pod.rsplit('-', 1)[-1].isdigit() else pod
    return k if k in KINDS else None


def base(group):
    env = dict(os.environ, NODE='jet2', N_FE='6', FE_RR='1', N_CAT='4', N_CUR=os.environ.get('OB_N_CUR', '2'),
               N_REC=os.environ.get('OB_N_REC', '5'), DPUMESH_LIB=f'{HOME}/DPUMesh-main/build/lib')
    if group.endswith('-trace'):
        env['EXTRA_ENV'] = ','.join(f'{k}={v}' for k, v in TRACE_ENV.items())
    if group == 'dpumesh':
        # the same 24 processes over DPUMesh to jet2's DPU (PF1, host 0b:00.1),
        # host library of feature/dpa-mux (= main + DPA mux), 14 DPU workers
        env.update(W='14', LAYOUT=os.environ.get('OB_LAYOUT') or os.path.join(HERE, '..', 'dpumesh', 'layout14rr-fe6.txt'),
                   DPUMESH_LIB=f'{HOME}/DPUMesh/build/lib')
    out = subprocess.run([sys.executable, GEN, 'dpumesh' if group == 'dpumesh' else 'tcp'], env=env,
                         capture_output=True, text=True, check=True).stdout
    return [json.loads(d) for d in out.split('\n---\n') if d.strip()]


def manifest(group):
    docs = base(group)
    for d in docs:
        md = d['metadata']
        if d['kind'] == 'Pod':
            name = md['name']
            md['labels']['obtier'] = 'backend' if kind_of(name) else ('frontend' if name.startswith('frontend') else 'redis')
            if group == 'l5d-opaque':
                md.setdefault('annotations', {})['config.linkerd.io/opaque-ports'] = OPAQUE
        if d['kind'] == 'Service':
            if group == 'istio-l4':
                for p in d['spec']['ports']:
                    if not p['name'].startswith('tcp-'):
                        p['name'] = 'tcp-' + p['name']
            if group == 'l5d-opaque':
                md.setdefault('annotations', {})['config.linkerd.io/opaque-ports'] = OPAQUE
    if group.startswith('l5d'):
        raw = '\n---\n'.join(json.dumps(d) for d in docs)
        out = subprocess.run([f'{HOME}/.linkerd2/bin/linkerd', 'inject', '--manual', '-'], input=raw,
                             capture_output=True, text=True, check=True).stdout
        import yaml
        docs = [d for d in yaml.safe_load_all(out) if d]
        if group == 'l5d-trace':
            for d in docs:
                if d['kind'] != 'Pod':
                    continue
                for c in d['spec'].get('initContainers', []) + d['spec']['containers']:
                    if c['name'] == 'linkerd-proxy':
                        c['env'] += [{'name': k, 'value': v} for k, v in L5D_TRACE_ENV.items()]
    return docs


def backend_pods(docs):
    return sorted(d['metadata']['name'] for d in docs if d['kind'] == 'Pod' and kind_of(d['metadata']['name']))


def step_objects(step, pods):
    """Policy objects added on top of a running deployment."""
    by_kind = {}
    for p in pods:
        by_kind.setdefault(kind_of(p), []).append(p)
    o = []
    if step == 'l5d-authz':
        o.append({'apiVersion': 'policy.linkerd.io/v1alpha1', 'kind': 'MeshTLSAuthentication',
                  'metadata': {'name': 'boutique-mesh', 'namespace': NS},
                  'spec': {'identities': [f'*.{NS}.serviceaccount.identity.linkerd.cluster.local']}})
        for k, members in by_kind.items():
            port, svc = KINDS[k]
            o.append({'apiVersion': 'policy.linkerd.io/v1beta3', 'kind': 'Server', 'metadata': {'name': k, 'namespace': NS},
                      'spec': {'podSelector': {'matchExpressions': [{'key': 'app', 'operator': 'In', 'values': members}]},
                               'port': port}})
            o.append({'apiVersion': 'policy.linkerd.io/v1beta3', 'kind': 'HTTPRoute', 'metadata': {'name': k, 'namespace': NS},
                      'spec': {'parentRefs': [{'group': 'policy.linkerd.io', 'kind': 'Server', 'name': k}],
                               'rules': [{'matches': [{'path': {'type': 'PathPrefix', 'value': f'/hipstershop.{svc}/'}}]}]}})
            o.append({'apiVersion': 'policy.linkerd.io/v1alpha1', 'kind': 'AuthorizationPolicy', 'metadata': {'name': k, 'namespace': NS},
                      'spec': {'targetRef': {'group': 'policy.linkerd.io', 'kind': 'HTTPRoute', 'name': k},
                               'requiredAuthenticationRefs': [{'group': 'policy.linkerd.io', 'kind': 'MeshTLSAuthentication', 'name': 'boutique-mesh'}]}})
    elif step == 'l5d-traffic':
        # inbound local rate limit far above the load (never rejects), outbound
        # retries and request timeout on every backend Service (annotations, below)
        for k in by_kind:
            o.append({'apiVersion': 'policy.linkerd.io/v1alpha1', 'kind': 'HTTPLocalRateLimitPolicy', 'metadata': {'name': k, 'namespace': NS},
                      'spec': {'targetRef': {'group': 'policy.linkerd.io', 'kind': 'Server', 'name': k},
                               'total': {'requestsPerSecond': 1000000}}})
    elif step == 'istio-notls':
        o.append({'apiVersion': 'security.istio.io/v1', 'kind': 'PeerAuthentication', 'metadata': {'name': 'default', 'namespace': NS},
                  'spec': {'mtls': {'mode': 'DISABLE'}}})
        o.append({'apiVersion': 'networking.istio.io/v1', 'kind': 'DestinationRule', 'metadata': {'name': 'notls', 'namespace': NS},
                  'spec': {'host': f'*.{NS}.svc.cluster.local', 'trafficPolicy': {'tls': {'mode': 'DISABLE'}}}})
    elif step == 'istio-authz':
        for p in pods:
            svc = KINDS[kind_of(p)][1]
            o.append({'apiVersion': 'security.istio.io/v1', 'kind': 'AuthorizationPolicy', 'metadata': {'name': p, 'namespace': NS},
                      'spec': {'selector': {'matchLabels': {'app': p}}, 'action': 'ALLOW',
                               'rules': [{'from': [{'source': {'principals': [f'cluster.local/ns/{NS}/sa/default']}}],
                                          'to': [{'operation': {'paths': [f'/hipstershop.{svc}/*']}}]}]}})
    elif step == 'istio-traffic':
        o.append({'apiVersion': 'networking.istio.io/v1alpha3', 'kind': 'EnvoyFilter', 'metadata': {'name': 'local-ratelimit', 'namespace': NS},
                  'spec': {'workloadSelector': {'labels': {'obtier': 'backend'}},
                           'configPatches': [{'applyTo': 'HTTP_FILTER',
                                              'match': {'context': 'SIDECAR_INBOUND', 'listener': {'filterChain': {'filter': {
                                                  'name': 'envoy.filters.network.http_connection_manager',
                                                  'subFilter': {'name': 'envoy.filters.http.router'}}}}},
                                              'patch': {'operation': 'INSERT_BEFORE', 'value': {
                                                  'name': 'envoy.filters.http.local_ratelimit',
                                                  'typed_config': {'@type': 'type.googleapis.com/udpa.type.v1.TypedStruct',
                                                                   'type_url': 'type.googleapis.com/envoy.extensions.filters.http.local_ratelimit.v3.LocalRateLimit',
                                                                   'value': {'stat_prefix': 'http_local_rate_limiter',
                                                                             'token_bucket': {'max_tokens': 1000000, 'tokens_per_fill': 1000000, 'fill_interval': '1s'},
                                                                             'filter_enabled': {'runtime_key': 'lrl_enabled', 'default_value': {'numerator': 100, 'denominator': 'HUNDRED'}},
                                                                             'filter_enforced': {'runtime_key': 'lrl_enforced', 'default_value': {'numerator': 100, 'denominator': 'HUNDRED'}}}}}}}]}})
        for svc in services_of(pods):
            o.append({'apiVersion': 'networking.istio.io/v1', 'kind': 'VirtualService', 'metadata': {'name': svc, 'namespace': NS},
                      'spec': {'hosts': [svc], 'http': [{'route': [{'destination': {'host': svc}}], 'timeout': '10s',
                                                         'retries': {'attempts': 2, 'retryOn': 'unavailable'},
                                                         'fault': {'abort': {'percentage': {'value': 0.0}, 'httpStatus': 503}}}]}})
    elif step == 'istio-telemetry':
        o.append({'apiVersion': 'telemetry.istio.io/v1', 'kind': 'Telemetry', 'metadata': {'name': 'mesh', 'namespace': NS},
                  'spec': {'accessLogging': [{'providers': [{'name': 'envoy'}]}],
                           'tracing': [{'providers': [{'name': 'otel'}], 'randomSamplingPercentage': 1.0}]}})
    else:
        raise SystemExit(f'unknown step {step}')
    return o


def services_of(pods):
    # gen.py makes one Service per backend replica, named like the pod
    return pods


# Linkerd retries/timeouts are Service annotations (Linkerd >= 2.16)
L5D_TRAFFIC_ANNOTATIONS = {'retry.linkerd.io/http': '5xx', 'retry.linkerd.io/grpc': 'unavailable',
                           'retry.linkerd.io/limit': '2', 'timeout.linkerd.io/request': '10s'}

if __name__ == '__main__':
    group, steps = sys.argv[1], sys.argv[2:]
    assert group in GROUPS, group
    docs = manifest(group)
    if steps:  # only the step objects (the deployment is up already)
        pods = backend_pods(docs)
        docs = [x for s in steps for x in step_objects(s, pods)]
    print('\n---\n'.join(json.dumps(d) for d in docs))
