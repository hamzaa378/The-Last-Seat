# Verification report — GitHub release v1.3

**Two evidence sources are distinguished throughout this report.** The user supplied PowerShell, pytest, k6 and PostgreSQL console output for the Windows machine. The GitHub packaging environment only re-ran source-level tests, not the Windows Postgres integration or Docker deployment.

## Consolidated verified figures

| Check | Observation | Evidence source |
|---|---|---|
| 30 simultaneous students, one seat | 1 held, 29 waitlisted, no double-booking | User's Windows console |
| Booking smoke demo | Hold → payment SUCCEEDED → booking CONFIRMED → cancelled; audit recorded | User's Windows console |
| Five integration cases | 5/5 passed in 53.06s **before v1.1 cache patch** | User's Windows console |
| 100 attempts, 20 VUs, before cache fix | Reservation average 9.65s, P95 11.76s | User's k6 output |
| 100 attempts, 20 VUs, Redis disabled | Reservation average 119.64ms, P95 327.49ms; 0 HTTP failures | User's k6 output |
| 10,000 attempts, 200 k6 VUs, fresh event 13 | 500 direct holds, 9,500 queued; 20,000 HTTP requests; 0 HTTP failures, 0 invalid outcomes | User's k6 output |
| Final full-load timing | 4m46.5s; HTTP average 2.80s, P95 4.47s, 69.80 HTTP req/s | User's k6 output |
| Event 13 post-load database integrity | Capacity 500, active holds 500, distinct active seats 500, no double booking, not oversold | User's `/events/13/integrity` output |
| Event 13 waitlist state counts | WAITING 7,500, EXPIRED 1,500, OFFERED 500 | User's PostgreSQL output |
| GitHub packaging unit/helper tests | **19 passed** | Python pytest run in packaging environment |

**Scope limitations:** The 10,000 attempts were sequentially distributed over 200 concurrent k6 virtual users. `won_seat` is a temporary hold, not a completed payment. Windows-native testing used `REDIS_ENABLED=0`; RabbitMQ, Redis, Docker, Nginx, cloud deployment and post-patch full integration tests have not been demonstrated here. Source-level tests do not demonstrate UI visual correctness. Temporary event 13 may subsequently be deleted from local PostgreSQL without affecting the archived figures above.

---

# Historical test template and execution notes

**Status at artifact generation:** Python compilation completed successfully and
`pytest tests/test_unit.py` passed **5 tests** (0.27 s in the generation
environment). Docker/PostgreSQL integration and load tests were not executed
because Docker and dependency downloads were unavailable. The measurements below are intentionally left
blank until they have been collected by executing the project.

## Environment to record

| Item | Value to fill in |
|---|---|
| Test date | |
| Host OS and kernel | |
| CPU/RAM | |
| Docker version | |
| PostgreSQL version | |
| Python version | |
| Git commit SHA | |

## Execution log

| Test | Command | Actual result |
|---|---|---|
| Static syntax | `python -m compileall -q app worker tests scripts` | PASS; compiled without syntax errors |
| Unit tests | `python -m pytest -q tests/test_unit.py` | PASS; 5 passed in 0.27 s |
| Concurrency / FIFO | `RUN_INTEGRATION=1 ... pytest tests/test_integration.py -v` | Pending |
| Direct race (1 seat / 30 students) | `python scripts/concurrency_probe.py` | Pending |
| Double booking index query | `scripts/invariants.sql` | Pending |
| 100 VU load | `k6 run ... loadtests/race.js` | Pending |
| 10k attempts | Configure k6 shared-iterations as described in loadtests README | Pending |
| Restart Redis | `docker compose stop redis` and retry bookings | Pending |
| Restart broker | `docker compose stop rabbitmq` and observe scanner/outbox | Pending |

## Capture after executing k6

- Total HTTP requests:
- Total successful reservations / queue entries / 409 conflicts:
- HTTP 5xx errors:
- p50 latency:
- p95 latency:
- p99 latency:
- Requests/second:
- Active booking uniqueness violations:
- Max observed database connections / lock wait:

## Expected correctness assertions (not measurements)

- On a freshly created **one-seat** event, 30 unique student requests should
  produce **one** initial HTTP 201 hold and **29** HTTP 202 waitlist results.
  A failure to meet either condition means the test did not pass.
- SQL checks `double_booked_seats=0`, `duplicate_active_users=0`.
- The first waiting person should get an `OFFERED` seat after cancellation.
- Same-key concurrent requests must return a single booking ID.
- A payment delivered after expiration must not confirm an expired hold.

Paste actual command output and timings here. Avoid claiming a result merely
because a test script contains the expected assertions.


## Verified Windows console results (2026-10-16)

See [`PERFORMANCE_WINDOWS.md`](PERFORMANCE_WINDOWS.md) for exact measured baseline and profiling results supplied by the project operator. The original blank Docker-template above is retained as a historical packaging record. Redis-enabled and RabbitMQ-enabled operation remain unverified. The operator subsequently completed a 10,000-attempt run as recorded below.

## Operator-provided Windows verification, through 2026-10-17

These measurements are taken from the user's actual PowerShell, pytest and k6 console output in the conversation. They were **not rerun** in the environment used to package the Streamlit UI.

| Test | Observed result |
|---|---|
| Native Windows environment | Python 3.13.15, PostgreSQL 18.6, FastAPI at port 8000 |
| Booking smoke demo | PASS: hold, simulated payment success, confirmation, audit, cancellation, integrity |
| One-seat 30-student race | 1 direct hold, 29 waiting, no oversell |
| Integration suite | 5/5 passed in 53.06s (before cache patch) |
| 20-VU 100-iteration profile before Redis-disabled patch | Reservation avg 9.65s, p95 11.76s |
| 20-VU 100-iteration profile after patch | Reservation avg 119.64ms, p95 327.49ms; HTTP 0% failed |
| 10,000 attempts (event 13), 200 VUs | 500 holds, 9,500 waitlisted, zero invalid outcomes and 5xx |
| k6 HTTP performance at 10k attempts | 20,000 HTTP requests, 69.80 req/s, avg 2.80s, p95 4.47s |
| 10k benchmark execution time | 4m46.5s |
| Post-run event 13 integrity | Capacity=500, active=500, unique active seats=500, no double booking=True, not oversold=True |
| Waitlist distribution snapshot | WAITING=7,500; EXPIRED=1,500; OFFERED=500; total=9,500 |

**Interpretation limits:** 10,000 total iterations with 200 concurrent VUs, not 10,000 simultaneous users. `won_seat` counts successful holds, not confirmed payments. This was a Windows-native PostgreSQL/worker run with Redis intentionally disabled, not proof of Redis, RabbitMQ, Nginx or Docker runtime integration. The post-patch full integration regression suite has not been supplied yet.

## v1.2 UI verification

- New pure HTTP client tests in `tests/test_frontend_client.py`: **6 passed** in package preparation.
- Python static compilation of the changed source: **passed**.
- Streamlit visual/manual end-to-end testing: **not completed** here (Streamlit not installed in build environment).
- Backend database integration after Swagger UI changes: should be rerun in the user's PostgreSQL-backed Windows environment. The update only changes API metadata, a docs route, a stylesheet, and the Pydantic examples; booking logic was not edited.
