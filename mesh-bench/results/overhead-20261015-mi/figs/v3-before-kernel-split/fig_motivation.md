# fig_motivation: 항목 설명

그림: `fig_motivation.png` / `fig_motivation.pdf` (스크립트 `mesh-bench/overhead/plot_motivation.py`)

그림에는 각주가 없다. 측정 조건과 읽는 법은 이 문서에 있다. 패널은 하나씩 잘라 쓰도록 크게(12.5×19.7 in) 그렸다. PNG는 400 dpi(5000×7880 px)이고, PDF는 벡터라 잘라도 화질이 떨어지지 않는다.

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
| Sidecar user | sidecar 컨테이너에서 leaf가 user 영역인 몫. 안의 구성은 (d)에 있음 |

커널 몫에는 syscall, TCP/IP(loopback, veth, bridge), netfilter(iptables redirect), 스케줄러, epoll/futex가 들어간다. 그 task가 실행 중일 때 처리된 softirq도 들어간다.

**주의:** 같은 부하인데 앱 CPU(App kernel + App user)가 메시 구성에서 줄어든다.
- 이유는 (b), (f)와 부록(가로채기 경로와 CPU 귀속)에 있다.
- 비교는 합계(앱 + sidecar)로 해야 한다.

---

## (b) Sidecar coalesces the app's traffic

sidecar가 있을 때 앱이 요청을 받고 보내는 방식이 어떻게 바뀌는지 보여 준다. 세 지표 모두 HTTP 요청 하나당 값이다. 처리량은 k6가 측정 구간에 받은 응답 수 ÷ 13 s다. 그림에는 Linkerd L4·L7, Istio L4·L7 막대만 있다. No sidecar 값은 아래 표에만 있다.

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

## (c) L7 sidecar makes fewer kernel events per request

(b)와 같은 모양으로, sidecar 자신의 커널 사건을 요청당으로 L4와 L7에 나란히 그렸다. 막대는 Linkerd L4, Linkerd L7, Istio L4, Istio L7이고, 색은 (b)와 같다. 처리량과 측정 구간은 (b)와 같다.

| 항목 | 정의 |
|---|---|
| Sidecar syscalls per request | sidecar 컨테이너 cgroup의 모든 syscall 진입 횟수(`raw_syscalls:sys_enter`, bpftrace, 4 s) ÷ 요청 수 |
| Sidecar wakeups per request | sidecar 컨테이너 모든 스레드의 자발적 context switch 증가량(`/proc/<tid>/status`의 `voluntary_ctxt_switches`, CPU 측정 구간) ÷ 요청 수 |
| Pod-to-pod packets per request | (b)의 세 번째 패널과 같은 값. 메시가 있으면 sidecar끼리 주고받은 패킷이다 |

### L4 → L7에서 sidecar kernel이 줄어드는 이유

커널 비용은 처리한 바이트 수보다 **사건 수**(패킷, syscall, 스레드 깨어남)에 비례한다. L7 sidecar는 요청 하나당 이 사건 수가 적다.

**측정값** (1,500 req/s, 노드의 sidecar 전체)

| | Linkerd L4 → L7 | Istio L4 → L7 |
|---|---|---|
| sidecar kernel vCPU | 3.46 → 2.77 (**−0.69**) | 3.53 → 2.10 (**−1.43**) |
| └ TCP/IP 스택(loopback, veth) | 1.62 → 1.30 | 1.62 → 0.94 |
| └ 스케줄러 | 0.74 → 0.50 | 0.72 → 0.41 |
| └ netfilter (iptables NAT, conntrack) | 0.45 → 0.42 | 0.45 → 0.28 |
| └ syscall 진입, epoll/futex, 메모리 | 0.57 → 0.38 | 0.61 → 0.30 |
| 요청당 sidecar syscall | 252 → 177 | 424 → 225 |
| 요청당 sidecar 깨어남(자발적 context switch) | 59 → 27 | 54 → 21 |
| 요청당 pod 간 패킷 | 56 → 51 | 54 → 25 |
| 요청당 loopback 패킷 (앱↔sidecar) | 114 → 96 | 108 → 73 |

커널 하위 항목은 커널 leaf 샘플을 함수 이름으로 나눈 것이다(`classify.py`의 `KSUB`, `buckets.json`의 `sidecar_ksub`).

**왜 사건 수가 줄어드나**
1. **L4 sidecar는 바이트 중계기다.** HTTP/2 메시지의 경계를 모르기 때문에, 들어온 덩어리를 기다리지 않고 바로 다음 hop으로 넘긴다. 더 올 데이터가 있는지 모르니 모아서 보낼 수 없다.
   - 앱이 HEADERS, DATA, trailer를 따로 쓰면, 그 각각이 sidecar에서 깨어남, 읽기, 쓰기, TLS 레코드, 패킷 하나씩이 된다.
   - 이 과정이 hop마다 반복된다.
2. **L7 sidecar는 HTTP/2를 종단하고 자기 연결에 다시 쓴다.** 요청과 응답을 메시지 단위로 받으므로, 언제 쓸지를 스스로 정한다.
   - 한 번 깨어났을 때 준비된 프레임과 요청을 모아 한 번에 쓴다. 같은 백엔드로 가는 요청은 하나의 HTTP/2 연결에 다중화된다.
   - WINDOW_UPDATE, PING 같은 제어 프레임은 hop마다 처리되고, 상대 sidecar까지 그대로 전달되지 않는다.
   - 그 결과 깨어남은 절반 아래로, syscall은 30–47% 줄었다.
3. **줄어든 사건이 커널 하위 항목에 그대로 나타난다.**
   - 패킷이 줄면 TCP/IP 스택과 netfilter가 줄어든다.
   - 깨어남이 줄면 스케줄러와 epoll/futex가 줄어든다.
   - syscall이 줄면 syscall 진입 비용이 줄어든다.

**Istio가 더 많이 줄어드는 이유.** Envoy는 이벤트 루프 한 바퀴 동안 쌓인 출력을 모아서 내보낸다. 그래서 pod 간 패킷이 절반 아래(54 → 25)로 줄었고, TCP/IP 스택과 netfilter가 크게 줄었다. Linkerd는 pod 간 패킷이 거의 그대로(56 → 51)라 감소의 대부분이 깨어남과 스케줄러 쪽이고, 그래서 감소폭도 작다.

**주의**
- 커널에서 줄어든 비용은 공짜가 아니다. 대신 user 공간에서 HTTP/2를 해석하고 다시 만드는 비용(L7 parsing +2.4 / +3.6, runtime +0.9 / +0.8)을 낸다. 그래서 sidecar 합계는 +3.6 / +4.9 vCPU 늘어난다.
- 앱 쪽에도 같은 효과가 있다((b)). inbound sidecar가 요청을 묶어 넘기므로 앱의 syscall과 깨어남도 L4보다 L7에서 적다.
- 위 원리 설명은 카운터(syscall 수, 깨어남 수, 패킷 수)와 커널 하위 분류에서 추론한 것이다. syscall 종류별 횟수, 쓰기당 바이트 수, 연결 수는 측정하지 않았다.

### 이 그래프를 설명하는 방법

**한 줄 메시지.** L7 sidecar는 HTTP/2를 종단해서 메시지 단위로 모아 보낸다. 그래서 요청당 syscall, 깨어남, 패킷이 L4보다 적고, sidecar의 kernel CPU가 줄어든다(Linkerd −0.7, Istio −1.4 vCPU). 대신 user 공간 파싱 비용이 더 크게 늘어서, sidecar 전체 CPU는 오히려 늘어난다((d), (h)).

**패널 순서대로 원인 → 결과로 읽는다.**

| 패널 | 무엇을 세는가 | 변화 (Linkerd / Istio) | 커널 CPU의 어디로 이어지나 |
|---|---|---|---|
| Syscalls | sidecar가 커널을 부른 횟수 | −30% / −47% | syscall 진입, epoll |
| Wakeups | sidecar 스레드가 잠들었다 깨어난 횟수 | −54% / −61% | 스케줄러 (−0.24 / −0.31 vCPU) |
| Pod-to-pod packets | sidecar끼리 주고받은 패킷 | −9% / −54% | TCP/IP 스택, netfilter (Istio −0.68, −0.17) |

