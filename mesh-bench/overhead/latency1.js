// One request outstanding at a time (MeshInsight's latency profiling): a single
// VU runs the locustfile task mix back to back against one frontend.
// Env: TARGET, WARM_S, MEASURE_S, OUT.
import http from 'k6/http';

const TARGETS = __ENV.TARGET.split(',');
let TARGET = TARGETS[0];
const WARM = Number(__ENV.WARM_S || 3);
const MEASURE = Number(__ENV.MEASURE_S || 20);

export const options = {
  scenarios: {
    warm: { executor: 'constant-vus', vus: 1, duration: `${WARM}s` },
    main: { executor: 'constant-vus', vus: 1, duration: `${MEASURE}s`, startTime: `${WARM}s` },
  },
  maxRedirects: 0,
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'p(99.9)', 'max', 'count'],
  thresholds: {
    'http_req_duration{scenario:main}': ['max>=0'],
    'http_reqs{scenario:main}': ['count>=0'],
    'http_req_failed{scenario:main}': ['rate>=0'],
  },
};

const products = ['0PUK6V6EV0', '1YMWWN1N4O', '2ZYFJ3GM2N', '66VCHSJNUP', '6E92ZMYYFZ',
  '9SIQT8TOJO', 'L9ECAV7KIM', 'LS4PSXUNUM', 'OLJCESPC7Z'];
const currencies = ['EUR', 'USD', 'JPY', 'CAD', 'GBP', 'TRY'];
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const ok = { responseCallback: http.expectedStatuses(200, 302) };

function index() { http.get(`${TARGET}/`, ok); }
function setCurrency() { http.post(`${TARGET}/setCurrency`, { currency_code: pick(currencies) }, ok); }
function browseProduct() { http.get(`${TARGET}/product/${pick(products)}`, ok); }
function viewCart() { http.get(`${TARGET}/cart`, ok); }
function addToCart() {
  const p = pick(products);
  http.get(`${TARGET}/product/${p}`, ok);
  http.post(`${TARGET}/cart`, { product_id: p, quantity: 1 + Math.floor(Math.random() * 10) }, ok);
}
function checkout() {
  addToCart();
  const y = new Date().getFullYear() + 1;
  http.post(`${TARGET}/cart/checkout`, {
    email: 'someone@example.com', street_address: '1600 Amphitheatre Parkway',
    zip_code: '94043', city: 'Mountain View', state: 'CA', country: 'United States',
    credit_card_number: '4432801561520454', credit_card_expiration_month: 1 + Math.floor(Math.random() * 12),
    credit_card_expiration_year: y + Math.floor(Math.random() * 70), credit_card_cvv: '672',
  }, ok);
}

// locustfile weights: index 1, setCurrency 2, browseProduct 10, addToCart 2,
// viewCart 3, checkout 1. Requests per task 1,1,1,2,1,3: 23 per 19 tasks.
const table = [];
[[index, 1], [setCurrency, 2], [browseProduct, 10], [addToCart, 2], [viewCart, 3], [checkout, 1]]
  .forEach(([f, w]) => { for (let i = 0; i < w; i++) table.push(f); });

export default function () {
  TARGET = TARGETS[(__VU - 1) % TARGETS.length];
  pick(table)();
}

export function handleSummary(data) {
  const m = (k) => (data.metrics[k] ? data.metrics[k].values : null);
  const out = {
    measure_s: MEASURE,
    dur: m('http_req_duration{scenario:main}'),
    reqs: m('http_reqs{scenario:main}'),
    failed: m('http_req_failed{scenario:main}'),
    dropped: m('dropped_iterations{scenario:main}'),
    iters: m('iterations{scenario:main}'),
    vus_max: m('vus_max'),
  };
  const json = JSON.stringify(out, null, 1);
  return __ENV.OUT === '-' ? { stdout: json } : { [__ENV.OUT]: json };
}
