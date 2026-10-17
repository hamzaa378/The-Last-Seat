# Technical architecture, correctness and scaling

## Why the event row lock?

The race we must avoid is:

1. Student A reads `seat 10 is free`.
2. Student B reads `seat 10 is free`.
3. Both attempt to create a ticket.

Ordinary read-then-write code is unsafe. In this project every operation that
changes allocation starts with `SELECT ... FROM events WHERE id=? FOR UPDATE`.
Only one transaction can hold that particular event lock at a time.

Within the lock, the service expires old holds, reoffers seats to people in the
waitlist, checks active bookings, allocates a seat and commits. Other requests
wait for the lock and then see the committed result.

The partial unique index `unique_active_seat` independently prevents two
bookings with status `HELD` or `CONFIRMED` from using the same seat. It is
an essential defense if someone accidentally adds an unlocked code path.

### Formal invariants

- I1: For any seat `s`, number of bookings with seat `s` and status
  `HELD` or `CONFIRMED` must be **at most one**.
- I2: For any event `e` and student `u`, number of active bookings must
  be **at most one**.
- I3: A `CONFIRMED` booking must come from a valid, unexpired `HELD` booking
  whose simulated payment returned success.
- I4: Replaying an identical `(user, scope, idempotency-key)` request must
  return the same saved response instead of creating another resource.
- I5: Offers go to the earliest `WAITING` row (`joined_at, id` ordering).
- I6: Expired holds no longer block allocation after reconciliation.

The SQL schema enforces I1 and I2 directly. Event locking + state checks enforce
I3, I5 and I6. The unique idempotency primary key and the transaction enforce I4.

## Expiration and clock semantics

The database sets `hold_expires_at` with `clock_timestamp()` and the
configured hold TTL. A periodic worker checks each event every ~2 seconds,
under its event row lock. **All write operations also reconcile expiration**
first, so correctness does not depend on the sweeper running precisely on time.

A hold can remain displayed as `HELD` in raw SQL for a few seconds after TTL
until the sweeper processes it; booking-status GET logically reports
`EXPIRED_PENDING_RECONCILIATION`. The read-only seat availability GET treats
holds past their expiry as free, and any competing write will run reconciliation
before reallocating. This avoids false permanent ownership.

## Queue fairness

The queue is persisted in PostgreSQL, not a volatile Redis list. A waiting
student is identified by user + event. Each waitlist entry may be `WAITING`,
`OFFERED`, `FULFILLED`, `EXPIRED`, or `CANCELLED`.

Whenever capacity becomes free:

1. Find the first available seat.
2. Find the oldest waiting user.
3. Create a standard expiring hold for that user.
4. Mark the waitlist entry `OFFERED` and record the booking ID.
5. Repeat while both seats and waiters remain.

When the offered hold expires, that offer is lost and the next waiting student
gets a turn. Users can register a new waitlist entry later if they wish.
This is documented to prevent the misleading impression of an everlasting
queue priority. It also prevents an unresponsive first waiter from blocking
all later students forever.

## Redis: fast but not authoritative

`GET /events/{id}/seats` uses a 2-second Redis snapshot cache. The cache can
be briefly stale under concurrency; this is normal for a read-only availability
hint. All mutations bypass the cache and decide against PostgreSQL while
holding the lock. If Redis goes down, readers fall back to PostgreSQL. Cache
invalidation is best effort. Decreasing TTL trades bandwidth for freshness.

### An intentionally accepted cache race

If a read populates a snapshot during a concurrent allocation, a stale cache
entry may survive invalidation for up to the TTL. The server never uses that
snapshot to grant seats. A user might see a seat as free and then get a 409,
which is consistent with a busy booking service.

## RabbitMQ and transactional outbox

It is unsafe to commit a booking payment request in PostgreSQL and then publish
a message to RabbitMQ in separate non-atomic steps: the API might crash between
the two, losing the payment request. Our API transaction instead writes a
`PENDING` payment and an `outbox` row together.

A publisher sends unpublished outbox messages with durable delivery and
publisher confirmations. A crash after broker acknowledgment but before
marking `published_at` may publish the same message again. The consumer can
receive duplicates. It is safe: after acquiring the event lock, it checks
payment status and acts only when `PENDING` and due.

**Extra recovery path:** the sweeper also scans `PENDING` payment attempts
with `ready_at <= now()`. Therefore a temporarily unavailable or slow broker
does not permanently prevent a due simulated payment from completing.

No real financial provider exists. The user requests a simulated outcome; the
worker applies the deterministic outcome after its due time. This is a state
machine demonstration, not a PCI-compliant payment gateway.

## Idempotency under simultaneous requests

The key is `(user_id, scope, key)` in PostgreSQL; it is not just a dictionary in
application memory. Within the same SQL transaction, the API inserts the key
or finds it, locks the row with `SELECT FOR UPDATE`, compares SHA-256 digests of
canonical request JSON, and either returns the original response or executes
the operation and saves its response. This handles two concurrent identical
requests from different API workers.

A key reused with different JSON is rejected with `409`. The same key can be
used in a different scope, but reuse across unrelated operations is discouraged.
The response snapshot is intentionally retained for replay; clients use GET
status APIs to retrieve current status afterward.

## Why not use Redis distributed locks?

A Redis lock introduces lock lease expiry, fencing token and split-brain failure
modes. We already require PostgreSQL transactions for persistent bookings.
Putting concurrency authority in the database keeps the invariant observable
and enforceable by a unique index, without any cross-system atomicity promise.

## Read consistency and isolation

PostgreSQL's default `READ COMMITTED` is sufficient because writers are
serialized per event and the partial unique indexes protect seat occupancy.
Read-only seat listings are best-effort snapshots, not promises of ownership.
No SERIALIZABLE isolation or global process mutex is required.

## How this scales

**One concert:** acquiring the same event row lock is intentionally a
bottleneck. A single event with 500 seats and 10,000 requests has a finite
critical-section rate and should use bounded connection pools and upstream
admission controls. The included Nginx proxy is a simple starting point.

**Multiple concerts:** locks are per event, so event A does not block event B;
multiple API replicas can run behind the reverse proxy. Postgres remains the
transaction coordinator for correctness.

Possible next steps, after measuring:

- Partition event demand or move from per-event lock to per-seat locking with a
  carefully specified fair-queue coordinator; preserve the unique index.
- Add PgBouncer when API replica count grows; limit connections per replica.
- Implement bounded admission and per-user rate limiting with retry-after,
  avoiding 10,000 blocked PostgreSQL connections.
- Use Redis notifications or SSE/WebSocket for offered-seat notifications.
- Use a dedicated queue dispatcher per event to avoid scanning every event.
- Separate payment execution from queue/outbox publication at higher volume.
- Instrument p50/p95/p99 latency, lock wait time, event throughput, and outbox age.

## Threat model summary

- User submits somebody else's booking ID: ownership check prevents access.
- User repeats request 20 times: idempotency key produces one outcome;
  unique user/seat indexes prevent extra holds even with new keys.
- Worker delivers the same message twice: second delivery sees non-PENDING
  status and is a no-op.
- Payment arrives after hold expires or was reallocated: cannot confirm it.
- API/worker loses Redis: SQL remains authoritative.
- Worker loses RabbitMQ: outbox retains intent, payment scanner recovers.

Remaining security gaps: no TLS by default, no anti-bot/CAPTCHA, no login
rate limiting, no real payment signature verification, no role-based admin API,
no secrets manager. See OPERATIONS.md for deployment precautions.
