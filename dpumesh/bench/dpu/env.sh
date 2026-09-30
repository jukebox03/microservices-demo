# Environment of the DPU linkerd2-proxy and its mock control plane for
# Online Boutique (../README.md). setup.sh copies this directory to
# <DPUMesh checkout on the DPU>/ob-bench; the proxy is that checkout's
# linkerd2-proxy submodule, built by build.sh.
B=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
P=$(cd "$B/../linkerd2-proxy" && pwd)
export LINKERD2_PROXY_ROOT=$P
source "$P/scripts/dev-proxy-env.sh" >/dev/null
export MOCK_IDENTITY_ADDR=127.0.0.1:17088 MOCK_POLICY_ADDR=127.0.0.1:17087 MOCK_DESTINATION_ADDR=127.0.0.1:17089
# Every flow goes to its original destination; OB_L7=1 keeps HTTP/2
# termination, otherwise the policy is opaque (L4).
export MOCK_POLICY_ECHO_TARGET=1
[ "${OB_L7:-0}" = 1 ] || export MOCK_OUTBOUND_OPAQUE=1
export LINKERD2_PROXY_IDENTITY_SVC_ADDR=127.0.0.1:17088 LINKERD2_PROXY_DESTINATION_SVC_ADDR=127.0.0.1:17089 LINKERD2_PROXY_POLICY_SVC_ADDR=127.0.0.1:17087
export LINKERD2_PROXY_POLICY_WORKLOAD=boutique-e2e
export LINKERD2_PROXY_OUTBOUND_LISTEN_ADDR=127.0.0.1:17140 LINKERD2_PROXY_INBOUND_LISTEN_ADDR=127.0.0.1:17143
export LINKERD2_PROXY_ADMIN_LISTEN_ADDR=127.0.0.1:17191 LINKERD2_PROXY_CONTROL_LISTEN_ADDR=127.0.0.1:17190
export LINKERD2_PROXY_INBOUND_DEFAULT_POLICY=all-unauthenticated
export LINKERD2_PROXY_DOCA_DEV_PCI_ADDR=${DPU_PCI:-03:00.0} LINKERD2_PROXY_DOCA_REP_PCI_ADDR=${REP_PCI:-94:00.0}
export LINKERD2_PROXY_DOCA_SERVER_NAME=${DPUMESH_SERVER:-DPUMeshBoutique0}
export LINKERD2_PROXY_LOG=${LINKERD2_PROXY_LOG:-warn} LINKERD2_PROXY_CORES=1 DMESH_NUM_WORKERS=1 DMESH_SHARDED=1 DMESH_BUSY_POLL=${DMESH_BUSY_POLL:-1}
# This node also runs another DPA job on PF 03:00.1. Keep the Boutique
# data/helper pairs on EUs 64..127; this is placement, not a HW partition.
export DPUMESH_DPA_EU_BASE=${DPUMESH_DPA_EU_BASE:-64}
export LINKERD2_PROXY_DESTINATION_PROFILE_NETWORKS=127.0.0.0/8,10.99.0.0/16
unset DMESH_NO_TEARDOWN
R=$B/run
mkdir -p "$R"
