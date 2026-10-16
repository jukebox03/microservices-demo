#!/bin/bash
# cpu.sh fix|restore|show: jet2's CPU clock for the overhead runs (asked for by the
# user, 2026-10-15): turbo off, every CPU fixed at 2.3 GHz with the performance
# governor. SMT is left as it is. fix saves the current state to $STATE first;
# restore puts it back. Needs root.
set -euo pipefail
STATE=${STATE:-/var/tmp/overhead-cpu-state}
C=/sys/devices/system/cpu
case ${1:-show} in
fix)
    [ -e "$STATE" ] || { echo "no_turbo $(cat $C/intel_pstate/no_turbo)"
        for p in $C/cpu[0-9]*/cpufreq; do echo "cpu $p $(cat $p/scaling_governor) $(cat $p/scaling_min_freq) $(cat $p/scaling_max_freq)"; done; } > "$STATE"
    echo 1 > $C/intel_pstate/no_turbo
    for p in $C/cpu[0-9]*/cpufreq; do
        echo performance > $p/scaling_governor
        echo 2300000 > $p/scaling_max_freq; echo 2300000 > $p/scaling_min_freq
    done ;;
restore)
    [ -e "$STATE" ] || { echo "no saved state in $STATE"; exit 1; }
    echo "$(awk '$1=="no_turbo"{print $2}' "$STATE")" > $C/intel_pstate/no_turbo
    awk '$1=="cpu"' "$STATE" | while read -r _ p gov lo hi; do
        [ -d "$p" ] || continue
        echo "$gov" > $p/scaling_governor; echo "$lo" > $p/scaling_min_freq; echo "$hi" > $p/scaling_max_freq
    done
    rm -f "$STATE" ;;
show) ;;
esac
echo "smt=$(cat $C/smt/control) no_turbo=$(cat $C/intel_pstate/no_turbo)" \
     "gov=$(cat $C/cpu0/cpufreq/scaling_governor) min=$(cat $C/cpu0/cpufreq/scaling_min_freq) max=$(cat $C/cpu0/cpufreq/scaling_max_freq)"
