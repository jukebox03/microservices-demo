#!/bin/bash
# k8sob/run.sh: one offered-load sweep of Online Boutique in Kubernetes pods
# (k8sob/gen.py) into $RES/$CFG/rep<k>/: a fresh deployment (and mesh), a 60 s
# warmup at 250 requests/s, then per load a quiet check, WARM_S s warm +
# MEASURE_S s measured k6, CPU (whole host split into app / sidecar / other pods /
# system by cpusnap.py) and pod veth packets; the sweep stops at the first
# saturated load. RATES are offered HTTP requests/s.
#   MODE=tcp|dpumesh MANIFEST=<yaml> N_FE=<frontends> EXPECT_PODS=<n>
#   MESH=linkerd|istio (tcp only), DPU_ENV=<extra env for the DPU proxy>
#   W=<DPU workers> K6_HOST=<ssh host running k6; unset: local, CPUs 12-15>
#   SUDO_PW=... RES=... RATES="..." REPS=1 CFG=<name> ./run.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
REPS=${REPS:-1 2 3}
RATES=${RATES:-500 1000 1500 2000 2500 3000 3500 4000 4500 5000 5500 6000}
WARM_S=${WARM_S:-20} MEASURE_S=${MEASURE_S:-60}
CFG=${CFG:-dpumesh}
RES=${RES:-$HERE/../results}
QUIET_MAX=${QUIET_MAX:-0.5}
DPU=192.168.100.2
mkdir -p "$RES"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$RES/run.log"; }

# snap <file>: host and DPU idle time, service-process CPU, pod veth packets.
# Busy time is wall time minus idle on both: the kernels are NOHZ, so idle is
# exact while /proc/stat's busy fields are tick samples that miss short wakeups.
snap() {
    python3 - "$1" <<'EOF'
import glob, json, os, subprocess, sys, time
hz = os.sysconf('SC_CLK_TCK')
idle = lambda line: (int(line.split()[4]) + int(line.split()[5])) * 1_000_000 // hz
svc = [int(l.split()[1]) for l in open('/sys/fs/cgroup/kubepods.slice/cpu.stat') if l.startswith('usage_usec ')][0]
host = idle(open('/proc/stat').readline())
t = time.time()
veth = sum(int(open(f).read()) for f in glob.glob('/sys/class/net/veth*/statistics/[rt]x_packets'))
# DPU: whole-device idle, and per thread of the DPU proxy its CPU ticks
# (utime+stime), so each shard's load shows (dmesh-shard-<k> serves DPUMesh<k>)
dpu = subprocess.run(['ssh', '192.168.100.2', 'head -1 /proc/stat; nproc; p=$(pgrep -nx linkerd2-proxy) && '
                      'for t in /proc/$p/task/*; do echo "$(cat $t/comm) $(sed "s/.*) //" $t/stat | cut -d" " -f12,13)"; done'],
                     capture_output=True, text=True).stdout.split('\n')
threads = {}
for l in dpu[2:]:
    f = l.split()
    if len(f) == 3:
        threads[f[0]] = threads.get(f[0], 0) + int(f[1]) + int(f[2])
json.dump({'t': t, 'ncpu': os.cpu_count(), 'idle': host, 'svc': svc, 'veth': veth,
           'dpu_t': time.time(), 'dpu_ncpu': int(dpu[1]), 'dpu_idle': idle(dpu[0]), 'dpu_threads': threads},
          open(sys.argv[1], 'w'))
EOF
}

