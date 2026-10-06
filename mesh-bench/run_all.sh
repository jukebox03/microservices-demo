#!/bin/bash
# run_all.sh: the whole experiment into results/. No-sidecar, Linkerd and Istio with
# 4 frontends; DPUMesh with 10 frontends, one per DPU worker. 1 run per config,
# 10 s warm + 20 s measured per load, a sweep stops when a load saturates.
#   SUDO_PW=... ./run_all.sh
cd "$(dirname "$0")/k8sob"
export WARM_S=10 MEASURE_S=20 RES=$PWD/../results
R="300 600 900 1200 1500 1800 2100 2400 2700 3000 3300 3600"
COMMON="N_FE=4 EXPECT_PODS=22 MODE=tcp MANIFEST=tcp-fe4.yaml"
env $COMMON RATES="$R" REPS=1 CFG=nosidecar ./run.sh
env $COMMON RATES="$R" REPS=1 CFG=linkerd MESH=linkerd ./run.sh
env $COMMON RATES="$R" REPS=1 CFG=istio MESH=istio ./run.sh
N_FE=10 EXPECT_PODS=28 MODE=dpumesh MANIFEST=dpumesh.yaml \
    RATES="300 900 1500 2100 2700 3000 3300 3600 3900" REPS=1 CFG=dpumesh ./run.sh
cd .. && .venv/bin/python plot.py
