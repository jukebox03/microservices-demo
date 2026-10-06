// Open-loop Online Boutique load: upstream locustfile's task mix, started at a
// fixed arrival rate (k6 constant-arrival-rate) so the offered load does not
// depend on response times. Redirects are not followed: every HTTP request is
// one frontend request, as the request counts below assume.
//
// Env: TARGET (http://ip:port, or several separated by commas: each VU then
// keeps to one of them, as a client keeps to one frontend), RATE (tasks/s),
// WARM_S, MEASURE_S, OUT (json).
import http from 'k6/http';

const TARGETS = __ENV.TARGET.split(',');
let TARGET = TARGETS[0];
const RATE = Number(__ENV.RATE);
const WARM = Number(__ENV.WARM_S || 20);
const MEASURE = Number(__ENV.MEASURE_S || 60);
const VUS = Math.max(64, Math.ceil(RATE * 0.5));

function scenario(start, dur) {
  return {
    executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s',
    duration: `${dur}s`, startTime: `${start}s`,
    preAllocatedVUs: VUS, maxVUs: VUS * 8, gracefulStop: '10s',
  };
}

export const options = {
  scenarios: { warm: scenario(0, WARM), main: scenario(WARM, MEASURE) },
  maxRedirects: 0,
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(99)', 'p(99.9)', 'max', 'count'],
  // Submetrics appear in the summary only through thresholds.
  thresholds: {
    'http_req_duration{scenario:main}': ['max>=0'],
    'http_reqs{scenario:main}': ['count>=0'],
    'http_req_failed{scenario:main}': ['rate>=0'],
    'dropped_iterations{scenario:main}': ['count>=0'],
    'iterations{scenario:main}': ['count>=0'],
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
    rate_tasks: RATE, measure_s: MEASURE,
    dur: m('http_req_duration{scenario:main}'),
    reqs: m('http_reqs{scenario:main}'),
    failed: m('http_req_failed{scenario:main}'),
    dropped: m('dropped_iterations{scenario:main}'),
    iters: m('iterations{scenario:main}'),
    vus_max: m('vus_max'),
  };
  return { [__ENV.OUT]: JSON.stringify(out, null, 1) };
}
