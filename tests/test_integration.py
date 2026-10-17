"""Full service tests. Run with RUN_INTEGRATION=1 after Docker Compose is healthy.

Each test creates a separate small event in PostgreSQL; never deletes audit records.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import httpx
import pytest

pytestmark = pytest.mark.skipif(os.getenv('RUN_INTEGRATION') != '1',
                              reason='Requires live Docker Compose services')
BASE = os.getenv('BASE_URL', 'http://localhost:8080')
TEST_DB = os.getenv('TEST_DATABASE_URL', '')


def make_event(capacity=1):
    import psycopg
    from psycopg.rows import dict_row
    if not TEST_DB:
        pytest.skip('TEST_DATABASE_URL not set')
    slug = 'test-' + uuid4().hex
    with psycopg.connect(TEST_DB, row_factory=dict_row, autocommit=True) as db:
        with db.transaction():
            result = db.execute("INSERT INTO events(slug,title,starts_at) VALUES (%s,%s,clock_timestamp() + interval '1 day') RETURNING id",
                                (slug,'Temporary Integration Event')).fetchone()
            db.execute('INSERT INTO seats(event_id,number) SELECT %s,generate_series(1,%s)',
                       (result['id'],capacity))
            return result['id']


def user():
    with httpx.Client(timeout=30) as client:
        reply = client.post(BASE+'/auth/register',json={
            'email': f'test-{uuid4().hex}@example.com', 'password':'TestPassword_987!'})
        assert reply.status_code == 201, reply.text
        return reply.json()['access_token']


def post(token, url, payload=None, key=None):
    with httpx.Client(timeout=30) as client:
        return client.post(BASE+url,json=payload,headers={
            'Authorization': 'Bearer '+token,
            'Idempotency-Key': key or 'test-'+uuid4().hex})


def get(token, url):
    with httpx.Client(timeout=30) as client:
        return client.get(BASE+url,headers={'Authorization':'Bearer '+token})


def wait_for_payment(token, pid, final=('SUCCEEDED','FAILED','TIMED_OUT'), timeout=18):
    start = time.monotonic()
    while time.monotonic()-start < timeout:
        info = get(token,f'/payments/{pid}')
        assert info.status_code==200, info.text
        status = info.json()['status']
        if status in final:
            return status
        time.sleep(0.25)
    pytest.fail('Payment was not processed by background worker within timeout')


def test_30_student_race_waitlist_fifo_and_reallocation():
    event_id = make_event(1)
    tokens = [user() for _ in range(30)]
    def request(index):
        return post(tokens[index],f'/events/{event_id}/reservations',
                    {'seat_number': 1})
    with ThreadPoolExecutor(max_workers=30) as executor:
        results = list(executor.map(request, range(30)))
    assert [r.status_code for r in results].count(201) == 1
    assert [r.status_code for r in results].count(202) == 29
    report = httpx.get(BASE+f'/events/{event_id}/integrity').json()
    assert report['no_double_booking'] and report['not_oversold']
    assert report['active_tickets'] == 1 and report['waiting'] == 29

    winner_idx = next(i for i,r in enumerate(results) if r.status_code == 201)
    winner_id = results[winner_idx].json()['booking_id']
    waiters = [i for i,r in enumerate(results) if r.status_code == 202]
    # Identify actual queue head from position, not arrival order in the test harness.
    queue_state = [(i, get(tokens[i],'/waitlist/'+results[i].json()['waitlist_id']).json())
                   for i in waiters]
    first = next(i for i,s in queue_state if s['position'] == 1)
    cancelled = post(tokens[winner_idx],f'/bookings/{winner_id}/cancel')
    assert cancelled.status_code == 200, cancelled.text
    state = get(tokens[first],'/waitlist/'+results[first].json()['waitlist_id']).json()
    assert state['status'] == 'OFFERED' and state['offered_booking_id']
    report = httpx.get(BASE+f'/events/{event_id}/integrity').json()
    assert report['active_tickets'] == 1 and report['no_double_booking']


def test_idempotency_same_key_races_and_different_payload_rejected():
    event_id = make_event(3)
    token = user()
    key = 'same-key-'+uuid4().hex
    def do_request(_):
        return post(token, f'/events/{event_id}/reservations', {}, key)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(do_request,range(8)))
    assert all(r.status_code==201 for r in responses), [r.text for r in responses]
    assert len({r.json()['booking_id'] for r in responses}) == 1
    changed = post(token,f'/events/{event_id}/reservations',{'seat_number':3},key)
    assert changed.status_code == 409


def test_async_success_failure_audit_and_refund():
    event_id = make_event(1)
    token = user()
    hold = post(token,f'/events/{event_id}/reservations',{}).json()
    booking_id = hold['booking_id']
    pending = post(token,f'/bookings/{booking_id}/payments',
                   {'outcome':'delayed_success','delay_seconds':1})
    assert pending.status_code==202, pending.text
    pid = pending.json()['payment_id']
    assert wait_for_payment(token,pid) == 'SUCCEEDED'
    confirmed = get(token,f'/bookings/{booking_id}').json()
    assert confirmed['status'] == 'CONFIRMED'
    actions = [x['action'] for x in get(token,f'/bookings/{booking_id}/audit').json()['audit']]
    assert 'SEAT_HELD' in actions and 'PAYMENT_SUCCEEDED' in actions
    cancelled = post(token,f'/bookings/{booking_id}/cancel')
    assert cancelled.status_code==200 and cancelled.json()['refund']=='SIMULATED'
    assert get(token,f'/payments/{pid}').json()['status'] == 'REFUNDED'

    another = user()
    hold2 = post(another,f'/events/{event_id}/reservations',{}).json()
    failed = post(another,f"/bookings/{hold2['booking_id']}/payments",{'outcome':'failure'})
    assert failed.status_code == 202
    assert wait_for_payment(another,failed.json()['payment_id'])=='FAILED'
    assert get(another,f"/bookings/{hold2['booking_id']}").json()['status']=='FAILED'


def test_expired_hold_cannot_receive_late_payment_and_seat_reallocates():
    """Fast-forward just this isolated booking's SQL timestamp, rather than sleep 120s."""
    import psycopg
    event_id = make_event(1)
    first, second = user(), user()
    original = post(first,f'/events/{event_id}/reservations',{}).json()['booking_id']
    # Queue a synthetic payment for the future so the worker cannot win early.
    payment = post(first,f'/bookings/{original}/payments',
                   {'outcome':'delayed_success','delay_seconds':60})
    assert payment.status_code==202, payment.text
    with psycopg.connect(TEST_DB,autocommit=True) as db:
        db.execute("UPDATE bookings SET hold_expires_at=clock_timestamp() - interval '2 seconds' WHERE id=%s",
                   (original,))
    new = post(second,f'/events/{event_id}/reservations',{})
    assert new.status_code==201, new.text
    assert new.json()['booking_id'] != original
    assert get(first,f'/bookings/{original}').json()['status']=='EXPIRED'
    assert get(first,f"/payments/{payment.json()['payment_id']}").json()['status']=='TIMED_OUT'
    integrity = httpx.get(BASE+f'/events/{event_id}/integrity').json()
    assert integrity['no_double_booking'] and integrity['active_tickets']==1


def test_user_may_leave_queue_and_decline_offer():
    event_id = make_event(1)
    first, second = user(), user()
    hold = post(first,f'/events/{event_id}/reservations',{})
    assert hold.status_code==201
    queued = post(second,f'/events/{event_id}/reservations',{})
    assert queued.status_code==202
    wait_id = queued.json()['waitlist_id']
    left = post(second,f'/waitlist/{wait_id}/leave')
    assert left.status_code==200
    assert get(second,f'/waitlist/{wait_id}').json()['status']=='CANCELLED'
    assert post(first,f"/bookings/{hold.json()['booking_id']}/cancel").status_code==200
    report = httpx.get(BASE+f'/events/{event_id}/integrity').json()
    assert report['active_tickets']==0 and report['waiting']==0
