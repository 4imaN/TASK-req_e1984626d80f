# Performance Benchmarking Guide

This document describes how to measure and validate API performance for TrailGoods. No pre-existing performance claims are asserted -- all targets must be established through reproducible measurement.

## Prerequisites

- A running instance of the API (Docker or local)
- A tool for HTTP load testing: [Locust](https://locust.io/), [k6](https://k6.io/), [wrk](https://github.com/wg/wrk), or [hey](https://github.com/rakyll/hey)
- The test database seeded with representative data

## Recommended Methodology

### 1. Establish a Baseline

Run the API in Docker Compose on the target hardware with production-like settings (connection pool sizes, worker count). Seed the database with representative data volumes before measuring.

```bash
docker compose up --build -d
python -m scripts.seed
python -m scripts.bootstrap_jobs
```

### 2. Measure Key Endpoints

Focus on the latency-sensitive paths:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/auth/login` | POST | Authentication (bcrypt cost) |
| `/api/v1/catalog/items` | GET | Paginated catalog search |
| `/api/v1/inventory/balances` | GET | Inventory balance queries |
| `/api/v1/assets/{id}` | GET | Asset metadata read |
| `/api/v1/orders` | POST | Order creation with idempotency |
| `/api/v1/orders/{id}/reserve` | POST | Stock reservation |

### 3. Example: k6 Script

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m', target: 50 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],
  },
};

const BASE = __ENV.BASE_URL || 'http://localhost:8000';

export default function () {
  const login = http.post(`${BASE}/api/v1/auth/login`, JSON.stringify({
    username: 'testuser',
    password: 'SecureP@ss123!',
  }), { headers: { 'Content-Type': 'application/json' } });

  check(login, { 'login 200': (r) => r.status === 200 });
  sleep(1);
}
```

Run with:

```bash
k6 run --env BASE_URL=http://localhost:8000 benchmarks/k6_login.js
```

### 4. Example: Locust File

```python
from locust import HttpUser, task, between

class TrailGoodsUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        resp = self.client.post("/api/v1/auth/login", json={
            "username": "testuser",
            "password": "SecureP@ss123!",
        })
        self.token = resp.json()["data"]["token"]

    @task(3)
    def browse_catalog(self):
        self.client.get("/api/v1/catalog/items", headers={
            "Authorization": f"Bearer {self.token}",
        })

    @task(1)
    def check_inventory(self):
        self.client.get("/api/v1/inventory/balances", headers={
            "Authorization": f"Bearer {self.token}",
        })
```

Run with:

```bash
locust -f benchmarks/locustfile.py --host=http://localhost:8000
```

### 5. Profiling Individual Endpoints

For per-request profiling, use the structured request logs emitted by `RequestLoggingMiddleware`. Each log entry includes `duration_ms`:

```bash
docker compose logs api | python -c "
import sys, json
for line in sys.stdin:
    try:
        entry = json.loads(line.split(' ', 3)[-1])
        if entry.get('event') == 'request':
            print(f\"{entry['method']} {entry['path']} -> {entry['status']} in {entry['duration_ms']}ms\")
    except (json.JSONDecodeError, KeyError):
        pass
"
```

### 6. Interpreting Results

When reporting results, always include:

- **Hardware**: CPU, RAM, disk type
- **Configuration**: PostgreSQL connection pool size, uvicorn workers, Docker resource limits
- **Data volume**: Number of rows in key tables (users, items, inventory_balances)
- **Concurrency**: Number of concurrent virtual users
- **Metrics**: p50, p95, p99 latency; requests/sec; error rate

Do not extrapolate from local Docker runs to production capacity. Local results establish a relative baseline for detecting regressions, not absolute performance targets.

### 7. Continuous Regression Detection

To guard against performance regressions in CI:

1. Record baseline metrics in a `benchmarks/baseline.json` file after a representative run.
2. In CI, run the same load profile against a fresh Docker Compose stack.
3. Compare p95 latencies against the baseline with a tolerance (e.g., 20%).
4. Fail the build if any endpoint exceeds the tolerance.

This provides evidence-based performance validation without asserting unverified targets.
