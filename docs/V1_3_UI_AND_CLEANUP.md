# The Last Seat v1.3 · Streamlit UX and safe test-event cleanup

No changes to FastAPI REST endpoints, concurrency transactions, PostgreSQL schema, Redis setting, worker, or k6 scripts.

## What's changed

- **Sign out visible at top:** appears in the main content header whenever signed in and also near the top of the sidebar; signing out clears the session token but does not cancel existing bookings.
- **Removed the attribution footer:** the sidebar no longer says “Made for the CodeChef-VIT backend challenge.”
- **Click to reserve:** the seat grid now uses native Streamlit buttons. Click an available numbered seat to send an immediate authenticated `POST /events/{id}/reservations` with `{'seat_number': number}` and a new idempotency key. The server returns `201` with a hold or `202` with a waiting-list entry. Busy seats are disabled.
- **50 seats per view:** choose a numbered section from the dropdown instead of loading 500 clickable widgets at once. No visual snapshot overrides the PostgreSQL booking decision.
- **Reserve best available:** remains available as a separate action.
- **Test-event cleanup:** new `scripts/cleanup_test_event.py` defaults to read-only and requires exact event ID, safe test-event slug, `--execute`, and typed confirmation. It refuses to delete the main concert or an event containing confirmed tickets.

## Install into the existing working Windows project

1. Stop the Streamlit app (Ctrl+C). Stop FastAPI and the payment worker **only when executing database cleanup**.
2. Back up `frontend/streamlit_app.py` and `frontend/styles.css` if you've customized them.
3. Extract `The_Last_Seat_v1_3_UI_Cleanup_Addon.zip` into `C:\Users\hamza\Downloads\the last seat` with overwrite when prompted. This add-on does **not** replace `app`, `.env`, `db`, `loadtests`, or your corrected k6 benchmark.
4. Restart the Streamlit frontend:

```powershell
cd 'C:\Users\hamza\Downloads\the last seat'
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend_windows.ps1
```

5. Open `http://127.0.0.1:8501`, log in, select a 50-seat block and click an available numbered seat. Check **My Tickets** for payment and history.

## Delete the temporary load-test event, event 13

**The script cannot access the PostgreSQL database on your Windows computer from this ZIP.** You must run it locally. Data deletion is permanent. Export a backup first if you may want to inspect the old 10,000-user benchmark, and retain the k6 JSON/results screenshots.

1. Stop FastAPI and the payment worker so they don't process any bookings while the event is being removed. Close Streamlit or make sure nobody is booking the event.
2. In the project directory, list temporary events and preview ID 13:

```powershell
.\.venv313\Scripts\python.exe .\scripts\cleanup_test_event.py --list
.\.venv313\Scripts\python.exe .\scripts\cleanup_test_event.py --id 13
```

3. Check that ID 13 belongs to the load test and not a real concert. To delete *only* event 13:

```powershell
.\.venv313\Scripts\python.exe .\scripts\cleanup_test_event.py --id 13 --execute
```

4. Type exactly `DELETE 13` when prompted. The cleanup removes related seats, bookings, payments, waiting entries, event-specific idempotency records, outbox payment messages and that test event's audit logs in one transaction. It **does not delete users** because some accounts can participate in other events.
5. Verify `--list` no longer includes 13, and `GET /events` no longer lists the event after restarting the API.

**Important:** The booking audit table is append-only and has a delete-blocking trigger. The cleanup utility temporarily disables that named trigger *within its PostgreSQL transaction* and restores it before commit. If anything errors, rollback reverses both the deletion and trigger change. Don't use general-purpose `TRUNCATE ... CASCADE`, and don't delete event 1.

Integration-test events have `test-` slugs; the race probe uses `race-`. Use `--list` and delete *only the IDs you explicitly recognize*; the script deliberately has no `--delete-all` mode.

## Testing

```powershell
.\.venv313\Scripts\python.exe -m pytest tests\test_seat_ui.py tests\test_cleanup_guard.py tests\test_frontend_client.py -v
```

The new UI tests use pure Python helpers and mock HTTP transports. Test the interactive buttons manually in a browser; the script never directly writes to PostgreSQL. It is designed for local demos, not public production deployment.
