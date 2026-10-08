#!/bin/bash
# irq.sh pin | restore: on the DPU, as root. The DPU proxy's Comch/DMA
# completions all raise interrupts of its DOCA device (03:00.1). irqbalance
# spreads them over the CPUs the DPU workers run on, and the worker sharing a
# CPU with them handles every worker's completions on top of its own work. pin
# stops irqbalance and moves them to CPUs 0-1 (the proxy's main threads,
# otherwise idle), saving the old placement; restore puts it back.
set -eu
DEV=${DEV:-03:00.1} CPUS=${CPUS:-0-1} SAVE=/tmp/irq-affinity-backup-${DEV//:/.}.txt
irqs() { grep "$DEV" /proc/interrupts | cut -d: -f1 | tr -d ' '; }
case "$1" in
    pin)
        [ -f "$SAVE" ] || for i in $(irqs); do echo "$i $(cat /proc/irq/$i/smp_affinity_list)"; done > "$SAVE"
        systemctl stop irqbalance
        for i in $(irqs); do echo "$CPUS" > /proc/irq/$i/smp_affinity_list; done ;;
    restore)
        while read -r i a _; do echo "$a" > /proc/irq/$i/smp_affinity_list; done < "$SAVE"
        rm -f "$SAVE"
        systemctl start irqbalance ;;
    *) echo "usage: $0 pin | restore" >&2; exit 2 ;;
esac
