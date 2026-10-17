# The Last Seat v1.3 · UI usability and safe test-event cleanup

- Streamlit now shows **Sign out** prominently in the main header and at the top of the sidebar.
- Removed the “Made for the CodeChef-VIT backend challenge” text.
- Click an available numbered seat to **reserve it immediately** via the existing FastAPI endpoint. 500 seats are split into 50-seat pages to keep UI responsive.
- `scripts/cleanup_test_event.py` can preview and, with explicit confirmation, remove a temporary integration or load-test event (such as event 13). It never removes the main concert and does not delete shared users.
- **No database schema change.** This add-on doesn't touch `app/`, `db/`, `.env`, `worker/`, or `loadtests/race.js`.

Read **`docs/V1_3_UI_AND_CLEANUP.md`** for Windows setup, cleanup, tests and limitations.
