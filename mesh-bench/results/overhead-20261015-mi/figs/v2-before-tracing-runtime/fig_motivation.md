# fig_motivation: 항목 설명

그림: `fig_motivation.png` / `fig_motivation.pdf` (스크립트 `mesh-bench/overhead/plot_motivation.py`)

## 공통 조건

- **측정 대상:** jet2(Xeon 6515P, 16 코어 / 32 vCPU, SMT on, turbo off, 2.3 GHz 고정)에 Online Boutique pod 24개를 띄웠다.
  - 배치는 frontend 6, productcatalog 4, currency 2, recommendation 5, 나머지 1개씩이고, 모든 구성이 같다.
- **부하:** jet1의 k6가 open-loop로 1,500 HTTP req/s를 건다. 요청 혼합은 upstream locustfile 비중을 따른다.
  - 측정점 하나는 20 s다: warm 2 s, CPU 측정 2.5–10 s, perf 10–14.5 s, bpftrace 15–19 s.
  - 모든 측정점은 1회씩이고, 보정은 하지 않았다.
- **vCPU:** 논리 CPU 단위의 CPU 시간이다(최대 32). cgroup의 `usage_usec` 증가량을 측정 구간 길이로 나눈 값이다.
  - 앱 컨테이너와 sidecar 컨테이너는 각자의 cgroup으로 구분한다.
- **분해 방법:** 각 컨테이너의 vCPU를 같은 측정점의 perf 샘플 비율로 나눈다.
  - perf는 `cycles`, 499 Hz, LBR call stack, `--all-cgroups`로 잰다.
  - 샘플은 기록된 cgroup으로 컨테이너에 귀속한다.
- **구성 이름**

| 그림의 이름 | 내용 |
|---|---|
| No sidecar | 메시 없음. 서비스끼리 ClusterIP로 직접 통신 |
| Linkerd L4 | Linkerd edge-26.8.4, 모든 서비스 포트를 opaque로 지정. sidecar가 HTTP/2를 해석하지 않고 TCP로 중계. mTLS 유지 |
| Linkerd L7 | Linkerd 기본. sidecar가 HTTP/2를 종단하고 다시 만듦. mTLS, 기본 인가, 기본 metrics |
| Istio L4 | Istio 1.31.1, 서비스 포트 이름을 `tcp-`로 해서 TCP 프록시(tcp_proxy). mTLS 유지 |
| Istio L7 | Istio 기본(포트 이름 `grpc`/`http`). HTTP/2 종단, auto mTLS, 기본 filter(istio.stats 등) |

두 메시 모두 sidecar worker는 1개다(Linkerd `PROXY_CORES=1`, Istio `concurrency: 1`).

---

## (a) Host CPU

막대 하나가 구성 하나다. 높이는 그 구성에서 앱 컨테이너 24개와 sidecar 컨테이너(메시 구성만)가 쓴 vCPU의 합이다. 막대 위 숫자는 합계이고, 괄호는 no-sidecar 대비 증가율이다.

| 항목 | 정의 |
|---|---|
| App kernel | 앱 컨테이너 cgroup에서 perf 샘플의 맨 끝(leaf) 함수가 커널인 몫 |
| App user | 앱 컨테이너 cgroup에서 leaf가 user 영역인 몫 |
| Sidecar kernel | sidecar 컨테이너(linkerd-proxy / istio-proxy, pilot-agent 포함)에서 leaf가 커널인 몫 |
| Sidecar user | sidecar 컨테이너에서 leaf가 user 영역인 몫. 안의 구성은 (c)에 있음 |

커널 몫에는 syscall, TCP/IP(loopback, veth, bridge), netfilter(iptables redirect), 스케줄러, epoll/futex가 들어간다. 그 task가 실행 중일 때 처리된 softirq도 들어간다.

**주의:** 같은 부하인데 앱 CPU(App kernel + App user)가 메시 구성에서 줄어든다.
- 이유는 (b)와 (e)에 있다.
- 비교는 합계(앱 + sidecar)로 해야 한다.

---

## (b) Sidecar coalesces the app's traffic

sidecar가 있을 때 앱이 요청을 받고 보내는 방식이 어떻게 바뀌는지 보여 준다. 세 지표 모두 HTTP 요청 하나당 값이다. 처리량은 k6가 측정 구간에 받은 응답 수 ÷ 13 s다.

