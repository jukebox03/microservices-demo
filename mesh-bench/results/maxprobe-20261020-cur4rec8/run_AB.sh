#!/bin/bash
# A: G1 with the DPU proxy at L4 (OB_L7=0); B: W0 and G1 with CFS migration_cost_ns=0 (restored after)
export HELPERS=/tmp/claude-1002/-home-jukebox-DPUMesh/7623ffc0-0a70-4605-8fef-e95024b574bd/scratchpad/helpers DPU_REV='feature/dpa-mux cd01a50 + linkerd2-proxy 154b428b + comch-wake (jet2 working tree, 2026-10-19)'
export OB_N_CUR=4 OB_N_REC=8 OB_LAYOUT=/home/jukebox/microservices-demo/mesh-bench/overhead/../dpumesh/layout14rr-fe6-cur4-rec8.txt MAX_START=5188 MAX_STEP=1.03 SKIP_P1500=1
MC=/sys/kernel/debug/sched/migration_cost_ns
START_ENV='OB_L7=0' python3 run_max_probe.py ../results/maxprobe-20261020-cur4rec8 G1-default+L4
echo "A-DONE" >> ../results/maxprobe-20261020-cur4rec8/run.log
ORIG=$(/tmp/claude-1002/-home-jukebox-DPUMesh/7623ffc0-0a70-4605-8fef-e95024b574bd/scratchpad/helpers/sudo2 cat $MC)
trap '/tmp/claude-1002/-home-jukebox-DPUMesh/7623ffc0-0a70-4605-8fef-e95024b574bd/scratchpad/helpers/sudo2 sh -c "echo $ORIG > $MC"; echo "migration_cost_ns restored: $(/tmp/claude-1002/-home-jukebox-DPUMesh/7623ffc0-0a70-4605-8fef-e95024b574bd/scratchpad/helpers/sudo2 cat $MC)" >> ../results/maxprobe-20261020-cur4rec8/run.log' EXIT
/tmp/claude-1002/-home-jukebox-DPUMesh/7623ffc0-0a70-4605-8fef-e95024b574bd/scratchpad/helpers/sudo2 sh -c "echo 0 > $MC"
echo "migration_cost_ns $ORIG -> $(/tmp/claude-1002/-home-jukebox-DPUMesh/7623ffc0-0a70-4605-8fef-e95024b574bd/scratchpad/helpers/sudo2 cat $MC)" | tee -a ../results/maxprobe-20261020-cur4rec8/run.log > ../results/maxprobe-20261020-cur4rec8/sched-mc0.txt
python3 run_max_probe.py ../results/maxprobe-20261020-cur4rec8 W0-nosidecar+mc0,G1-default+mc0
echo "ALLDONE-AB" >> ../results/maxprobe-20261020-cur4rec8/run.log
