#!/bin/bash
# run_all.sh: the whole experiment into results/<HOST_CORES>core/. Each
# configuration runs the replica counts that give it the most throughput while
# it uses every core it may (k8sob/gen.py lists them). HOST_CORES says how many
# jet1 cores the pods get and only names the run: the kubelet sets it (16: CPU
# manager none; 12: static with CPUs 12-15 reserved, README). Offered load in
# HTTP requests/s, 1000 apart at low load and 500 apart near each knee; 1 run
# per configuration, 5 s warm + 15 s measured per load, a sweep stops when a
# load saturates. k6 runs on K6_HOST, the load-generator node. The DPU's
# DPUMesh interrupts must be on CPUs 0-1 first (dpumesh/dpu/irq.sh pin).
#   SUDO_PW=... K6_HOST=<node> HOST_CORES=16 ./run_all.sh
cd "$(dirname "$0")/k8sob"
HOST_CORES=${HOST_CORES:-16}
export WARM_S=5 MEASURE_S=15 RES=$PWD/../results/${HOST_CORES}core
SIDECAR="500 1000 1500 2000 2500 3000 3500 4000 4500 5000"
FAST="1000 2000 3000 3500 4000 4500 5000 5500 6000 6500 7000 7500 8000"
N_FE=2 EXPECT_PODS=24 MODE=tcp MANIFEST=tcp-nosidecar.yaml RATES="$FAST" REPS=1 CFG=nosidecar ./run.sh
N_FE=6 EXPECT_PODS=24 MODE=tcp MANIFEST=tcp-linkerd.yaml RATES="$SIDECAR" REPS=1 CFG=linkerd MESH=linkerd ./run.sh
N_FE=4 EXPECT_PODS=22 MODE=tcp MANIFEST=tcp-istio.yaml RATES="$SIDECAR" REPS=1 CFG=istio MESH=istio ./run.sh
N_FE=10 W=14 EXPECT_PODS=33 MODE=dpumesh MANIFEST=dpumesh.yaml RATES="$FAST" REPS=1 CFG=dpumesh ./run.sh
cd .. && for p in plot.py packets_plot.py cpu_plot.py; do RESULTS=results/${HOST_CORES}core HOST_CORES=$HOST_CORES .venv/bin/python $p; done