**두 메시를 비교해서 보여 준다.**
- 깨어남은 두 메시 모두 절반 넘게 줄었다. 메시지 단위 처리와 한 번 깨어날 때 여러 일을 하는 것은 L7 종단의 공통 효과다.
- 패킷은 Istio만 절반으로 줄었다. Envoy가 이벤트 루프 한 바퀴 동안의 출력을 모아 내보내기 때문이다.
- 이 차이가 kernel 감소폭의 차이(−1.4 vs −0.7)를 설명한다.

**감을 잡기 쉬운 환산.** 값은 HTTP 요청 하나당이다. 요청 하나는 gRPC 약 10번, 즉 sidecar를 약 20번 지나간다. sidecar 한 번 통과마다 대략 이렇다(20번은 근사값이라 "대략"으로 말한다).

| sidecar 한 번 통과마다 | L4 → L7 |
|---|---|
| Linkerd syscall | 13번 → 9번 |
| Istio syscall | 21번 → 11번 |
| 깨어남 | 약 3번 → 1–1.4번 |

**DPUMesh 동기와 연결 (선택).** "L7이 사건을 줄이긴 하지만 없애지는 못한다"로 마무리할 수 있다.
- L7에서도 sidecar 혼자 요청당 177–225번 syscall을 하고, 21–27번 깨어나며, 2.1–2.8 vCPU를 커널에서 쓴다.
- 여기에 (b)의 앱 쪽 커널 사건도 더해진다.
- 이 사건들은 앱과 sidecar 사이 hop 때문에 생기고, DPUMesh가 없애려는 비용이다.

**말할 때 조심할 점.**
- 원리(메시지 단위로 모아 쓰기, 제어 프레임의 hop별 처리)는 카운터에서 추론한 것이다. syscall 종류나 쓰기당 바이트 수는 측정하지 않았다.
- 세 번째 패널은 (b) 세 번째 패널과 같은 데이터다.

**영어 캡션 초안**

> *Kernel events per HTTP request in the sidecars. Terminating HTTP/2 lets the L7 sidecar batch whole messages, so it issues fewer syscalls and wakes up less than the L4 (byte-relay) sidecar; Envoy also coalesces writes per event-loop pass, halving pod-to-pod packets. This is why the sidecar's kernel CPU drops from L4 to L7 (Fig. d), while its user-space CPU grows more.*

---

## (d) Inside the sidecar

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
| telemetry | metrics, tracing, access log | prometheus_client, linkerd_metrics, 요청·바이트 카운터, trace context, OpenTelemetry(trace export), access log, tap | Envoy::Stats, istio.stats, grpc_stats, tracer, access logger, peer metadata 교환, request id |
| runtime | 프록시 런타임과 나머지 | tokio, mio, tower/linkerd_stack, `tracing` span 처리(태스크 poll마다 로그 문맥 span에 들어가고 나옴, 로그 레벨 필터. 호출 체인에 OpenTelemetry·trace context·access log가 있으면 telemetry), control plane 클라이언트(tonic, prost) | 이벤트 루프(dispatcher), 네트워크 연결·버퍼, tcmalloc, 기타 Envoy 코드 |

| sidecar vCPU | 합계 | kernel/IPC | mTLS | L7 parsing | L7 policy | telemetry | runtime |
|---|---:|---:|---:|---:|---:|---:|---:|
| Linkerd L4 | 5.0 | 3.5 | 0.4 | 0 | 0.02 | 0.1 | 1.0 |
| Linkerd L7 | 8.6 | 2.8 | 0.3 | 2.4 | 0.4 | 0.8 | 1.9 |
| Istio L4 | 5.9 | 3.5 | 0.7 | 0 | 0 | 0.05 | 1.6 |
| Istio L7 | 10.8 | 2.1 | 0.5 | 3.6 | 1.1 | 1.1 | 2.4 |

L4에서 L7로 가면 kernel/IPC가 줄어든다. 이유는 (c)에 있다. L7 sidecar는 요청을 묶어서 syscall, 깨어남, 패킷이 적다. 요청당 sidecar syscall은 Linkerd 252 → 177, Istio 424 → 225회다.

---

## (e) Latency, one request outstanding

- **측정:** k6 VU 1개가 frontend-1에 locustfile 혼합 요청을 쉬지 않고 하나씩 보낸다. 동시에 처리 중인 요청은 항상 1개다(MeshInsight의 latency 측정 방식). warm 2 s 뒤 13 s를 쟀다.
- **mean:** HTTP 요청 하나의 왕복 시간 평균(ms).
- **p99:** 99번째 백분위수(ms).
- **해석:** 경합이 없는 상태에서 sidecar가 요청마다 더하는 지연이다. HTTP 요청 하나가 서비스 사이 gRPC 약 10번과 sidecar 통과 약 20번을 거친다.

---

## (f) Inside the app containers

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
| Kernel | **줄 수 있음** (두 가지 이유) | ① 요청당 syscall(936 → 661/614), 깨어남(200 → 153/142), 패킷(59 → 51/25)이 줄어 커널 처리가 실제로 줄어듦. ② 귀속 이동: veth로 보낸 패킷의 수신 쪽 TCP 처리는 보내는 task의 cgroup에 잡히는데, sidecar가 있으면 pod 사이를 보내는 쪽이 sidecar라 그 몫이 sidecar로 옮겨 감. ②는 실제로 아낀 것이 아니라 장부가 옮겨 간 것(부록 5절) |
| RPC stack | **일부만 줄 수 있음** | 연결과 읽기·쓰기 단위로 드는 부분(소켓 읽기·쓰기, HTTP/2 frame 처리, flow control, 연결별 상태 관리)은 연결이 모이고 요청이 묶이면 줄어듦. 메시지 단위로 드는 부분(protobuf 인코딩·디코딩, 요청마다의 header·metadata 처리, gRPC 호출 처리)은 그대로여야 함. −12/−25%는 앞의 몫이 줄어든 것 |
| Runtime | **줄 수 있음** | Go 스케줄러의 goroutine 재우기·깨우기, netpoll, 유휴 스레드 순회는 깨어남 횟수에 비례함. GC 일부도 I/O 버퍼 할당에 비례함 |
| JIT / interpreted code | **일부만 줄 수 있음** | 이 안의 RPC 처리 코드(Node grpc-js, Java Netty, .NET Kestrel, gRPC의 Python 계층)는 위 RPC stack과 같은 이유로 줄 수 있음. 함께 섞인 비즈니스 로직은 줄면 안 됨. 둘을 나누려면 JIT 심볼 맵을 켜고 다시 재야 함 |

**정리**
- 메시 구성에서 줄어든 앱 CPU(15.4 → 11.6 / 10.0 vCPU)는 비즈니스 로직이 아니라 요청 입출력 비용이다. 커널, 런타임, RPC 스택의 연결·쓰기 단위 몫이 줄었고, 커널 감소에는 귀속 이동도 섞여 있다.
- 이 몫은 사라진 것이 아니라 sidecar가 대신 떠안았다. (d)의 sidecar kernel·L7 parsing과 (a)의 합계 증가가 그 결과다.

---

## (g) Inside the app containers, with DPUMesh

(f)와 같은 앱 vCPU 분해에 DPUMesh 구성을 더했다. 묶음은 (f)와 같고, **DPUMesh host stack**이 추가됐다. DPUMesh host stack은 Kernel 바로 위에 쌓았다.

**DPUMesh 구성** (`mesh-bench/overhead/run_dpumesh.py`, 2026-10-15 18:07, 1회)
- 앱: (f)와 같은 pod 24개, 같은 배치, 같은 바이너리다. `DPUMESH_ENABLE=1`만 다르고, gRPC가 sidecar 대신 DPUMesh 호스트 라이브러리를 거쳐 DPU로 간다. sidecar는 없다.
- DPUMesh: `feature/dpa-mux` `cd01a50`(= main + DPA mux), linkerd2-proxy `154b428b`
  - 호스트 라이브러리는 jet2에서 빌드했다(`~/DPUMesh/build/lib`).
  - 프록시는 jet2의 DPU에서 빌드했다(`~/DPUMesh-ob-mux`).
