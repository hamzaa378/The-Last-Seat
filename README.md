# The Last Seat

**Ticket reservation platform · FastAPI + PostgreSQL + Streamlit**

A ticket booking REST API for a 500-seat college concert with a 10,000-student
opening rush. Seats can be held, paid for (simulation), cancelled, released,
and automatically offered to the next student in a first-in-first-out waiting queue.

The design goal is **no double booking under concurrent requests**, even across
multiple API processes and duplicate background messages. The backend exposes Swagger/OpenAPI documentation, and v1.3 includes a Streamlit student portal that calls the same tested REST endpoints. The portal has clickable seats, visible Sign out, waitlist tracking and simulated payments.

## Quick start — Windows, no Docker

Prerequisites: **Python 3.13 (standard 64-bit build)** and a running **PostgreSQL 18** server. This is the setup used for the reported live verification. Install [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/) only for load testing.

1. Extract the source ZIP, open PowerShell in the extracted `the-last-seat` folder, and create the Python environment:

   ```powershell
   py -3.13 -m venv .venv313
   .\.venv313\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv313\Scripts\python.exe -m pip install -r frontend\requirements.txt
   ```

2. Using `psql` as a PostgreSQL administrator, create a dedicated `tickets` role and database. Set the role password using `\password tickets`, not a copied real credential. **Run these two SQL files only for a brand-new database**:

   ```powershell
   & 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -h 127.0.0.1 -U tickets -d tickets -v ON_ERROR_STOP=1 -f db\001_schema.sql
   & 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -h 127.0.0.1 -U tickets -d tickets -v ON_ERROR_STOP=1 -f db\002_seed.sql
   ```

   The seed contains one concert with 500 seats. **Existing installations must skip database creation and seeding.**

3. Open three PowerShell windows at the repository root. Run one command per window (the API and worker prompt for the `tickets` password):

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start_api_windows.ps1
   powershell -ExecutionPolicy Bypass -File .\scripts\start_worker_windows.ps1
   powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend_windows.ps1
   ```

4. Open the **student portal** at <http://127.0.0.1:8501> and **Swagger API docs** at <http://127.0.0.1:8000/docs>. Verify the API health at <http://127.0.0.1:8000/health/ready>.

5. Run lightweight tests:

   ```powershell
   .\.venv313\Scripts\python.exe -m pytest -q tests\test_unit.py tests\test_cache_disabled.py tests\test_frontend_client.py tests\test_seat_ui.py tests\test_cleanup_guard.py
   ```

The Windows launch scripts set `REDIS_ENABLED=0` because Redis is not installed locally. The database remains the authoritative source for seat allocation; the worker handles simulated payments and reservation expiration. For detailed Windows instructions and troubleshooting, see [docs/STREAMLIT_GUIDE.md](docs/STREAMLIT_GUIDE.md). **A Windows launch of this backend does not test the Redis or RabbitMQ bonus integration.**

---

## What is included

| Requirement | Where it lives |
|---|---|
| View seats and book a specific or first-available seat | `GET /events/{id}/seats`, `POST /events/{id}/reservations` |
| Prevent double booking | PostgreSQL event row lock + partial unique index |
| Expiring holds | `hold_expires_at`, transaction reconciliation, worker sweeper |
| Cancellation and seat reallocation | `POST /bookings/{id}/cancel`, FIFO promotion |
| Success, failure and delayed simulated payments | `POST /bookings/{id}/payments`, background worker |
| Repeated/concurrent requests | Transactional `Idempotency-Key` table |
| History and status | `/bookings`, `/bookings/{id}`, `/payments/{id}`, `/waitlist/{id}` |
| PostgreSQL | `db/001_schema.sql`, `db/002_seed.sql` |
| Redis bonus | Short-lived seat snapshot cache (never the seat authority) |
| Waiting queue bonus | Durable database-backed waitlist with automatic offers |
| RabbitMQ bonus | Durable message publication through the transactional outbox |
| Payment / booking idempotency bonus | `app/idempotency.py` |
| Reverse-proxy bonus | Nginx on host port 8080 |
| Container deployment configuration | Docker Compose and Nginx included; Docker runtime not verified in the operator’s environment |
| Additional differentiators | Immutable audit log, self-healing payment scanner, invariant-report endpoint |

## Architecture at a glance

```mermaid
flowchart LR
  Student[Student / Client] --> Nginx[Nginx :8080]
  Nginx --> API[FastAPI - 2 workers]
  API --> DB[(PostgreSQL - source of truth)]
  API -. best effort .-> Redis[(Redis - 2s snapshots)]
  DB --> Outbox[Transactional outbox table]
  Worker[Python background worker] --> Outbox
  Worker --> DB
  Worker <-->|persistent messages| Rabbit[(RabbitMQ)]
