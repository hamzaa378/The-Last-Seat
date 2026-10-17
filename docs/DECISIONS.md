# Technical decisions and tradeoffs

These notes explain the implementation rather than claiming benchmarks that
have not yet been measured. Add your own experiment observations before
submitting the CodeChef-VIT recruitment task.

## 1. Most difficult engineering problem

**How do you ensure two students cannot buy the last seat at the same time?**

I chose to serialize each event's inventory mutation with `SELECT ... FOR
UPDATE` on the event row. This means concurrent requests queue *inside the
transaction manager*. The second transaction checks inventory only after the
first has committed. A partial unique seat index is an additional database
safety barrier. `tests/test_integration.py` and `scripts/concurrency_probe.py`
exercise the scenario using real parallel HTTP requests.

It is not enough to check availability in Redis, or to lock a Python variable.
Those mechanisms are not transactionally tied to bookings across two servers.

## 2. Most important architectural decision

**PostgreSQL is the single source of truth.** Redis only caches read-only seat
availability; RabbitMQ only transfers durable intentions from an outbox.
Neither decides which student gets a ticket. This avoids split-brain ownership
if a cache instance restarts or a message is duplicated.

The cost is a conservative per-event lock. I accepted lower peak per-event
write concurrency to make correctness easy to verify. A production system
would measure lock contention before switching to fine-grained seat locks.

## 3. Limitation or failure case

A single popular event can become write-throughput limited on its row lock,
even if more API replicas are added. Students may also receive a stale
read-only seat snapshot for up to two seconds. Under severe bursts, some
connections could time out before they acquire the event lock. None of these
imply that a duplicate ticket is safe or acceptable.

Simulated success/failure does not replicate real payment provider semantics.
A real integration needs webhook authentication, payment intents, refunds,
and reconciliation against provider records.

## 4. First improvement with another week

I would add **bounded admission control and observable fairness** before
adding more features: per-user rate limits, a maximum number of waiting SQL
transactions, metrics for lock wait time and promotion delay, and push
notifications for queue offers. After gathering load-test evidence, I would
consider finer-grained seat locking while preserving the unique index.

## 5. Distinctive engineering features

- Transactional outbox and publisher confirmation prevent silent loss of a
  newly requested payment when RabbitMQ is unavailable.
- A separate due-payment scan is a self-healing path for delayed/dropped
  broker notifications.
- Append-only booking events (enforced by a PostgreSQL trigger) make it easy
  to investigate disputes over seat assignment and cancellation.
- Read-only `/events/{event_id}/integrity` exposes invariant evidence to
  reviewers, and a separate SQL script detects violations across all events.
- Waiting users automatically receive expiring seat offers, with FIFO
  ordering determined inside the database transaction.

## Suggested 2-minute demonstration script

1. Show `GET /events`: one event, 500 seeded seats.
2. Run `scripts/concurrency_probe.py --students 30`: one seat, 30 requests.
3. Show the `/integrity` endpoint and SQL duplicate-seat check.
4. Cancel the one successful booking and inspect the first waiter's offer.
5. Submit a `delayed_success` payment, then view the audit events.
6. Replay the payment request with the same idempotency key and show that no
   new payment is created.
7. Show the diagram and explain why Redis isn't used for locking.

## Evaluation honesty

Use the actual stdout and timing numbers from your environment. Do not claim
10,000 concurrent users were handled unless that exact test was executed with
captured hardware settings, errors and latency percentiles.
