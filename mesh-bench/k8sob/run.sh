#!/bin/bash
# k8sob/run.sh: one offered-load sweep of Online Boutique in Kubernetes pods
# (k8sob/gen.py) into $RES/$CFG/rep<k>/: a fresh deployment (and mesh), a 60 s
# warmup at 200 tasks/s, then per load a quiet check, WARM_S s warm + MEASURE_S s
# measured k6, CPU (kubepods cgroup, per container via cpusnap.py) and pod
# veth packets; the sweep stops at the first saturated load.
#   MODE=tcp|dpumesh MANIFEST=<yaml> N_FE=<frontends> EXPECT_PODS=<n>
#   MESH=linkerd|istio (tcp only), DPU_ENV=<extra env for the DPU proxy>
#   SUDO_PW=... RES=... RATES="..." REPS=1 CFG=<name> ./run.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
REPS=${REPS:-1 2 3}
RATES=${RATES:-100 300 500 700 900 1000 1100 1200 1300 1400 1500 1700 1900 2100 2300 2500}
WARM_S=${WARM_S:-20} MEASURE_S=${MEASURE_S:-60}
CFG=${CFG:-dpumesh}
RES=${RES:-$HERE/../results}
QUIET_MAX=${QUIET_MAX:-0.5}
DPU=192.168.100.2
mkdir -p "$RES"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$RES/run.log"; }

# snap <file>: host per-core busy, service-process CPU, and the DPU's busy time.
snap() {
    python3 - "$1" <<'EOF'
import json, os, subprocess, sys, time
hz = os.sysconf('SC_CLK_TCK')
svc = 0
for l in open('/sys/fs/cgroup/kubepods.slice/cpu.stat'):
    k, v = l.split()
    if k == 'usage_usec':
        svc = int(v) * hz // 1_000_000
v = list(map(int, open('/proc/stat').readline().split()[1:9]))
host_busy = (sum(v) - v[3] - v[4]) * 1_000_000 // hz
dpu = subprocess.run(['ssh', '192.168.100.2', 'head -1 /proc/stat'], capture_output=True, text=True).stdout.split()[1:9]
d = list(map(int, dpu))
import glob
veth = sum(int(open(f).read()) for f in glob.glob('/sys/class/net/veth*/statistics/[rt]x_packets'))
json.dump({'t': time.time(), 'host_busy': host_busy, 'svc': svc * 1_000_000 // hz, 'veth': veth,
           'dpu_busy': (sum(d) - d[3] - d[4]) * 1_000_000 // 100}, open(sys.argv[1], 'w'))
EOF
}

# cpudiff <a> <b> <out>: cores used in the window, in summarize.py's fields
# (kubepods = the services, outside = the rest of the host).
cpudiff() {
    python3 - "$@" <<'EOF'
import json, sys
a, b = (json.load(open(x)) for x in sys.argv[1:3])
dt = b['t'] - a['t']
c = lambda k: (b[k] - a[k]) / 1e6 / dt
r = {'dt': dt, 'host_busy': c('host_busy'), 'kubepods': c('svc'), 'dpu_busy': c('dpu_busy')}
r['outside'] = r['host_busy'] - r['kubepods']
r['veth_pps'] = (b.get('veth', 0) - a.get('veth', 0)) / dt
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
    GOMAXPROCS=4 taskset -c 12-15 k6 run -q --no-color -e TARGET="$TARGETS" -e RATE=$1 \
        -e WARM_S=$2 -e MEASURE_S=$3 -e OUT="$4" ../boutique.js >"$4.log" 2>&1
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
    linkerd) linkerd install --crds | kubectl apply -f - >/dev/null; linkerd install | kubectl apply -f - >/dev/null
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
    log "$CFG rep$rep: warmup 60 s at 200 tasks/s"
    k6run 200 50 10 "$d/warmup.json"
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
        line=$(python3 - "$d/rate$r.json" "$d/rate$r.cpu.json" "$MEASURE_S" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1])); c = json.load(open(sys.argv[2])); m = float(sys.argv[3])
offered = d['rate_tasks'] * m
print('rps=%.0f p50=%.1f p99=%.1f fail=%.4f dropped=%d svc=%.2fc pkt/req=%.0f outside=%.2fc %s' % (
    d['reqs']['count'] / m, d['dur']['p(50)'], d['dur']['p(99)'], d['failed']['rate'],
    d['dropped']['count'], c['kubepods'], c.get('veth_pps', 0) / max(d['reqs']['count'] / m, 1), c['outside'],
    'SAT' if d['dropped']['count'] > 0.02 * offered or d['dur']['p(99)'] > 2000 else ''))
EOF
)
        log "  $CFG rep$rep rate=$r: $line"
        [[ $line == *SAT ]] && [ "${STOP_AT_SAT:-1}" = 1 ] && { log "  saturated, ending sweep"; break; }
        sleep 5
    done
done
kubectl delete ns boutique --ignore-not-found --wait=true >/dev/null 2>&1
ssh $DPU "cd DPUMesh-online-boutique/ob-bench && SUDO_PW=$SUDO_PW ./start.sh stop" >/dev/null
log "done"