```

**Seat ownership is never stored in Redis or RabbitMQ.** Only the PostgreSQL
transaction is allowed to allocate, confirm, expire or cancel a booking.


## Student portal and enhanced Swagger (v1.3)

**Optional frontend:** Streamlit on `http://127.0.0.1:8501` provides a seat map, registration/login, reservation, simulated payment, waitlist tracking, cancellation, booking audit and live integrity status. FastAPI's styled `/docs` on `http://127.0.0.1:8000/docs` remains the developer console.

On the existing native Windows install (`tickets` database already initialized):

```powershell
.\.venv313\Scripts\python.exe -m pip install -r frontend\requirements.txt
# In three separate PowerShell windows:
powershell -ExecutionPolicy Bypass -File .\scripts\start_api_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_worker_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend_windows.ps1
```

The Windows scripts explicitly disable Redis when unavailable, while PostgreSQL remains the seat authority. **Do not reinitialize the `tickets` database.** Full instructions in [docs/STREAMLIT_GUIDE.md](docs/STREAMLIT_GUIDE.md), demo plan in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

### User-reported Windows performance evidence (2026-10-17)

For a new 500-seat event (ID 13), a k6 run with **200 VUs and 10,000 iterations** recorded **500 holds, 9,500 waitlist responses, 0 invalid outcomes, 0 HTTP errors** and 20,000 HTTP requests in **4m46.5s**. Post-run PostgreSQL integrity returned both `no_double_booking=True` and `not_oversold=True`. These results were provided from the operator's Windows environment; this UI package did not reproduce the large load test. See [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## 1. Installation: Docker Desktop (alternative)

Requirements: Docker Desktop with Compose v2, at least 2 GB free memory,
and ports **8080**, **5434**, and **15672** available. Windows 11, macOS and
Linux are supported. No existing PostgreSQL installation is needed.

```bash
unzip the-last-seat.zip
cd the-last-seat
cp .env.example .env
# Edit .env: assign DB_PASSWORD and a long, random JWT_SECRET.
docker compose up -d --build
```

Windows PowerShell equivalent:

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up -d --build
```

Open:

- Swagger UI: <http://localhost:8080/docs>
- OpenAPI schema: <http://localhost:8080/openapi.json>
- Readiness: <http://localhost:8080/health/ready>
- RabbitMQ UI: <http://localhost:15672> (user `tickets`, password from `.env`)

The `postgres` container executes both `db/001_schema.sql` and `db/002_seed.sql`
**only when its data volume is first created**. It seeds one event with **500 seats**.
Subsequent `docker compose up` calls preserve the database.

Useful commands:

```bash
docker compose ps
docker compose logs -f api worker
docker compose exec postgres psql -U tickets -d tickets
# Stop without deleting data
docker compose down
# Dangerous: removes all stored data; only use for a deliberate reset
docker compose down -v
```

For local Python tests and the concurrency probe:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q tests/test_unit.py
```

## 2. Try a complete booking

All commands below use curl (`curl.exe` in Windows PowerShell if `curl` is aliased).
Use the returned IDs and tokens; don't copy placeholder IDs literally.

**Register**

```bash
curl -X POST http://localhost:8080/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"student1@example.com","password":"StrongPassword123!"}'
```

Response includes a `user_id`, `access_token`, and `token_type`.

**List events and seats**

```bash
curl http://localhost:8080/events
curl http://localhost:8080/events/1/seats
```

**Reserve a seat.** Replace `YOUR_TOKEN` with the access token from registration.
Each new mutation gets a new, unique `Idempotency-Key`. Reuse the *same* key
only if repeating the *same* operation.

```bash
curl -X POST http://localhost:8080/events/1/reservations \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Idempotency-Key: reservation-student1-001' \
  -H 'Content-Type: application/json' \
  -d '{"seat_number":10}'
```

HTTP **201** means the seat was held and response includes `booking_id` and
`hold_expires_at`. Omit seat number or send `{}` to take the first free seat.
When the event is fully held/confirmed, HTTP **202** registers the user in the
waiting queue instead, returning a `waitlist_id`. If only the *chosen* seat
is occupied while other seats remain free, the server returns HTTP **409**.

