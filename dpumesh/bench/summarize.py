#!/usr/bin/env python3
"""summarize.py <result dir>...: one CSV of perf.sh results on stdout.

Rows of kind "locust" hold a Locust level: frontend req/s and latency, the
host CPU of the services (and the host proxy), and the proxy's outbound
requests per second. Rows of kind "m1" and "m64" hold one health-bench
target: calls/s and latency.
"""
import csv
import json
import re
import sys
from pathlib import Path
from cpusample import cpu_seconds

SERVICE = {"1": "productcatalog", "2": "currency", "3": "cart", "4": "recommendation",
           "5": "shipping", "6": "checkout", "7": "ad", "8": "email", "9": "payment"}
FIELDS = ["kind", "run", "mode", "users", "service", "rate_per_s", "p50", "p95", "p99", "unit",
          "failures", "host_cores", "host_ms_per_page", "proxy_rpc_per_s", "note"]


def rows(run):
    head = (run / "run.log").read_text() if (run / "run.log").exists() else ""
    m = re.search(r"mode (\w+)", head)
    mode = m.group(1) if m else ""
    ldur = re.search(r"ldur (\d+)", head)
    ldur = int(ldur.group(1)) if ldur else 40
    busy = "dpu busy poll off" if "bp0" in run.name else ""
    text = (run / "summary.txt").read_text() if (run / "summary.txt").exists() else ""
    crash = re.search(r"dpuproxy: .*crash=(\d+)", text)
    crashed = bool(crash and int(crash.group(1)))

    def lost(why):  # a window the DPA crash emptied or cut short
        return f"DPA crash, {why}" if crashed else why
    for block in re.split(r"(?m)^== ", text):
        m = re.match(r"users=(\d+): frontend req/s=([0-9.]+) requests=(\d+) p50=(\S+)ms p95=(\S+)ms "
                     r"p99=(\S+)ms failures=(\d+)", block)
        if not m:
            continue
        users, rps, n, p50, p95, p99, fail = m.groups()
        rps = float(rps)
        total = re.search(r"(?m)^total\s+([0-9.]+)", block)
        host = float(total.group(1)) if total else None
        host_ms = host / rps * 1e3 if host is not None and rps else None
        a, b = run / f"cpu-u{users}-a.json", run / f"cpu-u{users}-b.json"
        if a.exists() and b.exists() and int(n):
            before, after = json.loads(a.read_text()), json.loads(b.read_text())
            seconds = sum(cpu_seconds(before, after, name) for name in after["procs"])
            host = seconds / (after["t"] - before["t"])
            # CPU snapshots include process startup/shutdown around Locust.
            # Use measured CPU time / actual requests, not cores / Locust rps
            # (those rates use a different elapsed interval).
            host_ms = seconds / int(n) * 1e3
        proxy = re.search(r"proxy outbound requests: \d+ \((\d+)/s\)", block)
        note = [busy] if busy else []
        if rps == 0:
            note.append(lost("no requests"))
        elif int(n) < rps * ldur * 0.8:
            note.append(lost(f"cut short ({n} requests)"))
        yield dict(kind="locust", run=run.name, mode=mode, users=users, rate_per_s=f"{rps:.0f}",
                   p50=p50, p95=p95, p99=p99, unit="ms", failures=fail,
                   host_cores=f"{host:.2f}" if host is not None else "",
                   host_ms_per_page=f"{host_ms:.1f}" if host_ms is not None else "",
                   proxy_rpc_per_s=proxy.group(1) if proxy else "", note="; ".join(note))
    for kind in ("m1", "m64"):
        path = run / f"bench-{kind}.txt"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line.startswith("RESULT"):
                continue
            f = dict(kv.split("=", 1) for kv in line.split()[1:])
            ip = f["target"].split(":")[0]
            yield dict(kind=kind, run=run.name, mode=mode, service=SERVICE[ip.rsplit(".", 1)[1]],
                       rate_per_s=f["calls_per_s"], p50=f["p50_us"], p99=f["p99_us"], unit="us",
                       failures=f["errors"], note=lost("no calls") if f["calls"] == "0" else busy)


if __name__ == "__main__":
    w = csv.DictWriter(sys.stdout, FIELDS)
    w.writeheader()
    for d in sys.argv[1:]:
        for r in rows(Path(d)):
            w.writerow(r)
