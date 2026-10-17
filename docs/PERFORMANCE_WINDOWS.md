# Windows native deployment and performance checkpoint (2026-10-16)

## Verified by the project operator

- Windows host, PostgreSQL 18.6, Python 3.13.15 and FastAPI responding at `http://127.0.0.1:8000`.
- Schema and event seeded successfully: nine tables; the seeded concert has 500 seats.
- Smoke demonstration: successful hold, processed simulated payment, confirmation, cancellation and inventory invariants.
- 30 simultaneous student attempts for **one seat**: one direct hold, 29 waiting, zero other outcomes, no double-booking.
- Integration suite: **5/5 PASSED**, 53.06 seconds.
- k6 5 VUs, 20 iterations: 20 holds, 0 HTTP failures, average HTTP 1.39 s, p95 2.95 s.
- k6 20 VUs, 100 iterations: 100 holds, 0 HTTP failures, average HTTP 6.34 s, p95 16.12 s.
- Profiled k6 20 VUs, 100 iterations: registration mean **1.68 s**, p95 **3.09 s**; reservation mean **9.65 s**, p95 **11.76 s**; 100 holds and no HTTP failures.
- After prior load run, integrity read returned active_tickets=0; no_double_booking=true; not_oversold=true (the holds had expired by the time this check was made).

These measurements are from locally supplied console output, **not** independent reruns in the packaging environment. No 10,000-user results are claimed.

## Suspected latency amplifier

`app/service.py::make_hold` invokes `app/cache.py::invalidate` *inside* an event-wide PostgreSQL lock. In the Windows native deployment, Redis has not been installed. The old cache module attempted a Redis network operation for **each** new hold, catching failures after its 0.3-second socket timeouts. This can add time to the critical section and compound lock waits. Event-row serialization and other SQL costs also remain possible bottlenecks; the slowdown has **not yet been proven** to come only from Redis.

## Safe A/B test without changing schema or booking rules

Do **not** rerun `db/001_schema.sql` or `db/002_seed.sql`. Keep PostgreSQL data intact.

1. Back up the existing `app/cache.py` before replacing it with the v1.1 version.
2. Stop the FastAPI process using Ctrl+C. Restart it in the **same PowerShell session** that has your database connection and JWT secret configured, adding:

```powershell
$env:REDIS_ENABLED = '0'
.\.venv313\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

3. If the background worker is running, stop it and restart with `REDIS_ENABLED=0` in its own terminal. Its `DATABASE_URL` must still be configured. For the scanner-only local mode used earlier:

```powershell
$env:REDIS_ENABLED = '0'
.\.venv313\Scripts\python.exe -c "from app.database import start_pool; from worker.run import reconciliation_loop; start_pool(); reconciliation_loop()"
```

4. Confirm `/health/ready`, then run the full integration suite (5 tests) with your existing `TEST_DATABASE_URL`, `BASE_URL` and `RUN_INTEGRATION=1` settings:

```powershell
.\.venv313\Scripts\python.exe -m pytest tests/test_unit.py tests/test_cache_disabled.py tests/test_integration.py -v
```

5. Rerun the **same** k6 workload. Compare `reservation_time` (mean and p95), registration time, errors, and HTTP throughput:

```powershell
k6 run --vus 20 --iterations 100 -e BASE_URL=http://127.0.0.1:8000 -e EVENT_ID=1 --summary-export=loadtests\profile_after_cache_off.json loadtests\race_profile.js
```

6. Recheck inventory integrity:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/events/1/integrity | Format-List
```

## Rollback / Redis bonus

To restore your original behavior, stop the API and worker, restore the backed-up `app/cache.py`, and restart. No database rollback is involved. If Redis is installed in future, start the server and omit the `REDIS_ENABLED` environment variable (or set it to `1`); the Redis bonus remains available.

## Further optimization *only after measurement*

- If reservation latency is still high, profile time spent acquiring the event lock versus doing SQL work and cache operations. Check `pg_stat_activity.wait_event_type` during k6 traffic.
- The original `SELECT ... FOR UPDATE` on the `events` row serializes all seat reservations for the concert; it preserves FIFO fairness. Do **not** remove it without redesigning locking, expiry reconciliation, and waitlist priority, then rerunning concurrency and idempotency regression tests.
- Registration and reservation combined are not the same metric: k6 sends **two HTTP calls** per iteration. Do not describe 100 iterations as 100 simultaneous users.
- Use an isolated test event or a controlled reset when comparing capacity/queue behavior; the seeded event may have expired holds or previous records.
- Load tests do not simulate successful payment confirmations unless those endpoints are explicitly exercised.

## Secrets hygiene

Do not put actual passwords, JWT secrets or full connection strings in Git, test exports or screenshots. If a credential was posted in a conversation or log, rotate it before sharing or deploying. The local `.env` is not included in this artifact.