- DPU: jet2의 BlueField-3, PF1(DPU 03:00.1, host 0b:00.1). linkerd2-proxy(dmesh_doca)와 mock 제어 평면을 돌렸다.
  - worker 14개, `DMESH_DPA_MUX=8`, event-driven(`DMESH_BUSY_POLL=0`), irq를 CPU 0–1에 고정했다.
  - PF0에는 k8s rig의 dpumesh-runtime pod가 쉬는 상태로 있었다(DPA 스레드 실행 0회).
- 측정: (f)와 같다. 1,500 req/s, 20 s, cgroup CPU·perf·bpftrace 창도 같고, CPU는 2.3 GHz로 고정했다.
  - 결과: 1,500 req/s를 drop·실패 없이 처리했다. p50 14.2 ms, p99 29.6 ms이고, flow_check 오류도 없다.
- 호스트에서 잰 것만 담는다. DPU의 CPU(프록시가 쓰는 ARM 코어와 DPA)는 들어 있지 않다.

**DPUMesh host stack에 넣은 코드** (`classify_app.py`)
- 공통: `libdpumesh.so.5`와 그 아래 DOCA·verbs 라이브러리
- Node·.NET: `libdpumesh_stream.so`, Node addon `dpumesh_grpc.node`
- Java: `libdpumesh_jni*.so`
- Python: 패치된 cygrpc 안의 `dpumesh::` 심볼
- Go: `dmeshgo*` 패키지와 cgo 스텁. dmeshgo가 부른 cgo 호출(`runtime.cgocall`) 몫도 포함한다.
- 한계: .NET 어댑터(`Dpumesh.Grpc`)는 JIT 코드라 JIT / interpreted에 남는다.

| 앱 vCPU | No sidecar | Linkerd L7 | Istio L7 | DPUMesh |
|---|---:|---:|---:|---:|
| Business logic | 0.45 | 0.47 | 0.43 | 0.42 |
| Kernel | 5.59 | 3.63 | 3.00 | 5.39 |
| DPUMesh host stack | 0 | 0 | 0 | 2.09 |
| RPC stack | 3.40 | 3.00 | 2.55 | 2.42 |
| Runtime | 3.13 | 2.30 | 2.07 | 3.01 |
| JIT / interpreted code | 2.78 | 2.23 | 1.98 | 2.36 |
| 합계 | 15.36 | 11.63 | 10.03 | 15.69 |
| (참고) sidecar vCPU | 0 | 8.60 | 10.79 | 0 (프록시는 DPU) |

**커널 안에서 바뀐 것** (앱 커널 하위 항목, vCPU)

| | No sidecar | DPUMesh | 변화 |
|---|---:|---:|---:|
| TCP/IP 스택 | 1.37 | 0.19 | −1.18 |
| netfilter | 0.30 | 0.05 | −0.25 |
| 메모리 | 0.15 | 0.05 | −0.10 |
| 스케줄러 | 2.39 | 2.77 | +0.38 |
| syscall 진입 | 0.56 | 1.13 | +0.57 |
| epoll/futex | 0.51 | 0.71 | +0.20 |
| 기타(irq 등) | 0.32 | 0.49 | +0.17 |
| 합계 | 5.59 | 5.38 | −0.21 |

| 요청당 | No sidecar | Linkerd L7 | Istio L7 | DPUMesh |
|---|---:|---:|---:|---:|
| 앱 syscall | 936 | 661 | 614 | 1,859 |
| 앱 깨어남 | 200 | 153 | 142 | 381 |
| pod 간 패킷 | 59 | 51 | 25 | 4 |
| pod 안 loopback 패킷 | 0 | 96 | 73 | 0 |

**커널에 들어간 경로** (perf 스택의 user 부분이 DPUMesh 코드인지로 나눔, vCPU)
- DPUMesh 코드에서: 0.95
  - `ppoll` 0.30, `timerfd_settime` 0.20, irq 0.21, `read` 0.10, `epoll_wait` 0.08
- 앱·런타임에서: 4.43
  - 소켓 송수신(`write`, `read`)은 1.73에서 0.27로 줄었다.
  - Go netpoll의 `epoll_pwait`는 0.46에서 0.89로 늘었다.
  - irq 등은 0.82에서 1.00으로 늘었다.

**해석**
- 사라진 것:
  - 커널 네트워크 처리: TCP/IP 스택, netfilter, 메모리가 1.82에서 0.29 vCPU로 줄었다(−1.53).
  - pod 간 패킷과 loopback 패킷도 거의 0이다.
  - RPC stack이 3.40에서 2.42로 줄었다(−0.98). gRPC의 소켓·HTTP/2 전송 부분이 DPUMesh 경로로 바뀌었기 때문이다.
- 새로 생긴 것:
  - DPUMesh host stack(user) 2.09 vCPU
  - 완료를 기다리고 알리는 데 드는 커널 시간: DPUMesh 코드의 `ppoll`과 `timerfd`, 늘어난 인터럽트, Go netpoll 호출
  - 앱 깨어남과 syscall이 no-sidecar의 약 두 배다.
- 그래서 현재 구현에서는 DPUMesh 관련 비용(user 2.09 + 커널 0.95)이 줄어든 커널 네트워크 처리(1.53)보다 크다. 앱 합계는 no-sidecar와 비슷하다(15.69 vs 15.36).
- 호스트 합계(앱 + sidecar)로 보면 Linkerd L7(20.2)과 Istio L7(20.8)보다 4.5–5.1 vCPU 적다. sidecar 비용이 호스트에서 사라졌기 때문이다.
- latency: 동시 요청 1개일 때 평균 15.6 ms다(No sidecar 9.0, Linkerd L7 21.0, Istio L7 26.8).
- 개선할 곳은 이벤트 기반 완료 통지 경로다. 메시지마다 깨우고(ppoll, epoll, 인터럽트), 타이머를 다시 거는(timerfd_settime) 비용이 크다.

### 커널을 진입 syscall별로 나눈 결과

위 "커널 안에서 바뀐 것" 표는 실행된 커널 코드로 나눴다. 이 표는 커널에 들어온 syscall로 나눈다. 예를 들어 futex 안에서 도는 스케줄러 코드는 위 표에서는 스케줄러, 이 표에서는 스레드 재우기·깨우기다. 같은 perf 데이터를 `overhead/kernel_lang.py`로 다시 나눴다(결과: `<config>/rep1/r1500/kernel_lang.txt`).

| 앱 커널 vCPU (진입 syscall) | No sidecar | DPUMesh | 변화 |
|---|---:|---:|---:|
| 소켓 I/O (`write`, `read`, `sendmsg`, `writev`, `sendto` …) | 2.11 | 0.47 | −1.64 |
| 스레드 재우기·깨우기 (`futex`, `nanosleep`, `sched_yield`) | 2.06 | 1.85 | −0.21 |
| 이벤트 대기 (`epoll_pwait`, `epoll_wait`, `ppoll`) | 0.58 | 1.63 | +1.05 |
| timerfd 재설정 (`timerfd_settime`) | 0 | 0.20 | +0.20 |
| syscall 진입·복귀 자체 | 0.41 | 0.68 | +0.27 |
| 인터럽트 | 0.30 | 0.39 | +0.09 |
| 기타 | 0.14 | 0.17 | +0.03 |
| 합계 | 5.60 | 5.38 | −0.22 |

- 위 표와 합계가 0.01 다른 것은 반올림 때문이다.
- No sidecar에서도 커널 5.6 vCPU 중 네트워크(소켓 I/O)는 2.1뿐이다.
  - 나머지 약 3.5는 언어 런타임이 스레드를 재우고 깨우는 비용이다. 예: Go의 futex·sysmon `nanosleep`·netpoll, .NET의 `sched_yield`.
  - DPUMesh와 상관없이 남는 부분이라, 잘 돼도 커널이 이 아래로 내려가기 어렵다.