| 항목 | 정의 |
|---|---|
| App syscalls per request | 앱 컨테이너 cgroup의 모든 syscall 진입 횟수(`raw_syscalls:sys_enter`, bpftrace, 4 s) ÷ 요청 수 |
| App wakeups per request | 앱 컨테이너 모든 스레드의 자발적 context switch 증가량(`/proc/<tid>/status`의 `voluntary_ctxt_switches`, CPU 측정 구간) ÷ 요청 수. 자발적 context switch는 스레드가 기다리려고 CPU를 내놓은 횟수, 즉 나중에 깨어나야 하는 횟수 |
| Pod-to-pod packets per request | 모든 pod network namespace의 `eth0` rx+tx 패킷 증가량 ÷ 2 ÷ 요청 수. pod 사이(sidecar 사이 포함) 패킷 수 |

| 요청당 | No sidecar | Linkerd L4 | Linkerd L7 | Istio L4 | Istio L7 |
|---|---:|---:|---:|---:|---:|
| 앱 syscall | 936 | 803 | 661 | 742 | 614 |
| 앱 깨어남 | 200 | 183 | 153 | 172 | 142 |
| pod 간 패킷 | 59 | 56 | 51 | 54 | 25 |

**해석**
- L7 sidecar는 HTTP/2를 종단한다. 그래서 여러 앱 연결에서 온 요청을 목적지 endpoint별 연결 하나에 다중화하고, 한 번에 모아 쓴다.
- 받는 쪽 앱에도 inbound sidecar 하나가 연결 하나로 요청을 묶어서 넘긴다. 앱이 요청당 덜 깨어나고, syscall과 패킷도 줄어든다.
- L4 sidecar는 바이트를 오는 대로 중계해서 이 효과가 작다.
- 연결 수 자체는 기록하지 않았다. 연결을 모아 준 결과로 나타나는 지표다.

---

## (c) Inside the sidecar

sidecar 컨테이너의 vCPU를 여섯 묶음으로 나눈 값이다. 같은 메시의 L4와 L7을 위아래로 붙였다. 막대 끝의 숫자는 sidecar vCPU 합계다.

**분류 방법**
- 커널 leaf는 모두 kernel/IPC다.
- user 샘플은 call stack을 leaf에서 위로 거슬러 올라가며, 처음 만나는 "의미 있는" 함수로 묶음을 정한다.
- memcpy, 메모리 할당자, std/core, protobuf 같은 공용 함수는 건너뛰어 호출한 쪽에 귀속한다.
- 규칙은 `mesh-bench/overhead/classify.py`에 있다.

| 항목 | 내용 | Linkerd(Rust)에서 해당하는 코드 | Istio(Envoy, C++)에서 해당하는 코드 |
|---|---|---|---|
| kernel / IPC | sidecar 문맥의 커널 시간 | syscall, loopback·veth TCP/IP, iptables NAT/conntrack, softirq, 스케줄러, epoll | 같음 |
| mTLS | TLS handshake와 레코드 암복호 | rustls, aws-lc-rs(AES-GCM 등), tokio-rustls, linkerd_meshtls, linkerd_tls | BoringSSL(bssl, SSL_*, aes/gcm), TransportSockets::Tls |
| L7 parsing | HTTP/2 종단과 재생성, 요청 처리 틀 | h2, hyper, http, linkerd_proxy_http, linkerd_http_detect, 앱 inbound/outbound HTTP 스택 | nghttp2, http2 adapter, Envoy::Http(codec, connection manager, header map, filter manager) |
| L7 policy | 인가와 트래픽 정책 | 인가(linkerd_app_inbound::policy, server_policy), route 매칭, 백엔드 분배, P2C/PeakEWMA LB, retry, timeout, 응답 분류, rate limit | Router, Upstream(LB, 연결 풀), RBAC, local rate limit, fault, cors, alpn, retry |
| telemetry | metrics, tracing, access log | prometheus_client, linkerd_metrics, 요청·바이트 카운터, tracing span, trace context, OpenTelemetry, access log, tap | Envoy::Stats, istio.stats, grpc_stats, tracer, access logger, peer metadata 교환, request id |
| runtime | 프록시 런타임과 나머지 | tokio, mio, tower/linkerd_stack, control plane 클라이언트(tonic, prost) | 이벤트 루프(dispatcher), 네트워크 연결·버퍼, tcmalloc, 기타 Envoy 코드 |