# cpudiff <a> <b> <out>: cores used in the window (kubepods = the services,
# outside = the rest of the host).
cpudiff() {
    python3 - "$@" <<'EOF'
import json, sys
a, b = (json.load(open(x)) for x in sys.argv[1:3])
dt, ddt = b['t'] - a['t'], b['dpu_t'] - a['dpu_t']
r = {'dt': dt, 'host_busy': b['ncpu'] - (b['idle'] - a['idle']) / 1e6 / dt,
     'kubepods': (b['svc'] - a['svc']) / 1e6 / dt,
     'dpu_busy': b['dpu_ncpu'] - (b['dpu_idle'] - a['dpu_idle']) / 1e6 / ddt}
r['outside'] = r['host_busy'] - r['kubepods']
r['veth_pps'] = (b['veth'] - a['veth']) / dt
# per DPU proxy thread name, cores (CLK_TCK 100 on the DPU)
r['dpu_threads'] = {k: (v - a['dpu_threads'].get(k, v)) / 100 / ddt for k, v in b['dpu_threads'].items()}
json.dump(r, open(sys.argv[3], 'w'), indent=1)
EOF
}

wait_quiet() {
    local o i
    for i in $(seq 1 60); do
        snap "$RES/.q1"; sleep 5; snap "$RES/.q2"; cpudiff "$RES/.q1" "$RES/.q2" "$RES/.q"
        o=$(python3 -c "import json;print('%.2f'%json.load(open('$RES/.q'))['outside'])")
        python3 -c "import sys;sys.exit(0 if $o < $QUIET_MAX else 1)" && { echo "$o"; return 0; }
        log "  host busy outside services: $o cores, waiting"; sleep 25
    done
    echo "$o"; return 1
}

k6run() {  # rate warm measure out
    if [ -n "${K6_HOST:-}" ]; then
        # the load generator's own node: the script goes over stdin, the summary
        # comes back on stdout
        ssh "$K6_HOST" "k6 run -q --no-color -e TARGET='$TARGETS' -e RATE=$1 -e WARM_S=$2 \
            -e MEASURE_S=$3 -e OUT=- -" < ../boutique.js > "$4" 2> "$4.log"
    else
        GOMAXPROCS=4 taskset -c 12-15 k6 run -q --no-color -e TARGET="$TARGETS" -e RATE=$1 \
            -e WARM_S=$2 -e MEASURE_S=$3 -e OUT="$4" ../boutique.js >"$4.log" 2>&1
    fi
}

TARGETS=$(for i in $(seq 1 ${N_FE:-10}); do printf '%shttp://10.99.0.%d' "$([ $i = 1 ] || echo ,)" $((100 + i)); done)

smoke() {
    local base=http://10.99.0.101 jar code fail=0
    jar=$(mktemp)
    for args in "$base/" "$base/product/OLJCESPC7Z" "-X POST -d product_id=OLJCESPC7Z -d quantity=2 $base/cart" "$base/cart" \
        "-X POST $base/cart/checkout -d email=a@b.com -d street_address=x -d zip_code=94043 -d city=MV -d state=CA -d country=US -d credit_card_number=4432801561520454 -d credit_card_expiration_month=1 -d credit_card_expiration_year=2039 -d credit_card_cvv=672"; do
        code=$(curl -s -o /dev/null -w '%{http_code}' -b "$jar" -c "$jar" --max-time 20 $args)
        [ "$code" = 200 ] || [ "$code" = 302 ] || fail=1
    done
    rm -f "$jar"; return $fail
}

