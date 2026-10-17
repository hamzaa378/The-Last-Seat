# k6 booking load tests

`race.js` contains a **shared-iterations** scenario. Configure the number of active virtual users and the exact **number of attempted booking iterations** using `-e` flags. Each iteration registers a unique simulated student and then requests a reservation. It reports direct holds (`201`), waiting-list responses (`202`), server errors, and unexpected outcomes. HTTP 404 or 422 from a mistyped event ID is an invalid outcome and fails the configured threshold. A targeted seat may return `409` while other seats exist, which is treated as an expected conflict only in that mode.

Example against a **fresh** event ID, running native Windows FastAPI on port 8000:

```powershell
k6 run -e VUS=20 -e ITERATIONS=100 -e BASE_URL=http://127.0.0.1:8000 -e EVENT_ID=1 loadtests/race.js
```

Full 10,000 attempt example, **after creating a new 500-seat test event and replacing the ID**:

```powershell
k6 run -e VUS=200 -e ITERATIONS=10000 -e BASE_URL=http://127.0.0.1:8000 -e EVENT_ID=YOUR_NUMERIC_EVENT_ID --summary-export=loadtests/results_10000.json loadtests/race.js
```

Do not paste `<NEW_EVENT_ID>` literally. Use the actual numeric event ID. The script uses `maxDuration: 30m`, so ensure the run completes all 10,000 iterations and has zero `invalid_outcomes`. This models **10,000 total attempts with up to 200 concurrent virtual users**, not 10,000 simultaneous clients.

**Never use the real concert for destructive performance test setup.** The benchmark creates users, bookings and waitlist entries in PostgreSQL. After each test, inspect `GET /events/{id}/integrity` for `no_double_booking: true` and `not_oversold: true`. k6's `won_seat` counts holds, **not paid confirmations**. Real hold expiry and waitlist offers can change state while the test is running.

The user-provided measured result for event 13 is archived in [docs/TEST_REPORT.md](../docs/TEST_REPORT.md). Benchmark JSON is a local output, not included in the GitHub release source ZIP.
