"""Booking rules. Every inventory mutation locks the parent EVENT before touching seats.

This is intentionally conservative: correct for a concert with 500 seats and easy
for reviewers to reason about. The partial UNIQUE index is a second line of defense.
"""
from uuid import uuid4
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from app.cache import invalidate
from app.config import HOLD_SECONDS, PAYMENT_DELAY_SECONDS


def audit(conn, event_id, booking_id, user_id, action, details=None):
    conn.execute('''INSERT INTO booking_audit(event_id,booking_id,actor_user_id,action,details)
                    VALUES (%s,%s,%s,%s,%s)''',
                 (event_id, booking_id, user_id, action, Jsonb(details or {})))


def lock_event(conn, event_id):
    row = conn.execute('SELECT id,slug,title FROM events WHERE id=%s FOR UPDATE',
                       (event_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Event not found')
    return row


def free_seat(conn, event_id, seat_number=None):
    sql = '''SELECT s.id, s.number FROM seats s
             WHERE s.event_id=%s AND NOT EXISTS (
               SELECT 1 FROM bookings b WHERE b.seat_id=s.id
               AND b.status IN ('HELD','CONFIRMED'))'''
    args = [event_id]
    if seat_number is not None:
        sql += ' AND s.number=%s'
        args.append(seat_number)
    sql += ' ORDER BY s.number LIMIT 1'
    return conn.execute(sql, args).fetchone()


def make_hold(conn, event_id, seat, user_id, queued=False):
    booking_id = uuid4()
    row = conn.execute('''INSERT INTO bookings(id,event_id,seat_id,user_id,status,hold_expires_at)
                          VALUES (%s,%s,%s,%s,'HELD', clock_timestamp() + make_interval(secs => %s))
                          RETURNING hold_expires_at''',
                       (booking_id, event_id, seat['id'], user_id, HOLD_SECONDS)).fetchone()
    audit(conn, event_id, booking_id, user_id, 'WAITLIST_OFFERED' if queued else 'SEAT_HELD',
          {'seat_number': seat['number'], 'ttl_seconds': HOLD_SECONDS})
    invalidate(event_id)
    return {'booking_id': str(booking_id), 'event_id': event_id,
            'seat_number': seat['number'], 'status': 'HELD',
            'hold_expires_at': row['hold_expires_at'].isoformat(),
            'source': 'WAITLIST' if queued else 'DIRECT'}


def expire_holds(conn, event_id):
    """Run only after lock_event. Expired payment attempts can never confirm later."""
    expired = conn.execute('''UPDATE bookings SET status='EXPIRED'
                              WHERE event_id=%s AND status='HELD'
                                AND hold_expires_at <= clock_timestamp()
                              RETURNING id, user_id''', (event_id,)).fetchall()
    for row in expired:
        conn.execute('''UPDATE payment_attempts SET status='TIMED_OUT',processed_at=clock_timestamp()
                        WHERE booking_id=%s AND status='PENDING' ''', (row['id'],))
        conn.execute('''UPDATE waitlist SET status='EXPIRED'
                        WHERE offered_booking_id=%s AND status='OFFERED' ''', (row['id'],))
        audit(conn, event_id, row['id'], row['user_id'], 'HOLD_EXPIRED')
    if expired:
        invalidate(event_id)
    return len(expired)


def offer_waitlist(conn, event_id):
    """FIFO promotion. One held seat is offered to one waiting student."""
    promoted = 0
    while True:
        seat = free_seat(conn, event_id)
        if seat is None:
            break
        person = conn.execute('''SELECT id, user_id FROM waitlist
                                 WHERE event_id=%s AND status='WAITING'
                                 ORDER BY joined_at,id LIMIT 1 FOR UPDATE''',
                              (event_id,)).fetchone()
        if person is None:
            break
        # If a user obtained a direct booking before promotion, skip this entry.
        existing = conn.execute('''SELECT id FROM bookings WHERE event_id=%s AND user_id=%s
                                   AND status IN ('HELD','CONFIRMED') LIMIT 1''',
                                (event_id, person['user_id'])).fetchone()
        if existing:
            conn.execute("UPDATE waitlist SET status='FULFILLED' WHERE id=%s", (person['id'],))
            continue
        held = make_hold(conn, event_id, seat, person['user_id'], queued=True)
        conn.execute('''UPDATE waitlist SET status='OFFERED', offered_booking_id=%s,
                        offered_at=clock_timestamp() WHERE id=%s''',
                     (held['booking_id'], person['id']))
        promoted += 1
    return promoted


def reconcile_event(conn, event_id):
    """Must be called under lock_event, before decisions or after seat releases."""
    expired = expire_holds(conn, event_id)
    offered = offer_waitlist(conn, event_id)
    return {'expired_holds': expired, 'new_offers': offered}


def join_waitlist(conn, event_id, user_id):
    existing = conn.execute('''SELECT id, status, offered_booking_id FROM waitlist
                               WHERE event_id=%s AND user_id=%s
                               AND status IN ('WAITING','OFFERED')''',
                            (event_id, user_id)).fetchone()
    if not existing:
        wait_id = uuid4()
        conn.execute('''INSERT INTO waitlist(id,event_id,user_id,status)
                        VALUES (%s,%s,%s,'WAITING')''', (wait_id, event_id, user_id))
        existing = {'id': wait_id, 'status': 'WAITING', 'offered_booking_id': None}
        audit(conn, event_id, None, user_id, 'WAITLIST_JOINED')
    return {'waitlist_id': str(existing['id']), 'status': existing['status'],
            'offered_booking_id': (str(existing['offered_booking_id'])
                                   if existing['offered_booking_id'] else None),
            'message': 'Check GET /waitlist/{id}; offers expire like normal holds.'}


def reserve(conn, event_id, user_id, seat_number):
    lock_event(conn, event_id)
    reconcile_event(conn, event_id)
    existing = conn.execute('''SELECT id,status FROM bookings WHERE event_id=%s AND user_id=%s
                               AND status IN ('HELD','CONFIRMED') LIMIT 1''',
                            (event_id, user_id)).fetchone()
    if existing:
        raise HTTPException(409, {'reason': 'ALREADY_HAS_TICKET',
                                  'booking_id': str(existing['id'])})
    waiting = conn.execute('''SELECT id FROM waitlist WHERE event_id=%s AND user_id=%s
                              AND status IN ('WAITING','OFFERED') LIMIT 1''',
                           (event_id, user_id)).fetchone()
    if waiting:
        return 202, join_waitlist(conn, event_id, user_id)
    # No new direct reservations may jump in front of someone waiting.
    queue_exists = conn.execute('''SELECT 1 FROM waitlist WHERE event_id=%s
                                   AND status='WAITING' LIMIT 1''', (event_id,)).fetchone()
    seat = None if queue_exists else free_seat(conn, event_id, seat_number)
    if seat:
        return 201, make_hold(conn, event_id, seat, user_id)
    any_free = free_seat(conn, event_id)
    if any_free and seat_number is not None and not queue_exists:
        raise HTTPException(409, {'reason': 'SEAT_UNAVAILABLE',
                                  'message': 'Try another seat number'})
    return 202, join_waitlist(conn, event_id, user_id)


def explicit_waitlist(conn, event_id, user_id):
    lock_event(conn, event_id)
    reconcile_event(conn, event_id)
    already = conn.execute('''SELECT 1 FROM bookings WHERE event_id=%s AND user_id=%s
                              AND status IN ('HELD','CONFIRMED') LIMIT 1''',
                           (event_id,user_id)).fetchone()
    if already:
        raise HTTPException(409, 'You already hold a seat')
    # Proactively return the available seat rather than queueing behind nobody.
    if free_seat(conn, event_id) and not conn.execute(
        "SELECT 1 FROM waitlist WHERE event_id=%s AND status='WAITING' LIMIT 1",
        (event_id,)).fetchone():
        raise HTTPException(409, 'Seats are available: use the reservations endpoint')
    return 202, join_waitlist(conn, event_id, user_id)


def request_payment(conn, user_id, booking_id, outcome, delay_seconds):
    owner = conn.execute('SELECT event_id FROM bookings WHERE id=%s AND user_id=%s',
                         (booking_id, user_id)).fetchone()
    if owner is None:
        raise HTTPException(404, 'Booking not found')
    event_id = owner['event_id']
    lock_event(conn, event_id)
    reconcile_event(conn, event_id)
    booking = conn.execute('''SELECT status,hold_expires_at FROM bookings WHERE id=%s''',
                           (booking_id,)).fetchone()
    if booking['status'] != 'HELD':
        raise HTTPException(409, {'reason': 'HOLD_NOT_PAYABLE', 'status': booking['status']})
    existing = conn.execute('''SELECT id, ready_at FROM payment_attempts
                               WHERE booking_id=%s AND status='PENDING' ''',
                            (booking_id,)).fetchone()
    if existing:
        return 202, {'payment_id': str(existing['id']), 'status': 'PENDING',
                     'ready_at': existing['ready_at'].isoformat()}
    actual_delay = (delay_seconds if delay_seconds is not None else PAYMENT_DELAY_SECONDS) if outcome.startswith('delayed') else 0
    payment_id = uuid4()
    raw_outcome = 'failure' if outcome.endswith('failure') else 'success'
    ready = conn.execute('''INSERT INTO payment_attempts(
                            id, booking_id, user_id, outcome,status,ready_at)
                            VALUES (%s,%s,%s,%s,'PENDING',clock_timestamp() + make_interval(secs => %s))
                            RETURNING ready_at''',
                         (payment_id, booking_id, user_id, raw_outcome, actual_delay)).fetchone()
    conn.execute("INSERT INTO outbox(event_type,payload) VALUES ('PAYMENT_REQUESTED',%s)",
                 (Jsonb({'payment_id': str(payment_id)}),))
    audit(conn, event_id, booking_id, user_id, 'PAYMENT_REQUESTED',
          {'payment_id': str(payment_id), 'simulated_outcome': raw_outcome,
           'delay_seconds': actual_delay})
    return 202, {'payment_id': str(payment_id), 'status': 'PENDING',
                 'ready_at': ready['ready_at'].isoformat()}


def cancel_booking(conn, user_id, booking_id):
    owner = conn.execute('SELECT event_id FROM bookings WHERE id=%s AND user_id=%s',
                         (booking_id, user_id)).fetchone()
    if not owner:
        raise HTTPException(404, 'Booking not found')
    event_id = owner['event_id']
    lock_event(conn, event_id)
    reconcile_event(conn, event_id)
    previous = conn.execute('SELECT status FROM bookings WHERE id=%s', (booking_id,)).fetchone()
    if previous['status'] not in ('HELD','CONFIRMED'):
        raise HTTPException(409, f"Cannot cancel booking in state {previous['status']}")
    conn.execute("UPDATE bookings SET status='CANCELLED' WHERE id=%s", (booking_id,))
    conn.execute('''UPDATE payment_attempts SET status='TIMED_OUT',processed_at=clock_timestamp()
                    WHERE booking_id=%s AND status='PENDING' ''', (booking_id,))
    conn.execute('''UPDATE payment_attempts SET status='REFUNDED',processed_at=clock_timestamp()
                    WHERE booking_id=%s AND status='SUCCEEDED' ''', (booking_id,))
    conn.execute('''UPDATE waitlist SET status='CANCELLED'
                    WHERE offered_booking_id=%s AND status='OFFERED' ''', (booking_id,))
    audit(conn, event_id, booking_id, user_id, 'BOOKING_CANCELLED',
          {'previous_status': previous['status'], 'refund': 'SIMULATED_ONLY'})
    invalidate(event_id)
    reconcile_event(conn, event_id)
    return 200, {'booking_id': str(booking_id), 'status': 'CANCELLED',
                 'refund': 'SIMULATED' if previous['status']=='CONFIRMED' else 'NOT_REQUIRED'}


def process_payment(conn, payment_id):
    """Safe to retry and safe if AMQP delivers a message more than once."""
    identifier = conn.execute('''SELECT b.event_id FROM payment_attempts p
                                 JOIN bookings b ON b.id=p.booking_id WHERE p.id=%s''',
                              (payment_id,)).fetchone()
    if not identifier:
        return 'UNKNOWN'
    event_id = identifier['event_id']
    lock_event(conn, event_id)
    reconcile_event(conn, event_id)
    payment = conn.execute('''SELECT p.id,p.booking_id,p.user_id,p.outcome,p.status,p.ready_at,
                                     b.status AS booking_status, b.hold_expires_at
                              FROM payment_attempts p JOIN bookings b ON b.id=p.booking_id
                              WHERE p.id=%s FOR UPDATE OF p''', (payment_id,)).fetchone()
    if payment['status'] != 'PENDING':
        return payment['status']
    now = conn.execute('SELECT clock_timestamp() AS now').fetchone()['now']
    if payment['ready_at'] > now:
        return 'NOT_DUE'
    if payment['booking_status'] != 'HELD' or payment['hold_expires_at'] <= now:
        conn.execute('''UPDATE payment_attempts SET status='TIMED_OUT',processed_at=clock_timestamp()
                        WHERE id=%s''', (payment_id,))
        return 'TIMED_OUT'
    if payment['outcome'] == 'success':
        conn.execute('''UPDATE bookings SET status='CONFIRMED',confirmed_at=clock_timestamp()
                        WHERE id=%s''', (payment['booking_id'],))
        conn.execute('''UPDATE payment_attempts SET status='SUCCEEDED',processed_at=clock_timestamp()
                        WHERE id=%s''', (payment_id,))
        conn.execute('''UPDATE waitlist SET status='FULFILLED'
                        WHERE offered_booking_id=%s AND status='OFFERED' ''',
                     (payment['booking_id'],))
        audit(conn, event_id, payment['booking_id'], payment['user_id'], 'PAYMENT_SUCCEEDED')
        invalidate(event_id)
        return 'SUCCEEDED'
    conn.execute('''UPDATE bookings SET status='FAILED' WHERE id=%s''',
                 (payment['booking_id'],))
    conn.execute('''UPDATE payment_attempts SET status='FAILED',processed_at=clock_timestamp()
                    WHERE id=%s''', (payment_id,))
    conn.execute('''UPDATE waitlist SET status='EXPIRED'
                    WHERE offered_booking_id=%s AND status='OFFERED' ''', (payment['booking_id'],))
    audit(conn, event_id, payment['booking_id'], payment['user_id'], 'PAYMENT_FAILED')
    invalidate(event_id)
    reconcile_event(conn, event_id)
    return 'FAILED'


def leave_waitlist(conn, user_id, wait_id):
    """Opt out of a queue offer; release it immediately and fairly reallocate."""
    entry = conn.execute('''SELECT event_id FROM waitlist WHERE id=%s AND user_id=%s''',
                         (wait_id, user_id)).fetchone()
    if not entry:
        raise HTTPException(404, 'Waitlist entry not found')
    event_id = entry['event_id']
    lock_event(conn, event_id)
    reconcile_event(conn, event_id)
    current = conn.execute('''SELECT status,offered_booking_id FROM waitlist
                              WHERE id=%s''', (wait_id,)).fetchone()
    if current['status'] not in ('WAITING','OFFERED'):
        raise HTTPException(409, f"Cannot leave waitlist in state {current['status']}")
    if current['status']=='OFFERED' and current['offered_booking_id']:
        conn.execute('''UPDATE bookings SET status='CANCELLED'
                        WHERE id=%s AND status='HELD' ''', (current['offered_booking_id'],))
        conn.execute('''UPDATE payment_attempts SET status='TIMED_OUT',processed_at=clock_timestamp()
                        WHERE booking_id=%s AND status='PENDING' ''',
                     (current['offered_booking_id'],))
        audit(conn, event_id, current['offered_booking_id'], user_id, 'WAITLIST_OFFER_DECLINED')
        invalidate(event_id)
    conn.execute("UPDATE waitlist SET status='CANCELLED' WHERE id=%s", (wait_id,))
    audit(conn, event_id, None, user_id, 'WAITLIST_LEFT')
    reconcile_event(conn, event_id)
    return 200, {'waitlist_id': str(wait_id), 'status': 'CANCELLED'}