**Start a simulated payment**

```bash
curl -X POST http://localhost:8080/bookings/BOOKING_ID/payments \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Idempotency-Key: payment-student1-001' \
  -H 'Content-Type: application/json' \
  -d '{"outcome":"delayed_success","delay_seconds":5}'
```

Returns HTTP **202** with `payment_id`. This is *not yet confirmation*.
The worker handles the outcome asynchronously, and after the delay:

```bash
curl -H 'Authorization: Bearer YOUR_TOKEN' \
  http://localhost:8080/payments/PAYMENT_ID
curl -H 'Authorization: Bearer YOUR_TOKEN' \
  http://localhost:8080/bookings/BOOKING_ID
```

Use `"outcome":"failure"` to simulate immediate failure, or
`"outcome":"delayed_failure"` for delayed failure. **No real payment or
refund service is integrated**, no real money changes hands.

**Leave the waiting queue (optional)**

If you joined a queue but no longer want a seat, call
`POST /waitlist/WAITLIST_ID/leave` with a fresh `Idempotency-Key`. If you
already received an `OFFERED` hold, it is released and passed on immediately.

**Cancel and release the seat**

```bash
curl -X POST http://localhost:8080/bookings/BOOKING_ID/cancel \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Idempotency-Key: cancellation-student1-001'
```

If someone is waiting, the next person automatically receives a new hold.
Their waitlist `status` becomes `OFFERED`, and `offered_booking_id` points to
the ticket they must pay for before expiry.

**Inspect the audit and database invariant report**

```bash
curl -H 'Authorization: Bearer YOUR_TOKEN' \
  http://localhost:8080/bookings/BOOKING_ID/audit
curl http://localhost:8080/events/1/integrity
```

The integrity endpoint checks that active tickets don't exceed capacity and
that the number of active tickets equals the number of distinct seats.

## 3. REST API reference

| Method | Route | Auth | Idempotency-Key | Result |
|---|---|---|---|---|
| POST | `/auth/register` | No | No | 201 user and token |
| POST | `/auth/login` | No | No | 200 token |
| GET | `/events` | No | No | 200 events |
| GET | `/events/{event_id}/seats` | No | No | 200 availability snapshot |
| POST | `/events/{event_id}/reservations` | Bearer | Yes | 201 HELD / 202 WAITING |
| POST | `/events/{event_id}/waitlist` | Bearer | Yes | 202 WAITING (only when no seats) |
| GET | `/waitlist/{wait_id}` | Bearer | No | 200 queue state and position |
| POST | `/waitlist/{wait_id}/leave` | Bearer | Yes | 200 opt out and release any offer |
| GET | `/bookings` | Bearer | No | 200 last 200 bookings |
| GET | `/bookings/{booking_id}` | Bearer | No | 200 booking status |
| POST | `/bookings/{booking_id}/payments` | Bearer | Yes | 202 PENDING |
| GET | `/payments/{payment_id}` | Bearer | No | 200 payment state |
| POST | `/bookings/{booking_id}/cancel` | Bearer | Yes | 200 cancellation |
| GET | `/bookings/{booking_id}/audit` | Bearer | No | 200 append-only event history |
| GET | `/events/{event_id}/integrity` | No | No | 200 inventory invariant report |
| GET | `/health/live`, `/health/ready` | No | No | 200 service health |

`401/403` unauthorized, `404` unknown or not owned, `409` business conflict,
`422` input validation and invalid key length. Ownership checks deliberately
return 404 for another user's booking/payment information.

### Reservation status transitions

```text
            +--------> CONFIRMED --cancel--> CANCELLED
            |
HELD ------+----expire---------------------> EXPIRED
            |
            +----failed payment------------> FAILED
            |
            +----cancel--------------------> CANCELLED

WAITING ----offered---> OFFERED ----paid---> FULFILLED
                           |
                           +--timeout------> EXPIRED
                           +--cancel-------> CANCELLED
```

A successful payment can only confirm a still-active, unexpired hold. If a
simulated success arrives too late, the payment is `TIMED_OUT` and the seat is
not taken back from its new holder.

## 4. Tests and load testing

Tests are **provided**, but results must come from actually running them.