- DPUMesh는 소켓 I/O를 1.64 없앴지만, 기다리는 방식이 1.61을 더한다(이벤트 대기 +1.05, timerfd +0.20, 진입·복귀 +0.27, 인터럽트 +0.09).

### 대기 비용이 큰 이유: 호스트 라이브러리의 idle 정책

`dpumesh_eq_arm`(`DPUMesh/src/core/dmesh_core.c`)은 EQ 폴링이 빈손일 때 바로 잠들지 않는다.
- nap: 일회성 timerfd로 10 → 20 → 40 → 80 µs 뒤에 다시 확인한다.
- linger: 그다음에는 마지막 작업 뒤 1 ms가 지날 때까지 100 µs마다 확인한다.
- sleep: 그 뒤에야 doorbell을 걸고 잔다. 200 ms backstop 타이머만 남는다.
- 설정값: `DPUMESH_NAP_US=10`, `DPUMESH_NAP_CAP_US=100`, `DPUMESH_LINGER_US=1000`, `DPUMESH_BACKSTOP_MS=200`. 이번 측정은 기본값 그대로다.

1,500 req/s에서는 frontend·productcatalog 같은 바쁜 서비스에 1 ms 안에 늘 일이 들어온다. 그래서 이 서비스들의 EQ는 거의 잠들지 않고, 최대 100 µs마다 깨어나 확인만 한다.

빈 확인 한 번(Go)은 다음 순서다. syscall 약 5개와 깨어남 1–2번이 든다.
1. 타이머 인터럽트
2. Go netpoll `epoll_pwait` 복귀
3. futex로 OS 스레드 깨우기
4. goroutine이 `ppoll`로 준비 상태 확인(`DPUMesh/integrations/grpc/go/eq_wait_linux.go`)
5. 빈 `dmesh_poll_eq`
6. `epoll_wait`·`read(timerfd)`로 응답
7. `timerfd_settime`으로 재설정
8. 다시 park

Python, Node.js, .NET, Java는 `libdpumesh_stream`의 C++ reactor 스레드가 `ppoll` 루프로 같은 EQ fd를 기다린다(`DPUMesh/integrations/grpc/cpp/src/dmesh_reactor.cc`). 같은 C 코어 정책을 타므로, `dmesh_poll_eq → dpumesh_eq_arm → timerfd_settime` 스택이 이 언어들에서도 나온다.

### 언어별 분해

No sidecar → DPUMesh, 1,500 req/s. vCPU는 앱 cgroup CPU를 perf cycles 비율로 나눈 값이다. 횟수는 bpftrace 창(4 s)에서 셌다.

| 언어 (서비스) | 앱 vCPU | 커널 소켓 I/O | 이벤트 대기 + timerfd | DPUMesh user | syscall/요청 | 자발적 context switch/요청 |
|---|---|---:|---:|---:|---|---|
| Go (frontend, productcatalog, checkout, shipping) | 9.66 → 10.49 (+9%) | 1.54 → 0.24 | 0.41 → 1.23 | 1.55 | 387 → 1,166 (×3.0) | 144 → 271 (×1.9) |
| Python (recommendation, email) | 2.39 → 1.99 (−17%) | 0.18 → 0.03 | 0.07 → 0.22 | 0.21 | 58 → 145 (×2.5) | 20 → 32 (×1.6) |
| Node.js (currency, payment) | 1.27 → 1.47 (+16%) | 0.18 → 0.04 | 0.04 → 0.21 | 0.18 | 26 → 126 (×4.9) | 3.4 → 23 (×6.8) |
| .NET (cart) | 1.46 → 1.19 (−18%) | 0.12 → 0.08 | 0.02 → 0.09 | 0.07 | 447 → 369 (×0.8) | 12 → 17 (×1.4) |
| Java (ad) | 0.48 → 0.45 (−6%) | 0.06 → 0.02 | 0.03 → 0.08 | 0.07 | 16 → 51 (×3.2) | 3.9 → 9.8 (×2.5) |
| 합계 (redis 포함) | 15.36 → 15.69 (+2%) | 2.11 → 0.47 | 0.58 → 1.83 | 2.08 | 936 → 1,859 (×2.0) | 185 → 353 (×1.9) |

- 자발적 context switch는 bpftrace `sched_switch`로 센 값이다. 그래서 위 "앱 깨어남"(/proc 기준, 200 → 381)과 조금 다르다.
- 모든 언어에서 모양이 같다. 커널 소켓 I/O가 사라지고, 이벤트 대기·timerfd·DPUMesh user가 생긴다. syscall은 .NET을 빼고 2.5–4.9배가 된다.
- 원인은 공통 C 코어의 idle 정책(위 절)이다. 언어마다 다른 것은 그 위에서 기다리는 층이다.
- Go가 크게 보이는 이유는 두 가지다.
  - 양: 핫 패스(frontend, productcatalog)가 Go라서 Go가 앱 CPU의 63%(no sidecar)–67%(DPUMesh)다. DPUMesh user 2.08 중 1.55, 이벤트 대기+timerfd 증가분 1.25 중 0.82(66%)가 Go다.
  - 대기 층: Go만 netpoll → futex → `ppoll` 층이 하나 더 있다. 그래서 syscall이 3.0배, syscall 진입·복귀가 0.25에서 0.47로 늘었다.
- Node.js는 비율로 가장 나쁘다(syscall 4.9배, context switch 6.8배, 앱 vCPU +16%).
  - 원래는 libuv가 스레드 하나에서 I/O를 몰아 처리해, 요청당 3.4번만 잠들었다.
  - DPUMesh reactor 스레드는 따로 자고 깬다.
- Python(−17%)과 .NET(−18%)은 줄었다.
  - 둘 다 원래 커널 비용이 컸다. Python은 futex 0.26, `sendmsg` 0.13, .NET은 `sched_yield`·futex·`sendto`다.
  - 그 감소분이 새 대기 비용보다 컸다. .NET 런타임 자체의 `sched_yield`·futex는 그대로 남는다.
- Java는 거의 같다(−6%).
- 의미: C 코어의 idle 정책을 고치면 다섯 언어에 한꺼번에 효과가 있다. Go의 추가 대기 층은 따로 고쳐야 한다.

### No sidecar와의 성능 비교

| | No sidecar | DPUMesh | Linkerd L4 | Istio L4 | Linkerd L7 | Istio L7 |
|---|---:|---:|---:|---:|---:|---:|
| 동시 요청 1개, 평균 (ms) | 8.95 | 15.55 | 14.34 | 15.05 | 21.01 | 26.84 |
| 1,500 req/s p50 (ms) | 6.9 | 14.2 | 10.0 | 11.3 | 17.0 | 25.4 |
| 1,500 req/s p99 (ms) | 13.0 | 29.6 | 18.1 | 20.3 | 29.7 | 42.5 |
| 호스트 vCPU (앱 + sidecar) | 15.4 | 15.7 | 18.5 | 19.2 | 20.2 | 20.8 |

- DPUMesh는 no sidecar보다 느리다. 10-14 jet1 측정(`results/16core-mux`, 다른 호스트·기본 CPU 설정)에서도 1,000 req/s 평균 지연이 no sidecar 5.6 ms, DPUMesh 11.6–13.6 ms였다. 수치는 같은 날 측정끼리만 비교한다.
- 구조적 이유:
  - no sidecar에는 프록시가 없다. 지연의 하한선이다.
  - DPUMesh는 RPC마다 호스트 → PCIe → DPU의 linkerd2-proxy(HTTP/2 종료, 라우팅) → PCIe → 호스트를 지난다. 프록시 일이 호스트에서 빠졌을 뿐 없어진 것은 아니다.
  - 양쪽 다 이벤트를 기다린다. DPU 프록시는 `DMESH_BUSY_POLL=0`, 호스트 라이브러리는 타이머나 doorbell로 깨어난다. 깨어날 때마다 지연이 붙는다.
  - OB 요청 하나는 RPC를 여러 번 차례로 부르므로, RPC마다 붙는 지연이 쌓인다.
