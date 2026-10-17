"""Friendly walkthrough: register -> reserve -> simulate payment -> cancel -> integrity.

Start Docker first. Requirements: httpx (in requirements.txt).
"""
import argparse
import time
from uuid import uuid4
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base',default='http://localhost:8080')
    args = parser.parse_args()
    with httpx.Client(base_url=args.base, timeout=30) as api:
        email = f'smoke-{uuid4().hex}@example.com'
        user = api.post('/auth/register',json={'email':email,'password':'LocalPassword123!'})
        user.raise_for_status()
        token = user.json()['access_token']
        auth = {'Authorization':f'Bearer {token}'}
        event = api.get('/events').json()[0]['id']
        key = lambda: {**auth, 'Idempotency-Key':'demo-'+uuid4().hex}
        reserve = api.post(f'/events/{event}/reservations',json={},headers=key())
        reserve.raise_for_status()
        if reserve.status_code == 202:
            print('Concert full: queued instead of confirmed:',reserve.json())
            return
        booking_id = reserve.json()['booking_id']
        print('1. Hold created:',booking_id)
        payment = api.post(f'/bookings/{booking_id}/payments',
                           json={'outcome':'success'},headers=key())
        payment.raise_for_status()
        pay_id = payment.json()['payment_id']
        print('2. Payment submitted asynchronously:',pay_id)
        for i in range(40):
            result = api.get(f'/payments/{pay_id}',headers=auth).json()
            if result['status'] != 'PENDING':
                break
            time.sleep(0.25)
        print('3. Payment state:',result['status'])
        assert result['status']=='SUCCEEDED', 'Worker must process payment'
        booking = api.get(f'/bookings/{booking_id}',headers=auth).json()
        print('4. Booking state:',booking['status'])
        assert booking['status']=='CONFIRMED'
        print('5. Audit actions:',[x['action'] for x in api.get(
            f'/bookings/{booking_id}/audit',headers=auth).json()['audit']])
        cancel = api.post(f'/bookings/{booking_id}/cancel',headers=key())
        cancel.raise_for_status()
        print('6. Cancellation:',cancel.json())
        integrity = api.get(f'/events/{event}/integrity').json()
        print('7. Inventory integrity:',integrity)
        assert integrity['no_double_booking'] and integrity['not_oversold']
        print('PASS: smoke demo completed')


if __name__ == '__main__':
    main()
