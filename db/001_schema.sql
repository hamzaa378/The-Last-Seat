-- PostgreSQL is the single authority for inventory, booking state and idempotency.
-- Intentionally explicit SQL so this project is easy to review and explain.
CREATE TABLE IF NOT EXISTS users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS seats (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    number INTEGER NOT NULL CHECK (number > 0),
    UNIQUE (event_id, number),
    UNIQUE (event_id, id)
);

CREATE TABLE IF NOT EXISTS bookings (
    id UUID PRIMARY KEY,
    event_id BIGINT NOT NULL,
    seat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('HELD','CONFIRMED','EXPIRED','FAILED','CANCELLED')),
    hold_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    confirmed_at TIMESTAMPTZ,
    FOREIGN KEY (event_id, seat_id) REFERENCES seats(event_id, id)
);
-- Physical backstop to event row lock: a seat cannot be active twice.
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_seat ON bookings(seat_id)
    WHERE status IN ('HELD','CONFIRMED');
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_ticket_per_user ON bookings(event_id, user_id)
    WHERE status IN ('HELD','CONFIRMED');
CREATE INDEX IF NOT EXISTS bookings_user_history ON bookings(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS bookings_expiration ON bookings(hold_expires_at)
    WHERE status='HELD';

CREATE TABLE IF NOT EXISTS waitlist (
    id UUID PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('WAITING','OFFERED','FULFILLED','EXPIRED','CANCELLED')),
    offered_booking_id UUID REFERENCES bookings(id),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    offered_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_waiter ON waitlist(event_id,user_id)
    WHERE status IN ('WAITING','OFFERED');
CREATE INDEX IF NOT EXISTS waitlist_fifo ON waitlist(event_id, joined_at, id)
    WHERE status='WAITING';

CREATE TABLE IF NOT EXISTS payment_attempts (
    id UUID PRIMARY KEY,
    booking_id UUID NOT NULL REFERENCES bookings(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    outcome TEXT NOT NULL CHECK (outcome IN ('success','failure')),
    status TEXT NOT NULL CHECK (status IN ('PENDING','SUCCEEDED','FAILED','TIMED_OUT','REFUNDED')),
    ready_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    processed_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_payment ON payment_attempts(booking_id)
    WHERE status='PENDING';
CREATE UNIQUE INDEX IF NOT EXISTS one_successful_payment ON payment_attempts(booking_id)
    WHERE status IN ('SUCCEEDED','REFUNDED');
CREATE INDEX IF NOT EXISTS payments_due ON payment_attempts(ready_at) WHERE status='PENDING';

CREATE TABLE IF NOT EXISTS idempotency_keys (
    user_id BIGINT NOT NULL REFERENCES users(id),
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    http_status INTEGER NOT NULL DEFAULT 0,
    response_body JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (user_id, scope, key),
    CHECK (length(key) BETWEEN 8 AND 128)
);

CREATE TABLE IF NOT EXISTS outbox (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    published_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS outbox_unpublished ON outbox(id) WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS booking_audit (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events(id),
    booking_id UUID REFERENCES bookings(id),
    actor_user_id BIGINT REFERENCES users(id),
    action TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS booking_audit_event ON booking_audit(event_id,id DESC);

-- Extra defense against accidental modifications to the immutable audit trail.
CREATE OR REPLACE FUNCTION forbid_audit_changes() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'booking_audit is append-only';
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS booking_audit_immutable ON booking_audit;
CREATE TRIGGER booking_audit_immutable BEFORE UPDATE OR DELETE ON booking_audit
FOR EACH ROW EXECUTE FUNCTION forbid_audit_changes();
