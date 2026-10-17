"""Safely preview or delete one temporary test event from the local PostgreSQL database.

Run with the FastAPI API and background worker STOPPED; never delete the live campus concert.
Default behavior is read-only. Data deletion requires --execute and typing a confirmation.
The booking audit trigger is temporarily disabled *inside* the same DB transaction,
then re-enabled before commit. PostgreSQL rolls back trigger DDL if anything fails.

This does not delete shared student accounts: users may have records for other events.
"""
import argparse
import getpass
import os
from urllib.parse import quote



TEST_SLUG_PREFIXES = ('test-', 'load-test-', 'k6-test-', 'race-')


def is_test_event(event):
    """Fail closed for all non-test slugs, especially the original campus concert."""
    return (int(event['id']) != 1 and event['slug'] != 'campus-concert'
            and any(event['slug'].startswith(x) for x in TEST_SLUG_PREFIXES))


def db_url():
    existing = os.getenv('TEST_DATABASE_URL') or os.getenv('DATABASE_URL')
    if existing:
        return existing
    password = quote(getpass.getpass('PostgreSQL tickets password: '), safe='')
    return f'postgresql://tickets:{password}@127.0.0.1:5432/tickets'


def snapshot(conn, eid):
    event = conn.execute('SELECT id,slug,title FROM events WHERE id=%s', (eid,)).fetchone()
    if event is None:
        raise ValueError(f'Event #{eid} does not exist')
    if not is_test_event(event):
        raise ValueError('Refusing to delete a non-test event')
    counts = {}
    for table in ('seats', 'bookings', 'waitlist', 'booking_audit'):
        counts[table] = conn.execute(f'SELECT COUNT(*) AS n FROM {table} WHERE event_id=%s',
                                     (eid,)).fetchone()['n']
    counts['payments'] = conn.execute('''SELECT COUNT(*) AS n FROM payment_attempts p
                                       JOIN bookings b ON b.id=p.booking_id
                                       WHERE b.event_id=%s''', (eid,)).fetchone()['n']
    counts['confirmed'] = conn.execute('''SELECT COUNT(*) AS n FROM bookings
                                        WHERE event_id=%s AND status='CONFIRMED' ''',
                                       (eid,)).fetchone()['n']
    return event, counts


def delete_event(conn, eid):
    """Preserve shared users; delete only rows belonging to this event."""
    # Scope-specific idempotency records must be removed before booking references disappear.
    conn.execute('''DELETE FROM idempotency_keys k
        WHERE k.scope IN (%s, %s)
        OR EXISTS (SELECT 1 FROM bookings b WHERE b.event_id=%s
                   AND k.scope IN ('payment:' || b.id::text, 'cancel:' || b.id::text))
        OR EXISTS (SELECT 1 FROM waitlist w WHERE w.event_id=%s
                   AND k.scope='waitlist-leave:' || w.id::text)''',
                 (f'reserve:{eid}', f'waitlist:{eid}', eid, eid))
    # The transactional outbox has no event_id; follow the payment reference instead.
    conn.execute('''DELETE FROM outbox o WHERE EXISTS (
        SELECT 1 FROM payment_attempts p
        JOIN bookings b ON b.id=p.booking_id
        WHERE b.event_id=%s AND o.payload->>'payment_id'=p.id::text
    )''', (eid,))
    # This maintenance exception is explicitly scoped to the deleted test event.
    # Both ALTER statements participate in the transaction; rollback restores the trigger.
    conn.execute('ALTER TABLE booking_audit DISABLE TRIGGER booking_audit_immutable')
    conn.execute('DELETE FROM booking_audit WHERE event_id=%s', (eid,))
    conn.execute('ALTER TABLE booking_audit ENABLE TRIGGER booking_audit_immutable')
    # Offered waitlist entries point to bookings. Break that FK first.
    conn.execute('UPDATE waitlist SET offered_booking_id=NULL WHERE event_id=%s', (eid,))
    conn.execute('DELETE FROM waitlist WHERE event_id=%s', (eid,))
    conn.execute('''DELETE FROM payment_attempts p USING bookings b
                    WHERE p.booking_id=b.id AND b.event_id=%s''', (eid,))
    conn.execute('DELETE FROM bookings WHERE event_id=%s', (eid,))
    conn.execute('DELETE FROM seats WHERE event_id=%s', (eid,))
    removed = conn.execute('DELETE FROM events WHERE id=%s RETURNING id', (eid,)).fetchone()
    if not removed:
        raise ValueError(f'Event #{eid} disappeared during cleanup; rolled back')


def main():
    parser = argparse.ArgumentParser(description='Preview or delete ONE temporary test event.')
    parser.add_argument('--list', action='store_true', help='Only list test events')
    parser.add_argument('--id', type=int, help='Exact test event ID, e.g. 13')
    parser.add_argument('--execute', action='store_true', help='Actually delete this test event')
    args = parser.parse_args()
    if not args.list and args.id is None:
        parser.error('Use --list or --id 13')
    if args.execute and args.id is None:
        parser.error('--execute requires --id')

    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(db_url(), row_factory=dict_row) as conn:
        if args.list:
            rows = conn.execute('SELECT id,slug,title FROM events ORDER BY id').fetchall()
            for event in rows:
                if is_test_event(event):
                    print(f'#{event["id"]:>4}  {event["slug"]:<45} {event["title"]}')
            print('No records were changed.')
            return
        event, counts = snapshot(conn, args.id)
        print(f'Event #{event["id"]}: {event["title"]}  ({event["slug"]})')
        for name, count in counts.items():
            print(f'  {name:<16} {count}')
        print('User accounts are preserved. Main concert is protected.')
        if not args.execute:
            print('DRY RUN: no records were changed. Review results before using --execute.')
            return
        if counts['confirmed']:
            raise ValueError('Refusing to remove a test event with CONFIRMED tickets')
        confirmation = input(f'Type DELETE {args.id} to permanently delete this event: ').strip()
        if confirmation != f'DELETE {args.id}':
            print('Confirmation mismatch: no deletion performed.')
            return
        # Lock the event row so new booking transactions cannot acquire it.
        conn.execute('SELECT id FROM events WHERE id=%s FOR UPDATE', (args.id,))
        delete_event(conn, args.id)
        print(f'Event #{args.id} and dependent test records deleted. Transaction committing.')


if __name__ == '__main__':
    main()