setup() {  # tag
    kubectl delete ns boutique --ignore-not-found --wait=true >/dev/null 2>&1
    ssh $DPU "cd DPUMesh-online-boutique/ob-bench && SUDO_PW=$SUDO_PW ./start.sh stop >/dev/null" >/dev/null
    [ "${MODE:-dpumesh}" = tcp ] || ssh $DPU "cd DPUMesh-online-boutique/ob-bench && ./start.sh mocks; sleep 1; \
        ${DPU_ENV:-} DMESH_BUSY_POLL=${DMESH_BUSY_POLL:-0} SUDO_PW=$SUDO_PW W=${W:-10} ./start.sh proxy $1" >/dev/null
    # MESH=linkerd|istio: a fresh mesh install, sidecars injected into the tcp pods.
    if kubectl get ns linkerd >/dev/null 2>&1; then
        linkerd uninstall 2>/dev/null | kubectl delete --ignore-not-found -f - >/dev/null 2>&1
        kubectl delete ns linkerd --ignore-not-found --wait=true >/dev/null 2>&1
    fi
    if kubectl get ns istio-system >/dev/null 2>&1; then
        istioctl uninstall --purge -y >/dev/null 2>&1; kubectl delete ns istio-system --ignore-not-found --wait=true >/dev/null 2>&1
    fi
    case ${MESH:-} in
    linkerd) # Linkerd requires the Gateway API CRDs (kept across runs)
             kubectl get crd httproutes.gateway.networking.k8s.io >/dev/null 2>&1 || kubectl apply --server-side \
                 -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml >/dev/null || return 1
             linkerd install --crds | kubectl apply -f - >/dev/null; linkerd install | kubectl apply -f - >/dev/null
             linkerd check --wait 5m >/dev/null || return 1 ;;
    istio) istioctl install -y --set profile=minimal >/dev/null 2>&1 || return 1
           kubectl -n istio-system rollout status deploy/istiod --timeout=300s >/dev/null ;;
    esac
    kubectl create ns boutique >/dev/null || return 1
    case ${MESH:-} in
    linkerd) kubectl annotate ns boutique linkerd.io/inject=enabled >/dev/null
             # LINKERD_OPAQUE=1: every service port opaque, so the proxies relay TCP
             # (mTLS kept) instead of terminating HTTP/2
             [ "${LINKERD_OPAQUE:-0}" = 1 ] && kubectl annotate ns boutique \
                 config.linkerd.io/opaque-ports=3550,5000,5050,6379,7000,7070,8080,9555,50051 >/dev/null ;;
    istio) kubectl label ns boutique istio-injection=enabled >/dev/null ;;
    esac
    if [ -n "${DEPLOY_CMD:-}" ]; then "$HERE/$DEPLOY_CMD" || return 1
    else kubectl apply -f "$HERE/${MANIFEST:-${MODE:-dpumesh}.yaml}" >/dev/null || return 1; fi
    local i
    for i in $(seq 1 60); do [ "$(kubectl -n boutique get pods --no-headers | grep -c Running)" = ${EXPECT_PODS:-28} ] && break; sleep 3; done
    [ "$(kubectl -n boutique get pods --no-headers | grep -c Running)" = ${EXPECT_PODS:-28} ] || return 1
    if [ -n "${MESH:-}" ]; then  # every pod must carry the sidecar
        local px=$([ "$MESH" = linkerd ] && echo linkerd-proxy || echo istio-proxy)
        [ "$(kubectl -n boutique get pods -o jsonpath='{range .items[*]}{.spec.initContainers[*].name} {.spec.containers[*].name}{"\n"}{end}' | grep -c "$px")" = ${EXPECT_PODS:-28} ] || return 1
    fi
    # record what runs in every pod (sidecar or not) for this rep
    kubectl -n boutique get pods -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.initContainers[*].name} | {.spec.containers[*].name}{"\n"}{end}' \
        > "$RES/$CFG/containers-$1.txt" 2>/dev/null
    for i in $(seq 1 10); do
        if smoke; then
            # after the smoke requests: does frontend-1's proxy see HTTP requests (L7)?
            [ "${MESH:-}" = linkerd ] && linkerd diagnostics proxy-metrics -n boutique po/frontend-1 2>/dev/null |
                grep -E '^(request_total|tcp_open_total)\{direction="outbound"' | sed 's/{.*} / /' |
                awk '{n[$1]++} END {for (k in n) print k, n[k], "series"}' > "$RES/$CFG/proxy-metrics-$1.txt"
            return 0
        fi
        sleep 3
    done
    return 1
}

