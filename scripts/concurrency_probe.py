"""Run a real 30-user race using the REST API and a private 1-seat PostgreSQL event.

Usage:
  TEST_DATABASE_URL=postgresql://tickets:PASSWORD@localhost:5434/tickets \
  python scripts/concurrency_probe.py --base http://localhost:8080
"""
import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import httpx
import psycopg
from psycopg.rows import dict_row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base',default='http://localhost:8080')
    parser.add_argument('--students',type=int,default=30)
    args = parser.parse_args()
    db_url = os.getenv('TEST_DATABASE_URL')
    if not db_url:
        parser.error('Set TEST_DATABASE_URL in the environment')
    with psycopg.connect(db_url,autocommit=True,row_factory=dict_row) as conn:
        with conn.transaction():
            slug = 'race-'+uuid4().hex
            event_id = conn.execute("INSERT INTO events(slug,title,starts_at) VALUES (%s,'Concurrency Race',clock_timestamp() + interval '1 day') RETURNING id",(slug,)).fetchone()['id']
            conn.execute('INSERT INTO seats(event_id,number) VALUES (%s,1)',(event_id,))
    def race(_):
        with httpx.Client(timeout=30) as client:
            token = client.post(args.base+'/auth/register',json={
                'email': f'race-{uuid4().hex}@example.com',
                'password': 'RacingPassword123!'}).json()['access_token']
            return client.post(f'{args.base}/events/{event_id}/reservations',json={'seat_number':1},
                               headers={'Authorization':'Bearer '+token,
                                        'Idempotency-Key':'race-'+uuid4().hex})
    with ThreadPoolExecutor(max_workers=args.students) as pool:
        responses = list(pool.map(race,range(args.students)))
    winners = sum(r.status_code==201 for r in responses)
    waiting = sum(r.status_code==202 for r in responses)
    report = httpx.get(f'{args.base}/events/{event_id}/integrity',timeout=30).json()
    print(f'Race: students={args.students} direct_holds={winners} waiting={waiting} other={len(responses)-winners-waiting}')
    print('Database integrity:',report)
    assert winners == 1, 'Expected one winner for a single seat'
    assert waiting == args.students-1, 'Every other student must be waitlisted'
    assert report['no_double_booking'] and report['not_oversold']
    print('PASS: precisely one winner, no double booking, everyone else queued')


if __name__ == '__main__':
    main()
