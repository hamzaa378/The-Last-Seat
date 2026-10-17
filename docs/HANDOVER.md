# Latest checkpoint · Streamlit v1.2 · 2026-10-17

The add-on now includes a native Windows **Streamlit frontend** plus styled `/docs`. The canonical backend and PostgreSQL schema remain unchanged.

**Current proven results from operator logs:** PostgreSQL 18.6 and Python 3.13.15 native Windows; 5/5 database integration tests passed before the v1.1 cache patch; smoke demo passed; one-seat 30-student race passed; v1.1 offline Redis improvement at 20 VUs took mean reservation latency from 9.65s to 119.64ms; event 13 k6 test completed 10,000 attempts with 200 VUs (500 holds and 9,500 waitlisted); post-test integrity True for both invariants. These results are user-reported console outputs, not independently rerun here.

**New/updated files:** `frontend/streamlit_app.py`, `frontend/api_client.py`, `frontend/styles.css`, `frontend/requirements.txt`, `.streamlit/config.toml`, `app/static/swagger_theme.css`, cosmetic/metadata changes only in `app/main.py` and `app/schemas.py`, `scripts/start_api_windows.ps1`, `scripts/start_worker_windows.ps1`, `scripts/start_frontend_windows.ps1`, `tests/test_frontend_client.py`, `docs/STREAMLIT_GUIDE.md`, `docs/DEMO_SCRIPT.md`, and `UI_ADDON_README.md`.

**What remains:** Run `pip install -r frontend/requirements.txt` and launch all three Windows processes, visually verify Streamlit in-browser, run all backend regressions, confirm queue payment/expiry through UI, take screenshots, and document any errors. Redis and RabbitMQ bonus runtime paths, public TLS/deployment, and load testing of the Streamlit layer remain unverified.

**No migration necessary.** Do not rerun `db/001_schema.sql` or `db/002_seed.sql`; test event 13 and original event 1 already exist on the user's machine. See `docs/STREAMLIT_GUIDE.md`. The older v1.1 handover details follow for historical context; any old pending-status language is superseded by the checkpoint above.

---

# HANDOVER / CONTINUATION GUIDE

This is the canonical orientation file for anyone continuing the backend.

## Task and current scope

- Task: CodeChef-VIT promotional cycle 2026–27, backend development,
  **The Last Seat** (task sheet pages 7–8).
- Problem: 500 concert seats, 10,000 potential students, seat reservation,
  time-limited holds, payments, cancellation, duplicates, history and queue.
- Technology: Python 3.12, FastAPI, PostgreSQL 16, Redis 7, RabbitMQ 3.13,
  Nginx, Docker Compose, pytest, k6.
- Source of truth: PostgreSQL, **never** Redis or RabbitMQ.
- External real payments: not implemented, intentionally simulated.
- Public cloud deployment: not performed.

## Files and responsibilities

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI routing, OpenAPI, ownership checks, input validation, response formatting |
| `app/schemas.py` | Pydantic request models with bounds and allowed outcomes |
| `app/security.py` | Password hashing, JWT issuance and bearer-user lookup |
| `app/config.py` | Environment variables and TTLs |
| `app/database.py` | Bounded psycopg pool and transaction/read helpers |
| `app/service.py` | Event locks, hold expiration, FIFO promotion, booking/payment state transitions |
| `app/idempotency.py` | SHA-256 request fingerprints and atomic saved HTTP responses |
| `app/cache.py` | Optional Redis caching of read-only seat maps |
| `worker/run.py` | RabbitMQ outbox publication, consumption and database recovery/expiry scanner |
| `db/001_schema.sql` | 9 tables, partial indexes, referential integrity, append-only audit trigger |
| `db/002_seed.sql` | 500-seat demo event; repeatable seed |
| `Dockerfile` | Python 3.12 image run as unprivileged user |
| `docker-compose.yml` | PostgreSQL + Redis + RabbitMQ + API + worker + Nginx deployment |
| `nginx/default.conf` | Reverse proxy and simple security headers |
| `tests/test_unit.py` | Pure-code input/idempotency checks |
| `tests/test_integration.py` | Concurrent one-seat race, key replay, queue handoff, delayed payment and refund |
| `scripts/smoke_demo.py` | Beginner-friendly complete booking and cancellation demo |
| `scripts/concurrency_probe.py` | Standalone 30-student, single-seat end-to-end proof |
| `scripts/invariants.sql` | Database integrity verification after pressure tests |
| `loadtests/race.js` | k6 concurrent traffic script |
| `docs/DIAGRAMS.md` | Mermaid ERD and sequence/workflow diagrams |
| `docs/ARCHITECTURE.md` | Design reasoning, proofs, tradeoffs and scaling |
| `docs/DECISIONS.md` | Student-facing design discussion and demo walkthrough |
| `docs/OPERATIONS.md` | Deployment, backups, failures and cloud checklist |
| `docs/TEST_REPORT.md` | Results and evidence collection template |
| `.github/workflows/ci.yml` | Unit plus optional Compose integration verification in GitHub Actions |

