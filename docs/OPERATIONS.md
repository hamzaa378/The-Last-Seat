# Deploying, observing and recovering the service

## Local deployment

1. Copy `.env.example` to `.env`, assign `DB_PASSWORD` and `JWT_SECRET`.
2. Run `docker compose up -d --build`.
3. Wait for `docker compose ps` to show postgres, redis and api healthy.
4. Open `http://localhost:8080/docs`; RabbitMQ management is at
   `http://localhost:15672` (exposed only on 127.0.0.1).
5. Run the tests in `README.md` and capture their stdout.

The Nginx reverse proxy publishes port 8080. PostgreSQL port 5434 is
bound to the local loopback for tests, not exposed on the host's public
interface. Never make DB or broker management ports publicly accessible.

## Backups and restore

From a shell in the project directory:

```bash
# Logical backup: user, seats, booking history, waitlist and audit
# Supply a safe output path and keep it out of Git.
docker compose exec -T postgres pg_dump -U tickets -d tickets -Fc > tickets.backup

# For a RESTORE DRILL, start from a stopped app/worker and an EMPTY target DB.
# A custom-format dump must be restored with pg_restore, not psql.
# Example if you have explicitly created a fresh, empty 'tickets_restore' DB:
docker compose exec -T postgres createdb -U tickets tickets_restore
cat tickets.backup | docker compose exec -T postgres pg_restore -U tickets \
    -d tickets_restore --no-owner --no-acl
```

For Windows PowerShell, do not use shell redirection to create a binary
custom-format backup because of possible encoding transformations. Use
`docker compose exec postgres pg_dump -U tickets -d tickets -Fc -f /tmp/tickets.backup`
and `docker cp` from the container, or use a plain-text SQL backup with a
supported binary-safe tool. A restore drill must be performed before claiming
recovery readiness.

**Warning:** `docker compose down -v` deletes the PostgreSQL data volume.
A live backup is not the same as a tested restore.

## Fault injection ideas

| Failure | Expected system behavior | How to investigate |
|---|---|---|
| Redis stopped | Seat GETs fall back to SQL; booking still works | `docker compose stop redis`, test GET + reserve |
| RabbitMQ stopped | `outbox` fills; due-payment scanner still processes eligible payments | `docker compose stop rabbitmq`, check worker logs and payment API |
| Worker stopped | Holds may linger until it returns; new writes reconcile their event | `docker compose stop worker`, wait for TTL, submit a reservation |
| API container restarted | Tokens and bookings remain valid (PostgreSQL persists state) | `docker compose restart api` |
| Same request repeated | Stable stored response | Reuse identical `Idempotency-Key` |
| Message duplicated | No extra payment/confirmed ticket | Worker checks `PENDING` status under lock |

After tests, restore paused services with `docker compose start redis rabbitmq worker`.

## Readiness vs liveness

`/health/live` checks the HTTP process itself; `/health/ready` performs a
PostgreSQL query. Redis and RabbitMQ are not readiness prerequisites for API
inventory safety, because Redis is best effort and outbox stores broker work.
The worker must be running eventually for timely payments and expiration.

## Public cloud deployment recipe (not executed here)

For a publicly reachable domain:

1. Provision a host/cluster and managed PostgreSQL, or persistent volumes with
   regularly tested backups.
2. Store credentials in a secret manager; don't commit `.env`.
3. Put the reverse proxy behind HTTPS with a real TLS certificate.
4. Use a nondefault RabbitMQ password and a dedicated broker network.
5. Use egress, proxy and app rate limits, admission control and anti-bot policy.
6. Configure centralized structured logs, metrics, and alerting.
7. Set resource limits and database connection budgets before scaling API workers.
8. Migrate schema with controlled versioned migrations rather than deleting DB volumes.
9. Run tests against a staging database and keep load-test data out of production.
10. Apply a real payment-provider security model before charging actual users.

No external cloud provider account or deployment URL is included. The delivered
Compose stack is a complete local/containerized deployment.

## Performance knobs

- `HOLD_SECONDS`: reservation TTL (default 120s).
- `PAYMENT_DELAY_SECONDS`: default synthetic delayed payment wait (10s).
- API Uvicorn worker count: currently 2.
- Per-process PostgreSQL pool: 1 to 12; 2 API workers + 1 background process.
- Redis snapshot TTL: 2s in `app/config.py`.
- Worker's reconcile interval: approximately 2s.

Resource estimates and high-load tuning must be measured on the target host.
The event row is the intended write bottleneck; blindly increasing worker
counts may worsen lock contention.
