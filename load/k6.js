// Load scenario: ramp 10 -> 100 virtual users on the public URL.
//   k6 run -e BASE_URL=http://<front_ip> load/k6.js
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
const pods = new Counter('answered_by_pod');

export const options = {
  stages: [
    { duration: '1m', target: 10 },   // warm-up, baseline latency
    { duration: '2m', target: 100 },  // ramp: CPU climbs, the HPA reacts
    { duration: '5m', target: 100 },  // plateau: new pods join, latency recovers
    { duration: '1m', target: 0 },    // ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // SLO: 95% of requests under 500 ms
    http_req_failed: ['rate<0.01'],   // SLO: less than 1% errors
  },
};

export default function () {
  // 90% CPU-bound API calls (what scales), 10% static page (nginx only).
  const res = Math.random() < 0.9 ? http.get(`${BASE_URL}/api/work`) : http.get(`${BASE_URL}/`);
  check(res, { 'status is 200': (r) => r.status === 200 });
  if (res.status === 200 && res.url.includes('/api/')) {
    pods.add(1, { pod: res.json('pod') });
  }
  sleep(1);
}