| sidecar vCPU | 합계 | kernel/IPC | mTLS | L7 parsing | L7 policy | telemetry | runtime |
|---|---:|---:|---:|---:|---:|---:|---:|
| Linkerd L4 | 5.0 | 3.5 | 0.4 | 0 | 0.02 | 0.4 | 0.8 |
| Linkerd L7 | 8.6 | 2.8 | 0.3 | 2.4 | 0.4 | 1.4 | 1.4 |
| Istio L4 | 5.9 | 3.5 | 0.7 | 0 | 0 | 0.05 | 1.6 |
| Istio L7 | 10.8 | 2.1 | 0.5 | 3.6 | 1.1 | 1.1 | 2.4 |

L4에서 L7로 가면 kernel/IPC가 줄어든다. (b)와 같은 이유로, L7 sidecar는 요청을 묶어서 syscall, 깨어남, 패킷이 적다. 요청당 sidecar syscall은 Linkerd 252 → 177, Istio 424 → 225회다.

---

## (d) Latency, one request outstanding

- **측정:** k6 VU 1개가 frontend-1에 locustfile 혼합 요청을 쉬지 않고 하나씩 보낸다. 동시에 처리 중인 요청은 항상 1개다(MeshInsight의 latency 측정 방식). warm 2 s 뒤 13 s를 쟀다.
- **mean:** HTTP 요청 하나의 왕복 시간 평균(ms).
- **p99:** 99번째 백분위수(ms).
- **해석:** 경합이 없는 상태에서 sidecar가 요청마다 더하는 지연이다. HTTP 요청 하나가 서비스 사이 gRPC 약 10번과 sidecar 통과 약 20번을 거친다.

---

## (e) Inside the app containers

앱 컨테이너(no-sidecar, Linkerd L7, Istio L7)의 vCPU를 코드 종류로 나눈 값이다. 막대 위 숫자는 앱 vCPU 합계다. Business logic은 막대 맨 아래에 두었고, 세 구성의 값이 거의 같아 옆에 평균(≈0.45)으로 표시했다.

**분류 방법** (`mesh-bench/overhead/classify_app.py`, 2026-10-15 수정판)
- 서비스마다 perf가 이름을 풀 수 있는 정도가 다르다.
  - Go: 함수 이름이 다 풀린다.
  - Python: gRPC C-core와 protobuf가 별도 라이브러리라 구분된다. Python 코드 자체는 인터프리터 안에서 돈다.
  - Node, Java, .NET: 런타임 바이너리(V8 내장 함수·GC, libjvm, libcoreclr)는 구분되지만, JIT으로 만든 코드는 이름이 없다.
- 샘플마다 call stack을 leaf에서 위로 거슬러 올라가며, 아래 다섯 묶음 중 하나에 속하는 첫 프레임으로 묶음을 정한다.
- **라이브러리 코드는 호출한 쪽에 귀속한다.** 대상은 다음과 같다.
  - Go 표준 라이브러리: context, reflect, time, strings, text/html template, encoding/json 등
  - Go 제3자 라이브러리: logrus, gorilla/mux, uuid 등
  - Go 런타임 도우미: 할당, 복사, map
  - libc, libstdc++
  - 예: gRPC가 부른 `context.Value`는 RPC stack이고, frontend 핸들러가 부른 템플릿 렌더링은 Business logic이다.
- **스택이 잘린 경우:** LBR 깊이가 모자라 Go 라이브러리 코드에서 체인이 끝나면 business로 둔다. 확인해 보니 거의 다 frontend 핸들러 아래의 깊은 `text/template` 재귀였다.