```bash
# Fast unit tests
python -m pytest -q tests/test_unit.py

# Bash integration test example (Docker services must already be running)
export RUN_INTEGRATION=1
export TEST_DATABASE_URL='postgresql://tickets:YOUR_PASSWORD@localhost:5434/tickets'
export BASE_URL=http://localhost:8080
python -m pytest -q tests/test_integration.py -v

# Quick sequential example (register -> hold -> pay -> cancel)
python scripts/smoke_demo.py

# Separate 30-student, one-seat concurrency probe
python scripts/concurrency_probe.py --base http://localhost:8080

# Invariants directly against PostgreSQL
docker compose exec -T postgres psql -U tickets -d tickets \
  -f /dev/stdin < scripts/invariants.sql

# k6 rush test (requires k6 installed on your host)
k6 run -e BASE_URL=http://localhost:8080 -e EVENT_ID=1 loadtests/race.js
```

PowerShell environment variables:

```powershell
$env:RUN_INTEGRATION='1'
$env:TEST_DATABASE_URL='postgresql://tickets:YOUR_PASSWORD@localhost:5434/tickets'
$env:BASE_URL='http://localhost:8080'
python -m pytest -q tests/test_integration.py -v
```

See [loadtests/README.md](loadtests/README.md). The probe is a **correctness
check**, not a statistically meaningful throughput benchmark. Real latencies,
throughput and 10k-run outcomes must be measured on the reviewer's machine.

## 5. Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): concurrency reasoning, scalability, failure recovery
- [docs/DIAGRAMS.md](docs/DIAGRAMS.md): ERD, sequence diagrams, booking workflow
- [docs/DECISIONS.md](docs/DECISIONS.md): tradeoffs and limitations
- [docs/OPERATIONS.md](docs/OPERATIONS.md): deployment, backups, outages, scale-up
- [docs/HANDOVER.md](docs/HANDOVER.md): complete file guide and continuation checklist
- [docs/TEST_REPORT.md](docs/TEST_REPORT.md): reproducible evidence template and honest test status

## 6. Known boundaries

- **Simulated payments**; no payment provider, escrow, chargebacks or real refunds.
- Development HTTP endpoint. Add TLS, login rate limiting, proper secrets and
  observability before public deployment.
- Single-event lock serializes allocations deliberately; multi-event bookings
  can run concurrently, but one highly contested concert has a throughput ceiling.
- Redis snapshots can be briefly stale (default <= 2 seconds); writes always
  re-check PostgreSQL under a transaction.
- Users poll for waitlist offers; no external push notification integration.
- Holding one active seat per user per concert is an explicit anti-hoarding rule.
- No public cloud deployment has been verified. The later Windows-native load results are recorded in docs/TEST_REPORT.md.

This project favors understandable, enforceable invariants over an elaborate
architecture with correctness gaps.


## Windows native startup and performance profiling

For the verified Docker-free PostgreSQL 18 + Python 3.13 setup and the optional `REDIS_ENABLED=0` offline cache optimization, see [`docs/PERFORMANCE_WINDOWS.md`](docs/PERFORMANCE_WINDOWS.md). That document includes observed k6 latencies, an A/B procedure, rollback steps and security notes. No schema changes are required.


## Windows Streamlit UI v1.3 and test-event cleanup

The student portal at `http://127.0.0.1:8501` has a prominent **Sign out** button, clickable numbered seats (50 per section), automatic allocation, and a cleaner student-facing event list. The tested FastAPI booking system is unchanged. Use `scripts/cleanup_test_event.py --list` to preview temporary events and `--id 13` for a dry-run preview before deleting the benchmark event. Read `docs/V1_3_UI_AND_CLEANUP.md` before making any database changes.


## GitHub publication

The repository is designed to be uploaded as **source files, not as a ZIP inside GitHub**. Start at [docs/GITHUB_UPLOAD.md](docs/GITHUB_UPLOAD.md) for the Windows publishing walkthrough (web UI and Git CLI), privacy checks and a suggested repository description. The distributable ZIP contains no real database, virtual environment, secrets, or user data.

## Verified evidence and limits

See [docs/TEST_REPORT.md](docs/TEST_REPORT.md) for operator-provided measurements and how they were obtained. The major local test used **10,000 total iterations with 200 k6 virtual users**, against a fresh 500-seat event: 500 direct holds and 9,500 waiting-list admissions. Zero invalid booking outcomes and zero HTTP failures were reported; a post-run PostgreSQL integrity query confirmed no double bookings and no overselling. The test used **simulated payments**, not real money. The temporary event is not included in the repository. Redis, RabbitMQ, Docker and public cloud runtime integration remain unverified on the operator's Windows system.

## License

No open-source license is included. The repository owner should choose and add a license if they intend to grant reuse rights.