- 6.6 ms 차이가 이 원인들 사이에 어떻게 나뉘는지는 재지 않았다. DPU 쪽은 프로파일하지 않았다.
- 정리:
  - 호스트 CPU는 no sidecar와 비슷하고(+2%), 지연은 L4 sidecar 수준이면서 L7 기능을 제공한다.
  - 호스트 CPU는 원리상 no sidecar보다 낮아질 수 있다(커널 소켓 I/O 2.1, RPC stack 감소분).
  - 지연은 프록시를 한 번 더 거치므로 no sidecar를 넘기 어렵다.

**주의**
- 1회 측정이다. DPU 쪽 CPU는 포함하지 않는다.
- 언어별 분해는 perf cycles 비율을 그대로 쓴 것이다. 언어별 가중치나 보정은 넣지 않았다.
- 측정이 끝난 뒤 DPU 프록시가 자동으로 멈추지 않았다(sudo 비밀번호 캐시 문제). 우리 PID를 확인하고 수동으로 멈췄으며, 스크립트도 고쳤다(`dpumesh/dpu-jet2/start.sh`).

---

## (h) From L4 to L7, then features added

L4에서 L7로, 그다음 기능을 켜 가며 sidecar vCPU가 어떻게 쌓이는지 순서대로 보여 준다. 숫자는 막대 위 합계와, 각 단계가 바꿔야 하는 묶음의 변화량만 적었다. 묶음은 (d)와 같다.

`fig_sequence.png`는 같은 그림을 따로 그린 것으로, 아래 "막대별 변화와 원인"의 구성 요소 이름과 각주가 그림 안에 들어 있다.

**막대 구성**
- Linkerd: L4 → L7 → + traffic policy → + telemetry
- Istio: L4 → L7 → + traffic policy → + telemetry
- 두 메시 모두 +authz 막대는 그리지 않았다.
  - 어떤 묶음도 0.1 vCPU 넘게 바뀌지 않았기 때문이다.
  - authz는 뒤 막대에서 켜져 있다.
- Istio + traffic policy는 거의 그대로지만, 비용이 거의 없다는 것을 보이려고 그렸다.
- 각 막대는 왼쪽 막대에 기능을 더한 구성이다(누적).

**변화량과 빗금을 적는 묶음** (각 단계가 원리상 바꾸는 묶음)

| 단계 | 변화량을 적는 묶음 | 근거 |
|---|---|---|
| L4 → L7 | L7 parsing, L7 policy, telemetry, runtime, kernel | HTTP/2 종단, 라우팅·LB, HTTP metrics, 요청당 프록시 일이 새로 생긴다. 요청을 묶어 보내 syscall이 줄어든다. mTLS는 같은 바이트를 암호화하므로 그대로여야 한다 |
| + authz, + traffic policy | L7 policy | 정책 평가만 더해진다 |
| + telemetry | telemetry, L7 parsing | tracing, access log가 더해지고 trace header가 붙는다 |

- 그 밖의 묶음은 원리상 그대로여야 하므로, 측정값이 움직여도 적지 않았다.
  - 예: Linkerd +telem의 kernel −0.17, Istio +telem의 runtime +0.10
- 적는 묶음이라도 0.15 vCPU 미만이면 적지 않았다.
- 빗금은 그 단계가 더한 몫이고, 같은 규칙을 따른다.

**막대별 변화와 원인** (그림에서 뺀 설명. 원인은 `components.json`에서 그 단계에 0.04 vCPU 이상 늘어난 구성 요소)

| 막대 | Linkerd | Istio |
|---|---|---|
| L4 | 5.0 | 5.9 |
| L7 | 8.6: L7 parsing +2.4, runtime +0.9, telemetry +0.7, L7 policy +0.4, kernel −0.7. HTTP/2 종단, 라우팅과 LB, HTTP metrics가 생기고, 요청당 syscall이 줄어든다 | 10.8: L7 parsing +3.6, L7 policy +1.1, telemetry +1.0, runtime +0.8, kernel −1.4. 원인은 Linkerd와 같다 |
| + traffic policy | 8.8: L7 policy +0.2. retry(재시도용 요청 body 보관) | 11.1: 거의 그대로. Envoy Router가 retry와 timeout을 원래 처리한다 |
| + telemetry | 9.2: telemetry +0.6. OTel span 생성·export, trace context 전파 | 11.9: telemetry +0.5, L7 parsing +0.3. OTel tracer·export, access log, HPACK |

- Linkerd +telemetry는 access log를 stdout으로 쓴다. 그 비용(+0.8 vCPU)은 sidecar 밖의 containerd에 잡혀 막대에 없다.
- 막대 사이 합계 차이에는 표시하지 않은 묶음의 편차도 들어 있다.
  - 예: Istio L7 → + traffic policy의 +0.3은 authz 단계를 포함하며, 여러 묶음이 조금씩(최대 L7 parsing +0.11 vCPU) 움직인 합이다.
- 각 측정점은 1회다.

**기능 설정**

| 이름 | Linkerd | Istio |
|---|---|---|
| L7 no mTLS (Istio만, `../table_features.md`에만 있음) | — | PeerAuthentication `DISABLE` + DestinationRule `tls.mode: DISABLE` |
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
  - 각 측정점은 1회라, 그 단계에서 건드리지 않은 묶음도 ±0.1 vCPU 정도 움직인다. 예: Istio +authz에서 mTLS +0.06.

### telemetry 묶음: telem을 켜기 전에도 CPU를 쓰는 이유

두 메시 모두 **metrics는 기본으로 켜져 있다.** linkerd viz와 Kiali·Prometheus 대시보드가 쓰는 요청 수, latency histogram, 바이트 수가 그 예다. +telem이 더하는 것은 그 위의 tracing과 access log다.

| telemetry 구성 (sidecar vCPU) | L4 | L7 | +telem | 내용 |
|---|---:|---:|---:|---|
| **Linkerd** | 0.13 | 0.79 | 1.44 | |
| Prometheus metrics | 0 | 0.67 | 0.63 | 요청·응답 카운터, latency histogram, route별 metrics(`linkerd_http_prom`, `linkerd_http_metrics`, `linkerd_stack_metrics` 등) |
| 바이트 카운터 | 0.13 | 0.08 | 0.07 | 연결별 송수신 바이트(`linkerd_io::sensor`). L4에도 있음 |
| access log 미들웨어 | 0 | 0.04 | 0.04 | 요청마다 access log 필드를 모으는 미들웨어(`linkerd_http_access_log`). L7 스택에 항상 있음. +telem에서 실제로 로그를 쓰는 비용은 containerd에 잡힘(아래) |
| trace span과 export | 0 | 0 | 0.54 | 요청마다 OpenTelemetry span을 만들어 collector로 내보냄(`linkerd_tracing`, `opentelemetry`) |
| trace context 전파 | 0 | 0 | 0.15 | trace header 읽기·쓰기(`linkerd_trace_context`) |
| **Istio** | 0.05 | 1.05 | 1.49 | |
| Envoy stats | 0.02 | 0.49 | 0.44 | 카운터·histogram 저장소, stat 이름 symbol table, tag 추출(`Envoy::Stats`) |
| Istio 표준 metrics | 0.01 | 0.13 | 0.14 | `istio.stats` filter: `istio_requests_total`, duration, size |
| peer metadata 교환 | 0.02 | 0.29 | 0.30 | 요청마다 상대 workload 정보(이름, namespace, label)를 주고받고 해석한다. metrics label을 붙이는 데 필요하다 |
| gRPC stats, request id | 0 | 0.10 | 0.10 | gRPC 메시지 수 집계, `x-request-id` UUID 생성 |
| tracing | 0 | 0.01 | 0.27 | OpenTelemetry tracer와 span 직렬화·export |
| access log | 0 | 0 | 0.22 | access log 포맷팅과 기록(`Envoy::Formatter`, `Envoy::AccessLog`) |

