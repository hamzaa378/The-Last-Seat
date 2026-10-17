// Native Windows example:
// k6 run -e VUS=200 -e ITERATIONS=10000 -e BASE_URL=http://127.0.0.1:8000 -e EVENT_ID=13 loadtests/race.js
// Use a real event ID; request outcomes must be 201 (held) or 202 (queued).
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const root = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const eventId = __ENV.EVENT_ID || '1';
const targetSeat = __ENV.SEAT_NUMBER ? Number(__ENV.SEAT_NUMBER) : null;
const won = new Counter('won_seat');
const waitlisted = new Counter('waitlisted');
const serverErrors = new Rate('server_errors');
const invalidOutcomes = new Rate('invalid_outcomes');

export const options = {
  scenarios: {
    booking_race: {
      executor: 'shared-iterations',
      vus: Number(__ENV.VUS || 50),
      iterations: Number(__ENV.ITERATIONS || 500),
      maxDuration: '30m',
    },
  },
  thresholds: {
    server_errors: ['rate<0.05'],
    invalid_outcomes: ['rate==0'],
  },
};

export default function () {
  const random = `${__VU}-${__ITER}-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  const register = http.post(`${root}/auth/register`, JSON.stringify({
    email: `k6-${random}@example.com`, password: 'K6SecurePassword987!',
  }), { headers: { 'Content-Type': 'application/json' } });

  if (register.status !== 201) {
    serverErrors.add(register.status === 0 || register.status >= 500);
    invalidOutcomes.add(true);
    if (__ITER === 0) console.error(`Registration failed: ${register.status} ${register.body}`);
    return;
  }

  const token = register.json('access_token');
  const reservation = http.post(`${root}/events/${eventId}/reservations`,
    JSON.stringify(targetSeat !== null ? { seat_number: targetSeat } : {}),
    { headers: {
      Authorization: `Bearer ${token}`, 'Content-Type': 'application/json',
      'Idempotency-Key': `reserve-${random}`,
    } });

  won.add(reservation.status === 201);
  waitlisted.add(reservation.status === 202);
  serverErrors.add(reservation.status === 0 || reservation.status >= 500);
  const expected = reservation.status === 201 || reservation.status === 202 ||
    (targetSeat !== null && reservation.status === 409);
  invalidOutcomes.add(!expected);
  check(reservation, { 'valid booking outcome': () => expected });
  if (!expected && __ITER === 0) {
    console.error(`Unexpected reservation: ${reservation.status} ${reservation.body}`);
  }
  sleep(0.1);
}
