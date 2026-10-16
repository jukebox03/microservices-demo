# 실험 1 기준표 (2026-10-14 합의, 완료 보고 때 다시 제시)

## 1. 큰 묶음 6개 (논문 그림의 범주)

| 묶음 | 핵심 | Linkerd 기본 | Istio 기본 |
|---|---|---|---|
| Kernel / IPC | iptables redirect, app↔sidecar loopback 왕복, syscall·epoll·context switch | 켜짐 (끌 수 없음) | 켜짐 (끌 수 없음) |
| mTLS | 연결당 handshake(gRPC는 장수명이라 작음), byte당 암복호 | 항상 켜짐 | 켜짐 (auto mTLS) |
| L7 protocol parsing | sidecar마다 HTTP/2를 종단하고 재생성(HPACK) | 켜짐 | 켜짐 |
| L7 policy enforcement | 인가(authz), 라우팅·LB·retry·timeout·rate limit | 인가가 요청마다 돎 (정책 없어도) | retry 켜짐, 인가는 정책이 있을 때만 |
| Telemetry | 요청당 metrics, tracing, access log | metrics 켜짐 (끌 수 없음) | metrics 켜짐 |
| Other | 프록시 런타임 (이벤트 루프, 메모리, 버퍼) | — | — |

## 2. 사용자가 걸 수 있는 옵션

| 묶음 | Linkerd | Istio |
|---|---|---|
| mTLS | 끌 수 없음 | PeerAuthentication STRICT / PERMISSIVE / DISABLE |
| L7 parsing | opaque-ports → L4 (파싱 없음, mTLS 유지) | 포트 이름 `tcp-` → L4, `grpc`/`http` → L7 |
| 인가 | Server + AuthorizationPolicy (route 단위 가능), default-inbound-policy | AuthorizationPolicy (ALLOW/DENY/CUSTOM), RequestAuthentication(JWT) |
| rate limit | HTTPLocalRateLimitPolicy | local rate limit (EnvoyFilter), global rate limit (외부 서비스) |
| 라우팅·회복성 | HTTPRoute/GRPCRoute(가중치 분배, header 수정), retry·timeout annotation, circuit breaking(failure accrual) | VirtualService(라우팅, retry, timeout, fault injection, mirroring), DestinationRule(LB, connection pool, outlier detection) |
| telemetry | tracing, access log | Telemetry API: metrics on/off, tracing sampling, access log |
| 확장 filter | 없음 | WasmPlugin, Lua (EnvoyFilter) |

## 3. 측정 사다리와 구성 ID

| 단계 | Linkerd | Istio | 늘어나는 묶음 |
|---|---|---|---|
| 0 | `N0-nosidecar` | (공통) | 기준 |
| 1 | `L1-opaque` (L4 + mTLS) | `I1-l4` (`tcp-` 포트 + mTLS) | Kernel/IPC + mTLS |
| 2 | `L2-l7` | `I2-l7` | + parsing, 기본 policy, 기본 telemetry |
| 3 | `L3-authz` (Server + HTTPRoute + AuthorizationPolicy, MeshTLSAuthentication) | `I3-authz` (AuthorizationPolicy ALLOW: principal + gRPC path) | + 인가 |
| 4 | `L4-traffic` (+ HTTPLocalRateLimitPolicy 1M rps, retry 2회, timeout 10 s) | `I4-traffic` (+ local rate limit 1M, VirtualService retry 2회·timeout 10 s·fault 0%) | + traffic policy |
| 5 | `L5-telemetry` (+ proxy tracing + access log, 앱 tracing 1%) | `I5-telemetry` (+ Telemetry: access log, tracing 1%, 앱 tracing 1%) | + telemetry 확장 |
| (Istio만) | — | `I2n-l7-notls` (I2 + mTLS DISABLE) | mTLS 몫 |
| (5단계 기준) | `N0t-nosidecar-trace` (앱 tracing 1%, sidecar 없음) | (공통) | 앱 쪽 tracing 몫 |

- tracing sampling 1%: Istio 기본값이고 Hindsight(NSDI '23)가 비교 기준으로 쓴 Jaeger 1% head sampling과 같다. Dapper는 약 0.1%(1/1024).
- 기능은 트래픽을 바꾸지 않게 설정했다: rate limit 거부 0, fault 0%, timeout 10 s.