| 항목 | 정의 | 포함되는 코드 |
|---|---|---|
| Business logic | 앱 자신의 코드와, 앱 코드가 부른 라이브러리 | Go 서비스의 OB 코드(`main`, OB 패키지. 단 `genproto`는 제외)와 그 코드가 부른 표준·제3자 라이브러리(템플릿 렌더링, JSON, 로깅 등), Redis 서버 코드 |
| Kernel | leaf가 커널 | 앱의 syscall, TCP/IP, softirq, 스케줄러, epoll/futex |
| RPC stack (gRPC, HTTP/2, protobuf) | 앱 자신의 RPC와 네트워크 계층, 그리고 이 계층이 부른 라이브러리 | Go: grpc, x/net/http2, protobuf, OB `genproto`(생성된 protobuf 코드), net/http(frontend의 HTTP 서버), net, internal/poll, otel 래퍼 / Python: cygrpc(gRPC C-core), protobuf / Node: http2, nghttp2, libuv / .NET: System.Native(소켓) / Java: nio, net |
| Runtime (GC, scheduler, VM) | 언어 런타임 서비스 | Go: GC, 스케줄러, netpoll / Node: V8 GC / Java: libjvm / .NET: libcoreclr / Python: 메모리 관리 |
| JIT / interpreted code | 앱 코드지만 어느 함수인지 perf가 모르는 몫 | Node·Java·.NET의 JIT 코드와 V8 내장 함수, CPython 인터프리터 루프, Go 서비스의 주소를 못 푼 샘플. 이 언어들은 비즈니스 로직과 RPC 처리(grpc-js, Netty·grpc-java, Kestrel·Grpc.AspNetCore, gRPC의 Python 계층)가 함께 들어 있음 |

| 앱 vCPU | No sidecar | Linkerd L7 | Istio L7 | 변화 |
|---|---:|---:|---:|---:|
| Business logic | 0.45 | 0.47 | 0.43 | +4% / −3% (약 0.45로 같음) |
| Kernel | 5.59 | 3.63 | 3.00 | −35% / −46% |
| RPC stack | 3.40 | 3.00 | 2.55 | −12% / −25% |
| Runtime | 3.14 | 2.30 | 2.07 | −27% / −34% |
| JIT / interpreted code | 2.78 | 2.23 | 1.98 | −20% / −29% |
| 합계 | 15.36 | 11.63 | 10.03 | −24% / −35% |

**이전 분류(v1)에서 바뀐 것.** v1은 "이름이 있고 RPC·runtime 목록에 없으면 business"였다. 그래서 다음 몫이 business로 잡혔다.
- gRPC나 HTTP 코드가 부른 Go 표준 라이브러리: gRPC metadata와 otel의 `context.Value`, 직렬화 경로의 `reflect`, hpack 타입 해시 등
- Python·Node의 libc `malloc`

수정판에서 이 몫(0.37–0.41 vCPU)은 대부분 RPC stack(0.33–0.36)으로, 나머지는 JIT / interpreted code·runtime으로 옮겨 갔다. Business는 0.85 / 0.87 / 0.81에서 0.45 / 0.47 / 0.43으로 줄었고, 다른 묶음은 ±0.03 vCPU 안에서 그대로다. v1의 분류기, 결과, 그림은 `v1-classify/`에 보관했다.

### Business logic과 JIT / interpreted code를 나누는 기준

perf는 샘플마다 CPU가 실행 중이던 명령어 주소를 기록하고, 그 주소가 속한 파일의 심볼 테이블에서 함수 이름을 찾는다.

- **함수 이름을 알 수 있는 코드:** 이름으로 어떤 코드인지 알 수 있다.
  - Go 바이너리는 심볼 테이블을 담고 있어서 `main.(*frontendServer).homeHandler`, `text/template.(*state).walk`처럼 나온다.
  - Redis(C)도 `readQueryFromClient`처럼 나온다.
  - 그래서 Business logic은 사실상 Go 서비스와 Redis에서만 셀 수 있다.