## Database structure / migration state

Bootstrap SQL files in `db/` are mounted in `docker-entrypoint-initdb.d` and
run only when PostgreSQL is first initialized. Main tables are:

1. `users` account identities (email, password hash).
2. `events` concert rows, one event lock per simultaneous allocation.
3. `seats` numbered seat inventory, 500 generated at seed.
4. `bookings` every historical hold, confirmation, failure, expiry, cancellation.
5. `waitlist` FIFO waiting students and offered booking linkage.
6. `payment_attempts` asynchronous simulated outcomes and statuses.
7. `idempotency_keys` response replay and payload conflict detection.
8. `outbox` reliable RabbitMQ messages.
9. `booking_audit` append-only mutation trace; DB trigger blocks updates/deletes.

Do not change the unique seat or user indexes without separately proving safety.
For schema changes after initial deployment, create a new migration process:
adding files to `docker-entrypoint-initdb.d` will **not** migrate existing data.

## Critical invariants

- Every inventory write calls `lock_event()` first, then `reconcile_event()`.
- All seat decisions use SQL within the current transaction.
- `unique_active_seat` allows at most one active ticket for each physical seat.
- One student can have only one active hold/confirmation for the same concert.
- Payment `SUCCEEDED` requires an unexpired active hold at processing time.
- Rabbit messages may arrive more than once; processing must be idempotent.
- Responses to repeated mutation keys are saved with the state changes in
  the same transaction; never move the `idempotency_keys` write outside it.

## Local startup and execution

```bash
cp .env.example .env   # On Windows PowerShell: Copy-Item .env.example .env
# Edit .env and configure DB_PASSWORD and JWT_SECRET
docker compose up -d --build
docker compose ps
docker compose logs -f api worker
```

REST docs: <http://localhost:8080/docs>. PostgreSQL host port is localhost:5434.
Use `README.md` to register a user, reserve a seat, simulate payment and cancel.

## Verification checklist

- [ ] `python -m compileall -q app worker tests scripts`
- [ ] `python -m pytest -q tests/test_unit.py`
- [ ] `docker compose ps` shows healthy services
- [ ] `RUN_INTEGRATION=1 TEST_DATABASE_URL=... python -m pytest -q tests/test_integration.py -v`
- [ ] `TEST_DATABASE_URL=... python scripts/concurrency_probe.py`
- [ ] `docker compose exec -T postgres ... < scripts/invariants.sql`
- [ ] `k6 run ... loadtests/race.js` and capture real latencies
- [ ] Stop/restart RabbitMQ and Redis, ensure booking integrity remains correct
- [ ] Test backup and restore on isolated database

Do not mark runtime/integration/load outcomes PASS until these commands actually
run. The environment used to generate the project may lack Docker/PostgreSQL.

## What should be done next

1. Run Compose and resolve any version-specific container or SQL errors.
2. Capture real concurrency probe and test outputs in `docs/TEST_REPORT.md`.
3. Run k6 at increasing concurrency and record 95th/99th percentile latency,
   transaction throughput, lock contention and connection pool saturation.
4. If admission overload is observed, add request rate controls plus a bounded
   queue for new arrivals without changing seat uniqueness.
5. For production: TLS, external secrets, login rate limits, centralized logs,
   backup/restore drills and a real signed payment provider integration.

## Known limitations

- Redis freshness is bounded by a short TTL; its response is not an allocation promise.
- A contended event row serializes writes and can become a throughput bottleneck.
- No push notifications; users poll `/waitlist/{id}` for an offered seat.
- No real money charged/refunded; refund state is simulated.
- No observed load-test results should be inferred from scripts alone.
- Local Compose configuration uses plain HTTP (appropriate only for testing).

## Changing the project safely

When modifying booking flow, add a concurrent integration test first. Keep
all inventory changes within the same SQL transaction and event lock. When
changing worker code, test delayed and duplicate delivery, expiration and
RabbitMQ restart. When adding routes, validate identity and add to README's
API table. Update this file and TEST_REPORT after every significant change.


## Windows v1.1 performance checkpoint (2026-10-16)

The user successfully ran the API and PostgreSQL 18.6 natively on Windows using Python 3.13.15, passing five live integration tests, a smoke demo, a 30-student race and multiple k6 tests. In the latest profile, reservation average/p95 were 9.65/11.76 seconds at 20 VUs, versus registration 1.68/3.09 seconds. The v1.1 code adds `REDIS_ENABLED=0` as an explicit offline-cache mode to prevent Redis connection attempts within the event lock on hosts without Redis. This is a hypothesis-driven optimization, not yet confirmed by an after-change benchmark. No schema or booking workflow changes were made. See `docs/PERFORMANCE_WINDOWS.md` for exact run, tests and rollback. The user still needs to execute the after-change profile, confirm invariants, and eventually benchmark Redis/RabbitMQ and 10,000 attempts.
