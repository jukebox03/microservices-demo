#!/usr/bin/env python3
"""Per-thread CPU and context-switch snapshots of named processes.

  cpusample.py snap <out.json> name=pid [name=pid ...]
  cpusample.py diff <before.json> <after.json> [calls]

snap records, for every thread of each process, utime+stime (clock ticks) and
voluntary/involuntary context switches, plus a monotonic timestamp. diff
prints each process's CPU in cores over the window, its busiest thread, and
its context switches per second (and per call when calls is given).
"""
import json
import os
import sys
import time

HZ = os.sysconf("SC_CLK_TCK")


def stat_values(path):
    with open(path) as f:
        stat = f.read()
    comm = stat[stat.index("(") + 1:stat.rindex(")")]
    fields = stat[stat.rindex(")") + 2:].split()
    return comm, int(fields[11]) + int(fields[12]), int(fields[19])


def threads(pid):
    out = {}
    try:
        tids = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return out
    for tid in tids:
        try:
            comm, ticks, start = stat_values(f"/proc/{pid}/task/{tid}/stat")
            with open(f"/proc/{pid}/task/{tid}/status") as f:
                status = f.read()
        except OSError:
            continue
        vol = invol = 0
        for line in status.splitlines():
            if line.startswith("voluntary_ctxt_switches"):
                vol = int(line.split()[1])
            elif line.startswith("nonvoluntary_ctxt_switches"):
                invol = int(line.split()[1])
        out[tid] = [comm, ticks, vol, invol, start]
    return out


def snap(path, pairs):
    data = {"t": time.monotonic(), "procs": {}, "process_totals": {}}
    for pair in pairs:
        name, pid = pair.split("=", 1)
        if pid:
            data["procs"][name] = threads(pid)
            try:
                _, ticks, start = stat_values(f"/proc/{pid}/stat")
                # Process totals retain CPU from threads that exited during
                # the window; summing only surviving threads undercounts it.
                data["process_totals"][name] = [int(pid), start, ticks]
            except OSError:
                pass
    with open(path, "w") as f:
        json.dump(data, f)


def cpu_seconds(before, after, name):
    a = before.get("process_totals", {}).get(name)
    b = after.get("process_totals", {}).get(name)
    if a is not None and b is not None:
        if a[:2] != b[:2]:
            raise ValueError(f"{name}: process restarted during measurement")
        return max(0, b[2] - a[2]) / HZ
    # Read historical snapshots written before process totals were recorded.
    then = before["procs"].get(name, {})
    return sum(max(0, row[1] - then.get(tid, ["", 0])[1])
               for tid, row in after["procs"].get(name, {}).items()) / HZ


def diff(before_path, after_path, calls=None):
    with open(before_path) as f:
        before = json.load(f)
    with open(after_path) as f:
        after = json.load(f)
    dt = after["t"] - before["t"]
    print(f"window {dt:.3f} s")
    print(f"{'process':24s} {'cores':>6s} {'top thread':>28s} {'cores':>6s} {'nthr':>4s} {'csw/s':>8s}"
          + (f" {'csw/call':>8s} {'cpu us/call':>11s}" if calls else ""))
    total = 0.0
    for name, now in after["procs"].items():
        then = before["procs"].get(name, {})
        per = []
        csw = 0
        for tid, row in now.items():
            comm, ticks, vol, invol = row[:4]
            t0 = then.get(tid, [comm, 0, 0, 0])
            if len(row) > 4 and len(t0) > 4 and row[4] != t0[4]:
                t0 = [comm, 0, 0, 0]
            per.append((f"{tid}:{comm}", max(0, ticks - t0[1]) / HZ / dt))
            csw += (vol - t0[2]) + (invol - t0[3])
        cores = cpu_seconds(before, after, name) / dt
        total += cores
        per.sort(key=lambda x: -x[1])
        top = per[0] if per else ("-", 0.0)
        busy = sum(1 for _, c in per if c > 0.05)
        line = f"{name:24s} {cores:6.2f} {top[0][:28]:>28s} {top[1]:6.2f} {busy:4d} {csw / dt:8.0f}"
        if calls:
            line += f" {csw / calls:8.2f} {cores * dt / calls * 1e6:11.1f}"
        print(line)
    print(f"{'total':24s} {total:6.2f} cpu_s={total * dt:.3f}"
          + (f" cpu_us/call={total * dt / calls * 1e6:.1f}" if calls else ""))


if __name__ == "__main__":
    if sys.argv[1] == "snap":
        snap(sys.argv[2], sys.argv[3:])
    else:
        diff(sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else None)