- **JIT / interpreted code:** 앱 코드인 것은 확실하지만 어느 함수인지 perf가 모르는 몫이다. 원인은 네 가지다.
  1. **JIT 코드(Node V8, Java JVM, .NET CLR):** 런타임이 실행 중에 기계어를 만들어 익명 메모리에 둔다. 디스크 파일이 없어서 perf는 주소만 본다(`[unknown] (perf-<pid>.map)`). 이번 측정에서는 JIT 심볼 맵(Node `--perf-basic-prof`, Java perf-map-agent, .NET `DOTNET_PerfMapEnabled=1`)을 켜지 않았다.
  2. **V8 내장 함수**(`Builtins_Call_ReceiverIsAny`, `Builtins_KeyedLoadIC_Megamorphic` 등): 이름은 있지만, 모든 JS 코드가 함께 쓰는 호출·속성 접근 장치다. 어느 JS 함수의 일인지는 알 수 없다.
  3. **CPython 인터프리터**(`_PyEval_EvalFrameDefault`, `_PyFunction_Vectorcall`, python3.12 안의 이름 없는 내부 함수): 인터프리터 함수 이름만 보이고, 어떤 Python 함수의 bytecode를 실행 중인지는 perf가 모른다.
  4. **Go 서비스의 `[unknown]`:** 어떤 파일에도 매핑하지 못한 주소다. 각 Go 서비스 CPU의 3–7%다.

**두 막대의 서비스 구성** (각 막대 vCPU 안에서의 비율, No sidecar)

| 막대 | 구성 |
|---|---|
| Business logic 0.45 | frontend(Go) 86%, redis-cart 10%, 나머지 Go 서비스 4% |
| JIT / interpreted code 2.78 | recommendation(Python) 29%, currency(Node) 27%, cart(.NET) 14%, ad(Java) 13%, frontend(Go) 8%, productcatalog(Go) 6%, 나머지 4% |

### 비즈니스 로직이 이렇게 작은 이유

**서비스별 앱 vCPU** (No sidecar, 1,500 rps; 컨테이너 cgroup vCPU를 perf 비율로 나눈 값)

| 서비스 (언어) | 요청 하나에서 하는 일 | vCPU | business | kernel | RPC | runtime | JIT / interp. |
|---|---|---:|---:|---:|---:|---:|---:|
| frontend (Go) | HTTP 처리, 백엔드 3–8개 호출, HTML 템플릿 렌더링 | 6.03 | 0.38 | 2.29 | 1.53 | 1.60 | 0.23 |
| productcatalog (Go) | 메모리의 상품 9개 목록 반환·ID 검색 | 3.12 | 0.01 | 1.39 | 0.82 | 0.76 | 0.15 |
| recommendation (Python) | 상품 목록을 받아 최대 5개 무작위 선택 | 2.20 | 0 | 0.55 | 0.77 | 0.09 | 0.80 |
| cart (.NET) | Redis get/set | 1.44 | 0 | 0.62 | 0.02 | 0.42 | 0.38 |
| currency (Node) | 고정 환율표로 곱셈 | 1.18 | 0 | 0.27 | 0.12 | 0.03 | 0.75 |
| ad (Java) | 카테고리별 광고 무작위 선택 | 0.67 | 0 | 0.20 | 0.01 | 0.13 | 0.35 |
| checkout, shipping, email, payment, redis | 결제 흐름에서만 호출, 고정 견적·카드 검증 등 | 0.71 | 0.06 | 0.27 | 0.15 | 0.12 | 0.11 |
| 합계 | | 15.36 | 0.45 | 5.59 | 3.40 | 3.14 | 2.78 |

Python, Node, .NET, Java 서비스의 business가 0인 것은 비즈니스 로직이 없어서가 아니다. 그 코드가 JIT / interpreted code 안에 있어서 셀 수 없기 때문이다.

**작은 이유**
- Online Boutique 서비스는 요청 하나에서 하는 일이 거의 없다. 실제 계산이라 할 만한 것은 frontend의 HTML 템플릿 렌더링 정도다.
- 반면 HTTP 요청 하나가 서비스 사이 gRPC를 약 10번 부른다. 호출마다 양쪽에서 커널 TCP, gRPC·HTTP/2, protobuf, 런타임 비용을 낸다.
  - 예를 들어 productcatalog는 3.1 vCPU를 쓰지만 business는 0.01 vCPU다. 나머지는 상품 목록을 주고받는 비용이다.
- 이름이 다 풀리는 Go 서비스만 보면 business 비율은 다음과 같다.
  - frontend: 0.38 vCPU(6%)
  - productcatalog: 0.2%

**전체 범위**
- 하한: 이름으로 확인된 business 0.45 vCPU다. 앱 CPU의 3%다.
- 상한: JIT / interpreted code 2.78을 모두 비즈니스로 쳐서 3.2 vCPU다. 앱 CPU의 21%다.
  - JIT / interpreted code 안에는 grpc-js, gRPC의 Python 계층, Netty, Kestrel 같은 RPC 코드도 들어 있으므로 실제 값은 상한보다 작다.

