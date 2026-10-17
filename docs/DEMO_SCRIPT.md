# Five-minute demo script · Version 1.2

## Preparation

In three separate Windows PowerShell terminals from the project root, start:

1. `powershell -ExecutionPolicy Bypass -File .\scripts\start_api_windows.ps1`
2. `powershell -ExecutionPolicy Bypass -File .\scripts\start_worker_windows.ps1`
3. `powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend_windows.ps1`

Open `http://127.0.0.1:8501` and `http://127.0.0.1:8000/docs`. Ensure `/health/ready` returns `ready`.

## Timeline

| Time | Live action | What to explain |
|---|---|---|
| 0:00–0:30 | Show event picker, capacity, color-coded seat map | Availability snapshot vs actual SQL allocation |
| 0:30–1:15 | Register a new demo user | JWT authentication and owner-only ticket endpoints |
| 1:15–2:00 | Choose any available seat; reserve it | Time-limited hold and unique seat index |
| 2:00–2:45 | Open My Tickets; choose `success` simulated payment | Worker processes payment asynchronously; no real money |
| 2:45–3:15 | Refresh status and open audit trail | Complete history and immutable audit design |
| 3:15–3:45 | Cancel the booking and refresh | Seat release; FIFO waitlist receives offers |
| 3:45–4:30 | Show Swagger guide and System status | Idempotency keys, OpenAPI docs and live invariants |
| 4:30–5:00 | Show actual k6 report from `docs/TEST_REPORT.md` | 200 VUs, 10,000 iterations, 500 holds / 9,500 waitlisted, zero 5xx |

## Interview talking points

- PostgreSQL is authoritative, not Streamlit, Redis or RabbitMQ.
- `SELECT ... FOR UPDATE` on the event row ensures a consistent ordering for allocations.
- A partial unique index on active bookings provides an independent double-booking backstop.
- Idempotency keys make client retries safe when the same key and payload are reused.
- All 500 seats can be held simultaneously; confirmation requires the payment simulator to succeed before expiration.
- The speedup after `REDIS_ENABLED=0` on Windows illustrates why a failed cache call must not block the SQL critical section.
- The 10,000-attempt benchmark was 200 *concurrent virtual users* across 4m46.5s, not 10,000 simultaneous connections.
- Pending bonuses: Redis- and RabbitMQ-enabled integration and public deployment have not been verified locally.

## Screenshots to capture (optional)

- Seat map and status cards
- Held booking with expiration deadline
- Confirmed payment and audit trail
- Waiting-room state or offered seat
- Swagger documentation banner
- Console output of the verified k6 test and the PostgreSQL integrity endpoint

**Do not** include real database passwords, bearer tokens or personal account emails in screenshots.
