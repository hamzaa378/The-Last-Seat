# v1.2 · UI checkpoint and safe continuation

The Last Seat backend already works on Windows with PostgreSQL 18.6, Python 3.13.15, FastAPI :8000, and a PostgreSQL-based background worker. Redis is intentionally disabled on Windows via `REDIS_ENABLED=0`. There is no need to run Docker, recreate `tickets`, or reseed 500 concert seats.

This add-on changes **API documentation presentation only** and introduces Streamlit as a separate HTTP client. The existing `app/service.py`, `app/database.py`, `app/idempotency.py`, `app/cache.py`, `worker/run.py`, and all `db/*.sql` files are **unchanged**.

## Runtime files

- `app/main.py`: existing endpoints plus friendly Swagger `/docs` renderer and metadata.
- `app/schemas.py`: sample field descriptions; same accepted request models.
- `app/static/swagger_theme.css`: local cosmetic Swagger theme.
- `frontend/streamlit_app.py`: Streamlit UI for guest browsing, accounts, reservations, simulated payments, cancellation, waitlist, audit and integrity.
- `frontend/api_client.py`: HTTP request handling, API error rendering, idempotency keys.
- `frontend/styles.css`: presentational styles, including display-only seat map.
- `frontend/requirements.txt`: optional Streamlit requirements; backend dependencies unchanged.
- `.streamlit/config.toml`: Streamlit theme.
- `scripts/start_api_windows.ps1`, `scripts/start_worker_windows.ps1`, `scripts/start_frontend_windows.ps1`: three no-Docker launchers.
- `scripts/check_ui_windows.ps1`: safe read-only health and docs checks.
- `tests/test_frontend_client.py`: six offline HTTP transport tests.
- `docs/STREAMLIT_GUIDE.md`, `docs/DEMO_SCRIPT.md`: setup and interview demo.

## Operator-provided evidence from 2026-10-17

- 5/5 live database integration tests passed **before** the UI addition.
- 10,000 k6 iterations with 200 concurrent VUs, event 13 (500 seats): 500 direct holds, 9,500 queue responses; 0% invalid outcomes; 0 HTTP errors; p95 4.47s; 4m46.5s total.
- Follow-up PostgreSQL integrity: `active_tickets=500`, `unique_active_seats=500`, `no_double_booking=True`, `not_oversold=True`.
- Snapshot queue states: WAITING 7,500, OFFERED 500, EXPIRED 1,500.
- These are backend measurements and are **not** frontend load measurements. No real money was charged.

## Safe startup

```powershell
# Run once in your existing virtual environment:
.\.venv313\Scripts\python.exe -m pip install -r frontend\requirements.txt

# Open 3 PowerShell windows and run one in each:
powershell -ExecutionPolicy Bypass -File .\scripts\start_api_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_worker_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend_windows.ps1

# In any extra window:
powershell -ExecutionPolicy Bypass -File .\scripts\check_ui_windows.ps1
```

## Outstanding verification

1. Install Streamlit and verify `http://127.0.0.1:8501` renders correctly on Windows.
2. Register/log in; reserve, confirm, cancel; check the audit and queue screens.
3. Rerun backend unit/integration suite against actual PostgreSQL. The UI package's new tests passed 6/6 offline.
4. Capture screenshots; document any Windows-specific Streamlit issues.
5. Redis-, RabbitMQ-, Nginx- and Docker-backed runtime bonuses are configured but **have not been demonstrated** in the Windows test run.

Important: Never publish `.env`, real passwords, access tokens, or database dumps containing real account records. Credentials previously pasted into chat should be rotated before deployment.
