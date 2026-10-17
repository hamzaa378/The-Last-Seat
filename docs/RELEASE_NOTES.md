# The Last Seat v1.3 — GitHub release notes

## Release scope

Complete source release for FastAPI REST API, PostgreSQL data model, a simulated-payment and expiration worker, Redis and RabbitMQ integration code, Docker Compose/Nginx configuration, custom Swagger UI, and optional Streamlit seat booking portal.

## Student experience

- Seat map buttons for available numbered seats, 50 seats per section
- Sign out visible at the top and in the sidebar
- No attribution footer in the student-facing UI
- Login, reservation, payment tracking, cancellation, audit and waitlist status
- Temporary test events hidden in student selector by default

## Reliability and validation

- PostgreSQL authoritative seat allocation with per-event locking and unique indexes
- Durable waiting list with expiring offers
- Idempotency keys, payment simulation and audit history
- `REDIS_ENABLED=0` switch for native Windows development without Redis service
- 19 source-level tests passed locally during GitHub release packaging
- User reported: 5 integration tests passed before Redis-disabled patch; 30-user one-seat test had 1 winner and 29 waitlisted
- User reported: 10,000 booking attempts using 200 k6 VUs, 500 holds, 9,500 queued, 0 invalid/failed HTTP outcomes
- User reported: post-run event 13 invariant report found 500 unique active held seats with no overselling

## Disclosure

The packaging environment did not run the PostgreSQL, Docker or 10,000-iteration integration workload again. Redis/RabbitMQ runtime, Docker build and full manual frontend E2E still require independent validation. No changes were made to core booking transactions during this GitHub release packaging.
