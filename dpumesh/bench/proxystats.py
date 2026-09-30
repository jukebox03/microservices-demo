#!/usr/bin/env python3
"""Outbound request counts and latency per service address from two
linkerd2-proxy /metrics scrapes.

  proxystats.py reqs <before> <after> <seconds>   requests per address
  proxystats.py lat <before> <after>              p50/p99 bucket per address
"""
import re
import sys
from collections import Counter

REQ = re.compile(r'^request_total\{direction="outbound",target_addr="([^"]*)".*\} (\d+)$')
LAT = re.compile(r'^response_latency_ms_bucket\{direction="outbound",target_addr="([^"]*)".*le="([^"]*)"\} (\d+)')


def lines(path):
    try:
        return open(path).read().splitlines()
    except OSError:
        return []


def reqs(before, after, secs):
    a, b = Counter(), Counter()
    for c, path in ((a, before), (b, after)):
        for line in lines(path):
            m = REQ.match(line)
            if m:
                c[m.group(1)] += int(m.group(2))
    d = {k: b[k] - a.get(k, 0) for k in b if b[k] - a.get(k, 0) > 0}
    total = sum(d.values())
    if total:
        print(f"proxy outbound requests: {total} ({total / secs:.0f}/s) "
              + " ".join(f"{k}={v}" for k, v in sorted(d.items())))


def hist(path):
    d = {}
    for line in lines(path):
        m = LAT.match(line)
        if m:
            d.setdefault(m.group(1), Counter())[m.group(2)] += int(m.group(3))
    return d


def lat(before, after):
    a, b = hist(before), hist(after)
    for t in sorted(b):
        buckets = sorted((float(k) if k != "+Inf" else float("inf"), k) for k in b[t])
        total = b[t]["+Inf"] - a.get(t, Counter())["+Inf"]
        if not total:
            continue
        out = []
        for q in (0.5, 0.99):
            for _, k in buckets:
                if b[t][k] - a.get(t, Counter())[k] >= q * total:
                    out.append(k)
                    break
        print(f"  {t:18s} n={total:7d} p50<={out[0]:>5s}ms p99<={out[1]:>5s}ms")


if __name__ == "__main__":
    if sys.argv[1] == "reqs":
        reqs(sys.argv[2], sys.argv[3], float(sys.argv[4]))
    else:
        lat(sys.argv[2], sys.argv[3])