- **Linkerd의 `tracing` span 처리는 runtime으로 옮겼다.** Rust `tracing` 프레임워크가 태스크를 poll할 때마다 로그 문맥 span에 들어가고 나오며, 로그 레벨 필터를 평가하는 비용이다. 값은 L4 0.24, L7 0.59, +telem 0.74 vCPU다.
  - 같은 `tracing` 코드라도 호출 체인에 OpenTelemetry, trace context, access log 코드가 있으면 telemetry로 둔다.
- +traffic 대비 +telem의 telemetry 증가분은 Linkerd +0.61, Istio +0.45 vCPU다.
  - Linkerd: trace span·export +0.54, trace context +0.15, metrics −0.06
  - Istio: tracing +0.26, access log +0.22. header 처리(HPACK, header map)가 늘어 L7 parsing도 +0.27이다.
- Linkerd는 access log를 stdout으로 쓰기 때문에, sidecar 밖의 containerd도 +0.83 vCPU가 늘었다(`../table_features.md`의 containerd 열).
- L4에서 telemetry가 0이 아닌 것도 같은 이유다. TCP 프록시도 연결 수와 바이트 metrics는 기본으로 유지한다.

수치는 `../table_features.md`에 있다. 각 단계의 latency, 앱+sidecar vCPU, sidecar vCPU, containerd vCPU, sidecar 묶음별 vCPU와 바로 위 단계와의 차이를 담았다.

---

# 부록: sidecar가 트래픽을 가로채는 경로와 CPU 귀속

(a), (c), (f)에서 말하는 "loopback 구간"과 "귀속 이동"의 배경이다.

## 1. pod는 네트워크 namespace 하나를 공유한다

- pod 안의 컨테이너(앱, sidecar)는 같은 네트워크 namespace에 있다. 그래서 인터페이스, 포트 공간, iptables 규칙을 공유한다.
- 인터페이스는 두 개다.
  - `lo`(127.0.0.1): pod 안에서만 쓰는 loopback
  - `eth0`: veth 쌍의 한쪽. 반대쪽이 host의 bridge(cni0)에 붙어 다른 pod로 이어진다.

### loopback 인터페이스(lo)란

- **정의:** 커널 안에만 있는 가상 네트워크 장치다. 하드웨어도 선로도 없다.
  - 이 장치로 패킷을 "보내면", 커널이 그 패킷을 곧바로 자기 수신 경로에 다시 넣는다(`loopback_xmit` → `netif_rx`).
  - 그래서 패킷이 그 네트워크 namespace 밖으로 나가지 않는다.
- **어떤 주소가 lo를 지나나:**
  - 127.0.0.0/8(localhost)이 대표적이다.
  - Linux는 그 namespace 자신의 주소(예: pod IP)로 가는 패킷도 lo로 보낸다. local 라우팅 테이블이 그렇게 정해 둔다.
- **namespace마다 하나씩 있다:**
  - host에도, pod마다에도 따로 있다. pod 안의 127.0.0.1은 "이 pod"를 뜻한다.
  - 앱과 sidecar는 같은 pod라서 같은 lo를 쓴다.
- **pod 간 경로(eth0)와 다른 점**

  | | lo | eth0 (veth) |
  |---|---|---|
  | 패킷이 가는 곳 | 같은 namespace의 수신 경로로 바로 | veth 반대쪽(host namespace)으로 넘어가 bridge, host netfilter(kube-proxy 규칙)를 거쳐 다른 pod의 veth로 |
  | MTU | 65536 (큰 덩어리도 패킷 하나) | 1500 (jet2의 flannel, cni0) |
  | 체크섬 계산, 이웃 탐색(ARP), 송신 큐 | 생략 | 있음(가상 장치라 일부는 생략) |

- **lo에서도 그대로 남는 일:** 패킷이 namespace 밖으로 나가지 않을 뿐, 양쪽 끝은 보통의 TCP 소켓이다.
  - 사용자↔커널 복사
  - TCP 상태 기계와 ACK
  - netfilter 훅(conntrack)
  - 받는 쪽 깨우기
- **비유:** 집 안 사람에게 편지를 건네는 것과 같다. 우체국(pod 간 네트워크)은 거치지 않지만, 봉투에 넣고 주소를 쓰고 뜯는 과정(TCP/IP)은 그대로 한다.
- **우리 측정에서:** "pod 안 loopback 패킷"은 각 pod namespace의 `lo` 송수신 패킷 카운터(`/proc/net/dev`, `snap.json`의 `pod_net.lo_pkts`) 증가량이다. sidecar가 없으면 0이다(측정 구간 동안 24개 pod 합계 0개).

## 2. iptables 규칙이 앱의 연결을 sidecar로 돌린다

메시는 pod가 뜰 때 이 namespace의 nat 테이블에 규칙을 넣는다. 넣는 주체는 init container(Linkerd `linkerd-init`, Istio `istio-init`)나 CNI 플러그인이고, 어느 쪽이든 규칙은 같다.

| | Linkerd | Istio |
|---|---|---|
| 나가는 연결 (OUTPUT 체인) | `PROXY_INIT_OUTPUT`: 다른 곳으로 가는 TCP를 `REDIRECT --to-port 4140` | `ISTIO_OUTPUT` → `ISTIO_REDIRECT`: `REDIRECT --to-ports 15001` |
| 들어오는 연결 (PREROUTING 체인) | `PROXY_INIT_REDIRECT`: `REDIRECT --to-port 4143` | `ISTIO_INBOUND` → `ISTIO_IN_REDIRECT`: `REDIRECT --to-ports 15006` |
| 무한 루프 방지 | proxy uid 2102의 트래픽, lo로 가는 트래픽은 그대로 통과 | Envoy uid 1337의 트래픽, 127.0.0.1로 가는 트래픽은 그대로 통과 |

## 3. 연결 하나가 지나는 길

앱이 `productcatalogservice:3550`에 connect하는 경우다.

1. 앱이 보낸 첫 SYN이 OUTPUT 체인에서 REDIRECT 규칙에 걸린다.
   - 목적지가 `127.0.0.1:4140`(Istio는 15001)으로 바뀐다. 커널 안에서 만들어진 패킷에 REDIRECT를 쓰면 목적지가 localhost가 되기 때문이다.
2. 목적지가 자기 주소이므로 경로는 `lo`가 된다.
3. conntrack이 이 변환을 기억한다. 이후 패킷은 규칙을 다시 훑지 않고 conntrack 조회만 하고 같은 길로 간다.
4. sidecar는 연결을 받은 뒤, 앱이 원래 가려던 주소(ClusterIP:3550)를 conntrack에서 알아낸다(`SO_ORIGINAL_DST`).
5. sidecar는 목적지 pod IP로 자기 연결을 새로 연다. 이 연결은 proxy uid라서 규칙에 걸리지 않고 eth0로 나간다.
6. 받는 pod에서는 PREROUTING 규칙이 그 연결을 inbound sidecar(4143 또는 15006)로 돌린다.
7. inbound sidecar가 앱 포트로 다시 연결한다. 대상은 127.0.0.1이나 pod 자신의 IP인데, 둘 다 자기 주소라 역시 `lo`를 지난다.

```
sidecar 없음:  앱 ─write─▶ netfilter(ClusterIP DNAT, conntrack) ─ eth0(veth) ─ bridge ─ veth ─▶ 상대 앱
sidecar 있음:  앱 ─write─▶ lo ─▶ sidecar ─write─▶ eth0(veth) ─ bridge ─ veth ─▶ 상대 sidecar ─write─▶ lo ─▶ 상대 앱
```

## 4. loopback 구간에서 커널이 하는 일

```
앱 write → tcp_sendmsg(사용자→커널 복사) → IP 송신 → netfilter(conntrack) → loopback_xmit
        → [softirq] IP 수신 → netfilter → tcp_v4_rcv → sidecar 소켓 큐 → sidecar 깨움 → sidecar read(커널→사용자 복사)
```

- 선로, 장치, bridge, veth를 지나지 않는다. 커널이 메모리 안에서 한 소켓의 데이터를 다른 소켓으로 넘기는 경로라 pod 사이 경로보다 짧다.
- 그래도 공짜는 아니다. 다음 비용이 모두 그대로 든다.
  - 복사 두 번
  - 양쪽 끝의 TCP 처리(ACK 포함)
  - 패킷마다 conntrack
  - 받는 쪽의 깨어남