log "start: cfg=$CFG mode=${MODE:-dpumesh} reps=[$REPS] rates=[$RATES] W=${W:-10} busy_poll=${DMESH_BUSY_POLL:-0}"
for rep in $REPS; do
    d="$RES/$CFG/rep$rep"; mkdir -p "$d" "$RES/$CFG"
    log "== $CFG rep$rep: setup"
    setup "$CFG-rep$rep" || { log "setup failed (services or smoke)"; continue; }
    log "$CFG rep$rep: warmup 60 s at 250 requests/s"
    k6run 250 50 10 "$d/warmup.json"
    for r in $RATES; do
        q=$(wait_quiet) || log "  not quiet ($q) before rate $r; measuring anyway, flagged"
        echo "$q" > "$d/rate$r.quiet"
        k6run $r $WARM_S $MEASURE_S "$d/rate$r.json" &
        kp=$!
        sleep $((WARM_S + 2)); snap "$d/.c1"; python3 ../cpusnap.py snap > "$d/.p1"
        sleep $((MEASURE_S - 4)); snap "$d/.c2"; python3 ../cpusnap.py snap > "$d/.p2"
        wait $kp
        cpudiff "$d/.c1" "$d/.c2" "$d/rate$r.cpu.json"; python3 ../cpusnap.py diff "$d/.p1" "$d/.p2" > "$d/rate$r.ctrs.json"
        echo "0" > "$d/rate$r.restarts.before"; kubectl -n boutique get pods --no-headers | grep -vc Running > "$d/rate$r.restarts.after"
        line=$(python3 - "$d/rate$r.json" "$d/rate$r.cpu.json" "$d/rate$r.ctrs.json" "$MEASURE_S" <<'EOF'
import json, sys
d, c, p = (json.load(open(x)) for x in sys.argv[1:4]); m = float(sys.argv[4])
offered = d['rate_tasks'] * m  # dropped counts tasks
s = p['split']
shards = [v for k, v in c.get('dpu_threads', {}).items() if k.startswith('dmesh-shard')]
print('rps=%.0f p50=%.1f p99=%.1f max=%.0f fail=%.4f dropped=%d host=%.2fc (app %.2f sidecar %.2f pods %.2f runtime %.2f user %.2f system %.2f) dpu=%.2fc%s pkt/req=%.0f %s' % (
    d['reqs']['count'] / m, d['dur']['p(50)'], d['dur']['p(99)'], d['dur']['max'], d['failed']['rate'], d['dropped']['count'],
    c['host_busy'], s['app'], s['sidecar'], s['pods'], s['runtime'], s['user'], s['system'], c['dpu_busy'],
    ' (busiest shard %.2f)' % max(shards) if shards else '',
    c.get('veth_pps', 0) / max(d['reqs']['count'] / m, 1),
    'SAT' if d['dropped']['count'] > 0.02 * offered or d['dur']['p(99)'] > 2000 else ''))
EOF
)
        log "  $CFG rep$rep rate=$r: $line"
        [[ $line == *SAT ]] && [ "${STOP_AT_SAT:-1}" = 1 ] && { log "  saturated, ending sweep"; break; }
        sleep 5
    done
    # DPUMesh: keep the proxy log and check that no DPA EU was shared by two
    # streams (a shared EU stalls requests; the run is then invalid)
    if [ "${MODE:-dpumesh}" = dpumesh ]; then
        ssh $DPU "gzip -c DPUMesh-online-boutique/ob-bench/run/proxy-$CFG-rep$rep.log" > "$d/proxy.log.gz"
        zcat "$d/proxy.log.gz" | python3 ../dpumesh/eu_check.py /dev/stdin ../dpumesh/layout14.txt > "$d/eu_check.txt"
        log "  $CFG rep$rep DPA EU check: $(tail -1 "$d/eu_check.txt")"
    fi
done
kubectl delete ns boutique --ignore-not-found --wait=true >/dev/null 2>&1
ssh $DPU "cd DPUMesh-online-boutique/ob-bench && SUDO_PW=$SUDO_PW ./start.sh stop" >/dev/null
log "done"
