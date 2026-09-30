#!/bin/bash
# matrix.sh [rep]: the run set behind DPUMesh's
# bench-results/2026-09-29_online-boutique-e2e.md (README.md), then its CSV.
#  1. every mode: Locust at 8, 32 and 128 users, then health-bench
#  2. preload and native: health-bench with 1 call in flight only, since the
#     DPA crash can cut phase 1 short in the DPUMesh modes
#  3. preload with the DPU proxy's busy poll off, whose CPU then follows load
# About 45 minutes. Results in $OUT (default dpumesh/.build/bench/results).
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT=${OUT:-$HERE/../.build/bench/results}
R=${1:-1}
mkdir -p "$OUT"
run() {  # run <tag> <env...> -- <mode>
    local tag=$1; shift
    local envs=()
    while [ "$1" != "--" ]; do envs+=("$1"); shift; done
    shift
    echo "### $tag start $(date +%T)"
    env "${envs[@]}" OUT="$OUT" bash "$HERE/perf.sh" "$1" "$tag" > "$OUT/$tag.out" 2>&1
    local rc=$?
    echo "### $tag end $(date +%T) exit=$rc"
}
for m in tcp hostproxy preload native; do run $m-r$R -- $m; done
for m in preload native; do run m1-$m-r$R USERS_LIST= SKIP_M64=1 M1_WARM=1s M1_DUR=4s -- $m; done
run bp0-preload-r$R DPU_BUSY_POLL=0 "USERS_LIST=8 32 64" LDUR=30 SKIP_BENCH=1 -- preload
python3 "$HERE/summarize.py" "$OUT"/*-r$R > "$OUT/matrix-r$R.csv"
echo "### csv $OUT/matrix-r$R.csv"