- 이 비용이 MeshInsight(SoCC'23)가 IPC라고 부른 비용이고, DPUMesh가 DMA로 바꾸려는 구간이다.

## 5. CPU 귀속

- 프로세스가 `write`를 부르면, 커널은 그 스레드 문맥에서 송신 경로를 처리한다.
- veth와 loopback은 받는 쪽 처리(bridge, 상대 veth, 받는 소켓의 TCP 처리)도 대개 그 자리의 softirq에서 바로 이어서 처리한다. 그래서 그 CPU 시간이 **보낸 쪽 cgroup**에 잡힌다.
  - 이렇게 되는 것은 커널이 irq 시간을 따로 세지 않을 때다. jet2(6.8.0-146-generic)는 `CONFIG_IRQ_TIME_ACCOUNTING`이 꺼져 있어서, cgroup CPU 시간에도 perf 샘플에도 이 몫이 보낸 쪽에 잡힌다.
  - 일부 softirq는 ksoftirqd나 다른 CPU에서 처리되어 어느 pod에도 잡히지 않는다.

| | 앱의 write가 처리하는 경로 | 비용이 잡히는 곳 |
|---|---|---|
| sidecar 없음 | ClusterIP NAT, veth, bridge, 상대 pod의 TCP 수신까지 전부 | 앱 |
| sidecar 있음 | iptables redirect와 loopback, sidecar 소켓 수신까지만 | 앱 |
| | pod 사이 구간(veth, bridge, 상대 sidecar 수신) | sidecar |

**우리 데이터** (요청당, 1,500 req/s)

| | No sidecar | Linkerd L4 | Linkerd L7 | Istio L4 | Istio L7 |
|---|---:|---:|---:|---:|---:|
| pod 안 loopback 패킷 | 0 | 114 | 96 | 108 | 73 |
| pod 간(eth0) 패킷 | 59 | 56 | 51 | 54 | 25 |
| 앱 커널: TCP/IP 스택 + netfilter (vCPU) | 1.67 | 1.01 | 0.82 | 1.02 | 0.65 |

- sidecar가 없으면 loopback 패킷이 0이다. sidecar가 생기면 pod 간 패킷과 별도로 loopback 구간이 새로 생긴다.
- L4에서도 앱 커널의 TCP/IP 스택과 netfilter가 1.67에서 1.01 vCPU로 줄어든다. L4 sidecar는 메시지를 합치지 않는데도 줄어드는 것은, 긴 pod 간 구간을 이제 sidecar가 처리하기 때문이다(귀속 이동).
- 이 몫은 일이 줄어든 것이 아니라 sidecar의 kernel로 옮겨 간 것이다. 그래서 sidecar 비용은 sidecar CPU만이 아니라 앱+sidecar 합계 증가로 봐야 한다((a)).

## 6. 기존 연구와의 관계

- 가로채기 경로 자체는 Istio와 Linkerd 문서의 표준 구조다. MeshInsight도 이 경로를 전제로 오버헤드를 나눈다.
- loopback 구간을 건너뛰는 시도도 있다. eBPF sockmap을 쓰는 Merbridge와 Cilium, 같은 노드 안의 통신을 eBPF로 줄이는 SPRIGHT(SIGCOMM'22)가 그 예다.
- 귀속 이동을 명시적으로 짚은 논문은 알지 못한다. 기존 연구는 대부분 sidecar 프로세스 CPU나 전체 CPU를 잰다. 문헌 확인은 아직 하지 않았다.

### eBPF sockmap으로 loopback 구간을 건너뛰는 방법

핵심은 같은 머신 안의 두 TCP 소켓 사이에서, 보낸 데이터를 TCP/IP 스택을 거치지 않고 상대 소켓의 수신 큐에 바로 넣는 것이다.

```
평소:     앱 write → TCP 송신 → IP → netfilter → lo → [softirq] IP 수신 → netfilter → TCP 수신 → sidecar 소켓 큐
sockmap:  앱 write → [sk_msg eBPF: 상대 소켓을 찾아 redirect] ─────────────────────────────▶ sidecar 소켓 큐
```

1. **소켓 등록 (sockops 프로그램).** cgroup에 `BPF_PROG_TYPE_SOCK_OPS` 프로그램을 붙인다. TCP 연결이 맺어질 때마다(`ACTIVE_ESTABLISHED`, `PASSIVE_ESTABLISHED`) 불린다.
   - 양 끝이 같은 머신이면, 소켓을 `BPF_MAP_TYPE_SOCKHASH` 맵에 넣는다. 키는 4-tuple이다.
2. **데이터 전달 (sk_msg 프로그램).** 그 맵에 `BPF_PROG_TYPE_SK_MSG` 프로그램을 붙인다. 맵에 있는 소켓이 `sendmsg`나 `write`를 하면, 데이터가 TCP 스택에 들어가기 전에 이 프로그램이 돈다.
   - 4-tuple을 뒤집어 상대 소켓의 키를 만들고, `bpf_msg_redirect_hash(..., BPF_F_INGRESS)`를 부른다.
   - 커널이 데이터를 상대 소켓의 수신 큐에 바로 넣는다.
3. 상대가 맵에 없으면 그냥 통과시켜 평소 TCP 경로로 간다.

**걸림돌: iptables NAT.** iptables REDIRECT를 쓰면 양쪽 소켓이 보는 주소가 달라서, 뒤집은 4-tuple로 상대를 찾을 수 없다.
- 앱 소켓은 자기가 `ClusterIP:3550`에 붙었다고 안다.
- sidecar가 받은 소켓의 목적지는 `127.0.0.1:15001`이다.

Merbridge는 iptables를 eBPF로 바꿔서 이 문제를 푼다(알려진 구조 기준).

| 단계 | eBPF 훅 | 하는 일 |
|---|---|---|
| connect 시점 | `cgroup/connect4` | 앱이 connect하는 순간 목적지를 sidecar 주소로 바꾼다. 원래 목적지는 맵에 적어 둔다. NAT가 없으니 양쪽 4-tuple이 짝이 맞는다 |
| 원래 목적지 조회 | `cgroup/getsockopt` | sidecar가 `SO_ORIGINAL_DST`를 물으면 맵에 적어 둔 원래 목적지를 돌려준다 |
| 연결 후 데이터 | `sockops` + `sk_msg` | 위 방식으로 상대 소켓으로 바로 넣는다. 같은 노드의 sidecar끼리 연결도 같은 방식으로 건너뛴다 |

Cilium도 cgroup connect 훅으로 ClusterIP를 소켓 단계에서 바꾸고(kube-proxy 대체), sockhash와 sk_msg로 로컬 TCP를 가속하는 기능을 실험적으로 넣었다. 이 가속 기능은 이후 버전에서 빠진 것으로 알고 있으나, 버전은 확인하지 않았다.

**무엇이 사라지고 무엇이 남나**

| | sockmap으로 사라짐 | 그대로 남음 |
|---|---|---|
| 커널 네트워크 처리 | TCP 분할과 수신 처리, IP, netfilter·conntrack, loopback 장치, softirq | 연결 맺기(handshake)는 평소 경로 |
| 앱·sidecar 쪽 | | `write`·`read` syscall, 사용자↔커널 복사 두 번, 받는 쪽 깨어남 |
| 프록시 | | sidecar가 여전히 호스트 CPU에서 돌며 L7 처리 |

우리 데이터에 대 보면, (c)·(d)에서 줄어드는 항목 중 TCP/IP 스택과 netfilter의 loopback 몫만 사라진다. syscall 진입, 스케줄러와 깨어남, 그리고 sidecar의 user CPU는 그대로 남는다.

**DPUMesh와 비교**

| | 커널 TCP/IP 처리 | 메시지당 syscall·깨어남 | 프록시 CPU |
|---|---|---|---|
| sidecar (지금) | 있음 | 있음 | 호스트 |
| sidecar + sockmap | loopback 구간은 없음 | 있음 | 호스트 |
| DPUMesh | 앱↔프록시 구간 없음 (공유 메모리·DMA) | 없음 (호스트 라이브러리가 링으로 전달) | DPU로 이동 |

sockmap은 커널 스택만 줄이는 방법이고, DPUMesh는 이 hop 자체와 프록시 CPU를 호스트에서 없앤다. 관련 연구 대비 위치를 잡을 때 쓸 수 있다.

**확인 필요.** Merbridge와 Cilium의 세부(훅 이름, 기능이 들어가고 빠진 버전)는 기억에 의존한 것이다. 논문에 쓰기 전에 원문을 확인한다. 성능 수치는 일부러 적지 않았다.

---

# fig_steps: 단계별 sidecar CPU 증가

그림: `fig_steps.png` / `fig_steps.pdf` (스크립트 `mesh-bench/overhead/plot_steps.py`, 구성 요소는 `components.py`)

L4에서 시작해 L7, +authz, +traffic, +telem으로 하나씩 켤 때, sidecar CPU가 **어느 묶음에서 얼마나** 늘었는지 보여 준다. 조건은 (a)–(h)와 같다(1,500 req/s, 노드의 sidecar 전체).

**읽는 법**
- 행: Linkerd, Istio
- 첫 칸: L4 + mTLS 구성의 sidecar vCPU 묶음별 절대값
- 다음 칸들: 바로 왼쪽 구성 대비 묶음별 변화(Δ vCPU). 제목의 숫자는 sidecar vCPU 순증가로, `../table_features.md`의 step과 같다.
- x 축: L4 → L7 칸은 그 칸만의 범위를 쓴다. 세 기능 칸(+authz, +traffic, +telem)은 같은 범위를 써서 서로 크기를 비교할 수 있다.
- 묶음: (d)와 같다. 단, Linkerd의 `tracing` span 처리는 runtime이다.
- 칸 아래 글: 그 단계에서 0.04 vCPU 이상 움직인 구성 요소다. perf 샘플의 묶음을 정한 프레임으로 셌다. containerd가 0.3 vCPU 이상 바뀌면 함께 적었다.

| Linkerd | 합계 | kernel/IPC | mTLS | L7 parsing | L7 policy | telemetry | runtime |
|---|---:|---:|---:|---:|---:|---:|---:|
| L4 + mTLS (절대값) | 5.03 | 3.46 | 0.41 | 0.00 | 0.02 | 0.13 | 1.01 |
| L4 → L7 | +3.57 | −0.69 | −0.12 | +2.37 | +0.41 | +0.66 | +0.93 |
| + authz | −0.05 | −0.04 | −0.01 | −0.01 | −0.02 | +0.03 | 0.00 |
| + traffic | +0.25 | +0.01 | −0.01 | 0.00 | +0.22 | 0.00 | +0.03 |
| + telem | +0.40 | −0.17 | 0.00 | +0.04 | −0.11 | +0.61 | +0.02 |

| Istio | 합계 | kernel/IPC | mTLS | L7 parsing | L7 policy | telemetry | runtime |
|---|---:|---:|---:|---:|---:|---:|---:|
| L4 + mTLS (절대값) | 5.89 | 3.53 | 0.67 | 0.00 | 0.00 | 0.05 | 1.65 |
| L4 → L7 | +4.90 | −1.43 | −0.17 | +3.62 | +1.11 | +1.00 | +0.77 |
| + authz | +0.21 | −0.03 | +0.06 | +0.05 | +0.08 | +0.02 | +0.04 |
| + traffic | +0.10 | +0.07 | −0.06 | +0.06 | +0.01 | −0.03 | +0.04 |
| + telem | +0.80 | −0.04 | 0.00 | +0.27 | +0.02 | +0.45 | +0.10 |

**단계별로 늘어난 곳**

| 단계 | Linkerd | Istio |
|---|---|---|
| L4 → L7 | L7 parsing +2.37(HTTP/2 종단·재생성), runtime +0.93, telemetry +0.66(기본 metrics), L7 policy +0.41(라우팅·LB). kernel −0.69 | L7 parsing +3.62, L7 policy +1.11(Envoy Router·LB), telemetry +1.00(stats·peer metadata), runtime +0.77. kernel −1.43 |
| + authz | 늘지 않음. 기본 상태에서도 요청마다 인가를 검사함 | L7 policy +0.08(RBAC filter +0.05) |
| + traffic | L7 policy +0.22(retry +0.18: 재시도용 요청 body 보관) | 늘지 않음. Envoy Router가 retry·timeout을 원래 처리함 |
| + telem | telemetry +0.61(trace span·export +0.54, trace context +0.15). sidecar 밖 containerd +0.83(access log 쓰기) | telemetry +0.45(tracer·export +0.26, access log +0.22), L7 parsing +0.27(HPACK, header map) |

**L4 → L7에서 kernel이 줄어드는 이유.** L7 sidecar는 요청을 연결 하나에 다중화하고 묶어서 보낸다. 그래서 요청당 sidecar syscall(Linkerd 252 → 177, Istio 424 → 225)과 깨어남이 줄어든다. (d)를 참고한다.

**주의**
- 각 측정점은 1회다. 그 단계에서 건드리지 않은 묶음도 ±0.1 vCPU 정도 움직인다.
  - 예: Istio +authz의 mTLS +0.06, Linkerd +telem의 L7 policy −0.11
  - 0.1 vCPU보다 작은 변화는 위 표처럼 구성 요소 근거가 있을 때만 해석한다.
- 그림은 sidecar 컨테이너만 담는다. sidecar 밖에서 늘어나는 비용은 따로 봐야 한다.
  - Linkerd +telem: containerd +0.83(access log를 stdout으로 씀)
  - +telem 단계는 앱 tracing(1%)도 함께 켰다. 앱 CPU 증가(no-sidecar 기준 +0.69 vCPU)는 sidecar가 아니라 앱 쪽 비용이다.

---

# 데이터 위치

| 파일 | 내용 |
|---|---|
| `../summary.csv` | 구성 × 부하별 요약 (`summarize.py`) |
| `../tables.md` | 원자료 표 (latency, 부하별 CPU, 커널 상호작용) |
| `../table_features.md` | 기능별 증분 |
| `../<config>/rep1/r<rate>/` | 측정점 원자료: `k6.json`, `snap.json`(cgroup·`/proc`·netns 카운터), `bpf.json`, `perf.txt.gz`, `buckets.json`(sidecar 분류), `app_buckets.json`(앱 분류), `meta.json` |
| `../<config>/latency1/k6.json` | 동시 요청 1개 latency |
| `../D1-dpumesh/` | DPUMesh 측정점: `rep1/r1500/`(위와 같은 원자료), `latency1/`, DPU 프록시 로그 `proxy-*.log`, `flow_check.txt` |
| `../{N0-nosidecar,D1-dpumesh}/rep1/r1500/kernel_lang.txt` | 언어별 앱 vCPU, 진입 syscall별 커널, DPUMesh user, 요청당 syscall·자발적 context switch (`kernel_lang.py`, (g)) |
| `../<config>/rep1/r1500/components.json` | sidecar 묶음별·구성 요소별 vCPU (`components.py`, 기능 사다리 측정점만) |
| `v1-classify/` | 이전 앱 분류(v1)의 `classify_app.py`, 세 측정점의 `app_buckets.json`, 그때의 그림 |
| `v2-before-tracing-runtime/` | Linkerd `tracing` span 처리를 runtime으로 옮기기 전의 `classify.py`, 모든 측정점의 `buckets.json`, `summary.csv`, 표, 그림 |

스크립트(`mesh-bench/overhead/`): `classify.py`(sidecar 묶음), `classify_app.py`(앱 묶음), `summarize.py`(→ `summary.csv`), `tables_mi.py`(→ `tables.md`, `table_features.md`), `components.py`(→ `components.json`), `run_dpumesh.py`(DPUMesh 측정), `kernel_lang.py`(→ `kernel_lang.txt`), `plot_motivation.py`, `plot_steps.py`, `plot_sequence.py`, `plot_mi.py`. DPU 쪽 스크립트: `mesh-bench/dpumesh/dpu-jet2/`
