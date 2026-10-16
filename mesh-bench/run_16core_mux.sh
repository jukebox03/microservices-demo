#!/bin/bash
# run_16core_mux.sh: experiment B (pods on all 16 jet1 cores) again with
# DPUMesh feature/grpc-all-mux, the per-language gRPC adapters plus DPA flow
# multiplexing (DMESH_DPA_MUX), into results/16core-mux/. Same procedure as
# run_all.sh: 1 run per configuration, 5 s warm + 15 s measured per load, a
# sweep stops at the first saturated load. Linkerd and Istio are not rerun
# (they do not use DPUMesh; results/16core has them), and KEEP_MESHES=1 leaves
# the Linkerd another rig installed in the cluster alone.
#   host: ~/DPUMesh-ob-mux = feature/grpc-all-mux, `make lib` (the manifests'
#         DPUMESH_LIB); the service binaries are run_all.sh's
#   DPU:  ~/DPUMesh-ob-mux = the same tree with linkerd2-proxy, built by
#         bench/grpc/dpu/build.sh, and ob-bench/ = dpumesh/dpu/*.sh
# Configurations (CONFIGS, default all, in this order):
#   nosidecar            the same manifest as run_all.sh, as a same-day reference
#   dpumesh-fe10         run_all.sh's DPUMesh replica counts, one DPA thread per flow
#   dpumesh-fe10-mux8    the same with 8 DPA mux threads per DPU worker
#   dpumesh-fe14rr-mux8  14 frontends, each round-robin over every catalog,
#                        currency and recommendation replica; 8 mux threads
# and, by name only, dpumesh-fe2rr-mux8 / dpumesh-fe4rr-mux8: 2 or 4 such
# frontends with no-sidecar's other replica counts (recommendation 8, currency 3),
# and dpumesh-fe2rr: the 2-frontend layout with one DPA thread per flow
#   SUDO_PW=... K6_HOST=<node> ./run_16core_mux.sh
cd "$(dirname "$0")/k8sob"
export WARM_S=5 MEASURE_S=15 RES=$PWD/../results/16core-mux KEEP_MESHES=1 DPU_DIR=DPUMesh-ob-mux
FAST="1000 2000 3000 3500 4000 4500 5000 5500 6000 6500 7000 7500 8000 8500 9000 9500 10000"
for c in ${CONFIGS:-nosidecar dpumesh-fe10 dpumesh-fe10-mux8 dpumesh-fe14rr-mux8}; do
    case $c in
    nosidecar) N_FE=2 EXPECT_PODS=24 MODE=tcp MANIFEST=tcp-nosidecar.yaml RATES="$FAST" REPS=1 CFG=$c ./run.sh ;;
    dpumesh-fe10) N_FE=10 W=14 EXPECT_PODS=33 MODE=dpumesh MANIFEST=dpumesh-mux-fe10.yaml RATES="$FAST" REPS=1 CFG=$c ./run.sh ;;
    dpumesh-fe10-mux8) DPU_ENV=DMESH_DPA_MUX=8 N_FE=10 W=14 EXPECT_PODS=33 MODE=dpumesh MANIFEST=dpumesh-mux-fe10.yaml \
        RATES="$FAST" REPS=1 CFG=$c ./run.sh ;;
    dpumesh-fe14rr-mux8) DPU_ENV=DMESH_DPA_MUX=8 N_FE=14 W=14 EXPECT_PODS=38 MODE=dpumesh MANIFEST=dpumesh-mux-fe14rr.yaml \
        RATES="$FAST" REPS=1 CFG=$c ./run.sh ;;
    # no-sidecar's replica counts (frontends round-robin over every replica)
    dpumesh-fe2rr-mux8) DPU_ENV=DMESH_DPA_MUX=8 N_FE=2 W=14 EXPECT_PODS=24 MODE=dpumesh MANIFEST=dpumesh-mux-fe2rr.yaml \
        RATES="$FAST" REPS=1 CFG=$c ./run.sh ;;
    dpumesh-fe4rr-mux8) DPU_ENV=DMESH_DPA_MUX=8 N_FE=4 W=14 EXPECT_PODS=26 MODE=dpumesh MANIFEST=dpumesh-mux-fe4rr.yaml \
        RATES="$FAST" REPS=1 CFG=$c ./run.sh ;;
    dpumesh-fe2rr) N_FE=2 W=14 EXPECT_PODS=24 MODE=dpumesh MANIFEST=dpumesh-mux-fe2rr.yaml RATES="$FAST" REPS=1 CFG=$c ./run.sh ;;
    *) echo "unknown configuration $c" >&2; exit 2 ;;
    esac
done