**이전 연구와 비교**
- Accelerometer(Sriraman et al., ASPLOS'20): Facebook 운영 마이크로서비스에서 핵심 앱 로직은 CPU cycle의 18%까지 내려간다. 나머지는 I/O, 직렬화, 압축, 로깅, RPC 같은 orchestration이다.
- Kanev et al.(ISCA'15): Google 전체 cycle의 22–27%가 "datacenter tax"(protobuf, RPC, memmove, 할당, 압축)다.
- OB는 운영 서비스보다 요청당 로직이 훨씬 얇은 데모 앱이라, 비즈니스 로직 비율이 이 범위의 아래쪽(3–21%)에 있다.
  - 논문에서는 이 점을 밝혀야 한다. 앱 로직이 얇을수록 sidecar 비용의 상대 비율이 크게 보인다.

### sidecar 때문에 줄어들 수 있는 부분과 줄면 안 되는 부분

**기준:** 요청 하나를 처리하는 일 자체는 sidecar가 있든 없든 같다. 바뀌는 것은 요청이 앱에 "어떻게 도착하고 어떻게 나가는지"다. (b)에서 본 것처럼 요청당 연결 수, 읽기·쓰기 횟수, 깨어남, 패킷이 줄어든다. 따라서 줄어들 수 있는 것은 이 횟수에 비례하는 비용이고, 요청 내용에 비례하는 비용은 그대로여야 한다.

| 항목 | sidecar 때문에 줄 수 있나 | 이유 |
|---|---|---|
| Business logic | **줄면 안 됨** | 요청 내용 처리(페이지 렌더링, 상품 조회, 계산)는 요청 수에만 비례함. 실제로 0.45 / 0.47 / 0.43 vCPU로 약 0.45에서 그대로임 |
| Kernel | **줄 수 있음** (두 가지 이유) | ① 요청당 syscall(936 → 661/614), 깨어남(200 → 153/142), 패킷(59 → 51/25)이 줄어 커널 처리가 실제로 줄어듦. ② 귀속 이동: veth로 보낸 패킷의 수신 쪽 TCP 처리는 보내는 task의 cgroup에 잡히는데, sidecar가 있으면 pod 사이를 보내는 쪽이 sidecar라 그 몫이 sidecar로 옮겨 감. ②는 실제로 아낀 것이 아니라 장부가 옮겨 간 것 |
| RPC stack | **일부만 줄 수 있음** | 연결과 읽기·쓰기 단위로 드는 부분(소켓 읽기·쓰기, HTTP/2 frame 처리, flow control, 연결별 상태 관리)은 연결이 모이고 요청이 묶이면 줄어듦. 메시지 단위로 드는 부분(protobuf 인코딩·디코딩, 요청마다의 header·metadata 처리, gRPC 호출 처리)은 그대로여야 함. −12/−25%는 앞의 몫이 줄어든 것 |
| Runtime | **줄 수 있음** | Go 스케줄러의 goroutine 재우기·깨우기, netpoll, 유휴 스레드 순회는 깨어남 횟수에 비례함. GC 일부도 I/O 버퍼 할당에 비례함 |
| JIT / interpreted code | **일부만 줄 수 있음** | 이 안의 RPC 처리 코드(Node grpc-js, Java Netty, .NET Kestrel, gRPC의 Python 계층)는 위 RPC stack과 같은 이유로 줄 수 있음. 함께 섞인 비즈니스 로직은 줄면 안 됨. 둘을 나누려면 JIT 심볼 맵을 켜고 다시 재야 함 |

**정리**
- 메시 구성에서 줄어든 앱 CPU(15.4 → 11.6 / 10.0 vCPU)는 비즈니스 로직이 아니라 요청 입출력 비용이다. 커널, 런타임, RPC 스택의 연결·쓰기 단위 몫이 줄었고, 커널 감소에는 귀속 이동도 섞여 있다.
- 이 몫은 사라진 것이 아니라 sidecar가 대신 떠안았다. (c)의 sidecar kernel·L7 parsing과 (a)의 합계 증가가 그 결과다.

---

## (f) Enabling features on top of L7

L7 기본 구성 위에 기능을 하나씩 켰을 때의 sidecar vCPU다. 막대 안의 묶음은 (c)와 같고, 막대 위 숫자는 sidecar vCPU 합계다.

| 이름 | Linkerd | Istio |
|---|---|---|
| L7 no mTLS (Istio만) | — | PeerAuthentication `DISABLE` + DestinationRule `tls.mode: DISABLE` |
| L7 | 기본 | 기본 |
| +authz | 백엔드 서비스마다 Server + HTTPRoute(gRPC 서비스 경로) + AuthorizationPolicy(MeshTLSAuthentication: 같은 namespace의 메시 identity) | 백엔드 pod마다 AuthorizationPolicy ALLOW(principal + gRPC 경로) |
| +traffic | + HTTPLocalRateLimitPolicy(1,000,000 rps, 거부 0) + 서비스 annotation으로 retry(5xx·unavailable, 최대 2회)와 timeout 10 s | + local rate limit(EnvoyFilter, 1,000,000 토큰/s) + VirtualService(retry 2회, timeout 10 s, fault abort 0%) |
| +telem | + proxy tracing(OpenTelemetry, collector는 jet1) + access log(JSON) + 앱 tracing(parent-based 1%) | + Telemetry API(access log, tracing 1%) + 앱 tracing(parent-based 1%) |

모든 기능은 트래픽을 바꾸지 않게 걸었다. rate limit 거부 0, fault 0%, timeout은 실제로 걸리지 않는 10 s다. 그래서 기능을 평가하는 비용만 들어 있다.

### L7 policy 묶음: 기능을 켤 때마다 늘지는 않는다

L7 policy 묶음은 L7 기본 구성에서 이미 0.43(Linkerd), 1.11(Istio) vCPU다. 모든 L7 요청이 정책 설정과 상관없이 지나는 라우팅과 LB 코드가 여기 들어간다. 기능을 켰을 때 늘어나는 것은 새 코드가 요청 경로에 들어가는 경우뿐이다.

| sidecar vCPU, L7 policy | L7 | +authz | +traffic | +telem |
|---|---:|---:|---:|---:|
| Linkerd | 0.43 | 0.41 | 0.63 | 0.52 |
| Istio | 1.11 | 1.19 | 1.20 | 1.22 |

- **L7 기본에 이미 있는 몫**
  - Linkerd: 라우터 0.08, 응답 분류(classify) 0.10, stream timeout 0.06, P2C/EWMA LB 0.08, 기본 인가 정책 0.04 등
  - Istio: Envoy Router(route 매칭, upstream 요청, 재시도 상태) 0.64, cluster manager·LB·연결 풀 0.23, 기본 filter chain에 들어 있는 fault·cors·alpn 0.06 등
- **Linkerd +authz: 늘지 않음 (−0.02)**
  - 기본 상태에서도 inbound 요청마다 기본 정책(all-unauthenticated)으로 인가 검사를 한다.
  - Server, HTTPRoute, AuthorizationPolicy를 걸면 규칙만 바뀌고, 요청당 검사 비용은 그대로다.
- **Istio +authz: +0.08**
  - RBAC filter는 AuthorizationPolicy가 있을 때만 filter chain에 들어간다. RBAC filter와 matcher가 0.05 vCPU다.
- **Linkerd +traffic: +0.20**
  - 거의 다 retry(`linkerd_http_retry`, 0.18)다. 재시도하려면 요청 body를 다시 보낼 수 있게 붙잡아 두어야 해서, 실제 재시도가 없어도 요청마다 비용이 든다.
  - rate limit은 0.015 vCPU 미만이라 보이지 않는다.
- **Istio +traffic: +0.01**
  - retry와 timeout은 Envoy Router가 원래 처리한다. Istio는 기본으로 retry 2회 정책을 넣기 때문에 retry 상태 관리가 L7 기본에 이미 있다.
  - fault filter도 기본 chain에 이미 있고, local rate limit은 0.015 vCPU 미만이다.
- **+telem의 변화(Linkerd −0.11, Istio +0.02)는 측정 편차다.** 이 단계에서 정책은 바뀌지 않았다.
  - 각 측정점은 1회라, 그 단계에서 건드리지 않은 묶음도 ±0.1 vCPU 정도 움직인다. 예: Linkerd +authz에서 telemetry +0.06.

### telemetry 묶음: telem을 켜기 전에도 CPU를 쓰는 이유

두 메시 모두 **metrics는 기본으로 켜져 있다.** linkerd viz와 Kiali·Prometheus 대시보드가 쓰는 요청 수, latency histogram, 바이트 수가 그 예다. +telem이 더하는 것은 그 위의 tracing과 access log다.

| telemetry 구성 (sidecar vCPU) | L4 | L7 | +telem | 내용 |
|---|---:|---:|---:|---|
| **Linkerd** | 0.37 | 1.38 | 2.18 | |
| Prometheus metrics | 0 | 0.67 | 0.63 | 요청·응답 카운터, latency histogram, route별 metrics(`linkerd_http_prom`, `linkerd_http_metrics`, `linkerd_stack_metrics` 등) |
| `tracing` span·event 처리 | 0.24 | 0.60 | 1.27 | Rust `tracing` 프레임워크(`tracing_subscriber`). 기본 상태에서도 연결·요청마다 로그 문맥용 span을 만들고 로그 레벨 필터를 평가한다. +telem에서는 access log JSON 포맷팅과 OpenTelemetry span이 이 경로를 지나서 +0.65 |
| 바이트 카운터 | 0.13 | 0.08 | 0.07 | 연결별 송수신 바이트(`linkerd_io::sensor`). L4에도 있음 |
| trace context 전파 | 0 | 0 | 0.15 | trace header 읽기·쓰기(`linkerd_trace_context`) |
| **Istio** | 0.05 | 1.05 | 1.49 | |
| Envoy stats | 0.01 | 0.41 | 0.35 | 카운터·histogram 저장소, stat 이름 symbol table, tag 추출(`Envoy::Stats`) |
| Istio 표준 metrics | 0.01 | 0.13 | 0.14 | `istio.stats` filter: `istio_requests_total`, duration, size |
| peer metadata 교환 | 0.02 | 0.29 | 0.30 | 요청마다 상대 workload 정보(이름, namespace, label)를 주고받고 해석한다. metrics label을 붙이는 데 필요하다 |
| gRPC stats, request id | 0 | 0.10 | 0.10 | gRPC 메시지 수 집계, `x-request-id` UUID 생성 |
| tracing | 0 | 0 | 0.25 | OpenTelemetry tracer와 span 직렬화 |
| access log | 0 | 0 | 0.16 | access log 포맷팅(`Envoy::Formatter`) |

- +telem의 증가분은 Linkerd +0.80, Istio +0.44 vCPU다.
  - Linkerd: access log와 span 처리 +0.65, trace context +0.15
  - Istio: tracing +0.25, access log +0.16
- Linkerd는 access log를 stdout으로 쓰기 때문에, sidecar 밖의 containerd도 +0.83 vCPU가 늘었다(`../table_features.md`의 containerd 열).
- L4에서 telemetry가 0이 아닌 것도 같은 이유다. TCP 프록시도 연결 수와 바이트 metrics, Linkerd의 연결 span은 기본으로 유지한다.

수치는 `../table_features.md`에 있다. 각 단계의 latency, 앱+sidecar vCPU, sidecar vCPU, containerd vCPU, sidecar 묶음별 vCPU와 바로 위 단계와의 차이를 담았다.

---

## 데이터 위치

| 파일 | 내용 |
|---|---|
| `../summary.csv` | 구성 × 부하별 요약 (`summarize.py`) |
| `../tables.md` | 원자료 표 (latency, 부하별 CPU, 커널 상호작용) |
| `../table_features.md` | 기능별 증분 |
| `../<config>/rep1/r<rate>/` | 측정점 원자료: `k6.json`, `snap.json`(cgroup·`/proc`·netns 카운터), `bpf.json`, `perf.txt.gz`, `buckets.json`(sidecar 분류), `app_buckets.json`(앱 분류), `meta.json` |
| `../<config>/latency1/k6.json` | 동시 요청 1개 latency |
| `v1-classify/` | 이전 앱 분류(v1)의 `classify_app.py`, 세 측정점의 `app_buckets.json`, 그때의 그림 |
