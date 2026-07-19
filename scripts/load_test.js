// k6 load test for the MHC e-Ticketing pilot.
// Run after the stack is up: k6 run scripts/load_test.js
//
// Stages (NFR §28):
//   1. ramp to 10  concurrent users over 30s (smoke)
//   2. hold 50 concurrent users for 2m  (NFR-004: 50 agents)
//   3. ramp to 100 concurrent users for 1m (over-subscription burst)
//   4. ramp down
//
// Success criteria:
//   * p95 < 2s across the run (NFR-002)
//   * error rate < 1%
//   * no 5xx bursts longer than 5s
//
// Adjust BASE_URL to point at the pilot host.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const TOKEN = __ENV.TOKEN || 'dev:demo:ops-agents'; // dev-bypass only in dev

const errorRate = new Rate('errors');
const listLatency = new Trend('list_latency_ms');
const detailLatency = new Trend('detail_latency_ms');

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '2m',  target: 50 },
    { duration: '1m',  target: 100 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    'http_req_duration{expected_response:true}': ['p(95)<2000'],
    'errors': ['rate<0.01'],
  },
};

export default function () {
  const headers = { 'Content-Type': 'application/json' };
  if (__ENV.TOKEN) headers.Authorization = `Bearer ${TOKEN}`;

  // 1. List tickets (the most common agent action)
  const listRes = http.get(`${BASE_URL}/api/v1/tickets/`, { headers });
  listLatency.add(listRes.timings.duration);
  const ok = check(listRes, {
    'list 200': r => r.status === 200,
    'list shape': r => Array.isArray(r.json()),
  });
  if (!ok) errorRate.add(1);

  // 2. Pull a single ticket (if any)
  if (Array.isArray(listRes.json()) && listRes.json().length > 0) {
    const id = listRes.json()[0].number;
    const t0 = Date.now();
    const detailRes = http.get(`${BASE_URL}/api/v1/tickets/${id}/`, { headers });
    detailLatency.add(detailRes.timings.duration);
    const ok2 = check(detailRes, {
      'detail 200': r => r.status === 200,
    });
    if (!ok2) errorRate.add(1);
  }

  // 3. Kanban (board view)
  const kanbanRes = http.get(`${BASE_URL}/api/v1/tickets/kanban/?domain=operational`, { headers });
  check(kanbanRes, {
    'kanban 200': r => r.status === 200,
    'kanban has columns': r => r.json('columns') !== undefined,
  }) || errorRate.add(1);

  sleep(0.5);
}
