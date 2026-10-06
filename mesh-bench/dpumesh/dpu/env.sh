# DPU linkerd2-proxy for Online Boutique over DPUMesh (mesh-bench/dpumesh).
# Lives in <DPUMesh checkout on the DPU>/ob-bench; the proxy is that
# checkout's linkerd2-proxy, already built (bench/grpc/dpu/build.sh).
B=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
P=$(cd "$B/../linkerd2-proxy" && pwd)
export LINKERD2_PROXY_ROOT=$P
export LINKERD2_PROXY_LOG=${LINKERD2_PROXY_LOG:-warn}
source "$P/scripts/dev-proxy-env.sh" >/dev/null
export MOCK_IDENTITY_ADDR=127.0.0.1:17088 MOCK_POLICY_ADDR=127.0.0.1:17087 MOCK_DESTINATION_ADDR=127.0.0.1:17089
# Every flow goes to its original destination. L7 (HTTP/2 terminated, as a
# Linkerd sidecar does) unless OB_L7=0.
export MOCK_POLICY_ECHO_TARGET=1
[ "${OB_L7:-1}" = 1 ] || export MOCK_OUTBOUND_OPAQUE=1
export LINKERD2_PROXY_IDENTITY_SVC_ADDR=127.0.0.1:17088 LINKERD2_PROXY_DESTINATION_SVC_ADDR=127.0.0.1:17089 LINKERD2_PROXY_POLICY_SVC_ADDR=127.0.0.1:17087
export LINKERD2_PROXY_POLICY_WORKLOAD=boutique-e2e
export LINKERD2_PROXY_OUTBOUND_LISTEN_ADDR=127.0.0.1:17140 LINKERD2_PROXY_INBOUND_LISTEN_ADDR=127.0.0.1:17143
export LINKERD2_PROXY_ADMIN_LISTEN_ADDR=127.0.0.1:17191 LINKERD2_PROXY_CONTROL_LISTEN_ADDR=127.0.0.1:17190
export LINKERD2_PROXY_INBOUND_DEFAULT_POLICY=all-unauthenticated
export LINKERD2_PROXY_DOCA_DEV_PCI_ADDR=${DPU_PCI:-03:00.1} LINKERD2_PROXY_DOCA_REP_PCI_ADDR=${REP_PCI:-0b:00.1}
export LINKERD2_PROXY_DOCA_SERVER_NAME=DPUMesh0
# W shared-nothing workers (Comch servers DPUMesh0..DPUMesh<W-1>), each a
# pinned current_thread runtime; the main runtime gets one core.
export DMESH_NUM_WORKERS=${W:-10} DMESH_SHARDED=1 LINKERD2_PROXY_CORES=1 DMESH_BUSY_POLL=${DMESH_BUSY_POLL:-1}
# jet1's DPU runs no other DPA job (dpa-ps is empty), so the pools may use
# every EU from 0.
export DPUMESH_DPA_EU_BASE=${DPUMESH_DPA_EU_BASE:-0}
# DPA EUs per worker. Two DPUMesh streams on one EU stall for seconds, and
# every stream holds a DPA thread on its worker's pool, so each worker gets
# its own EU range inside [base, END): the device reports 254 EUs but takes
# DPA threads only below 190 (dpaeumgmt: 190 usable). With the ob.sh layout
# (W=10, gen_layout.py 10 4 2 5 10: one frontend per worker, 179 streams
# in all) each range holds its worker's streams plus one spare EU.
# another W, OFFSETS is unset and the pools are STRIDE apart.
export DPUMESH_DPA_EU_END=${DPUMESH_DPA_EU_END:-190}
export DPUMESH_DPA_EU_STRIDE=${DPUMESH_DPA_EU_STRIDE:-$(( (DPUMESH_DPA_EU_END - DPUMESH_DPA_EU_BASE) / DMESH_NUM_WORKERS ))}
[ "$DMESH_NUM_WORKERS" = 10 ] && export DPUMESH_DPA_EU_OFFSETS=${DPUMESH_DPA_EU_OFFSETS:-0,25,45,65,84,103,120,138,155,173}
export LINKERD2_PROXY_DESTINATION_PROFILE_NETWORKS=127.0.0.0/8,10.99.0.0/16
unset DMESH_NO_TEARDOWN
R=$B/run
mkdir -p "$R"
