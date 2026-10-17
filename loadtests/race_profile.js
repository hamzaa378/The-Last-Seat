// k6 run -e BASE_URL=http://localhost:8080 -e EVENT_ID=1 loadtests/race.js
// Default: first available seat, so the 500-seat event eventually fills and queues.
// Set SEAT_NUMBER=1 to deliberately contest a single seat; 409 then means other seats are still free.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const root = __ENV.BASE_URL || 'http://localhost:8080';
const eventId = __ENV.EVENT_ID || '1';
const targetSeat = __ENV.SEAT_NUMBER ? Number(__ENV.SEAT_NUMBER) : null;
const won = new Counter('won_seat');
const waitlisted = new Counter('waitlisted');
const serverErrors = new Rate('server_errors');
const registrationTime = new Trend('registration_time', true);
const reservationTime = new Trend('reservation_time', true);
export const options = {
  scenarios: { sudden_rush: { executor: 'constant-vus', vus: 100, duration: '20s' } },
  thresholds: { server_errors: ['rate<0.05'] },
};

export default function() {
  const random = `${__VU}-${__ITER}-${Date.now()}-${Math.floor(Math.random()*1e9)}`;
  const register = http.post(`${root}/auth/register`, JSON.stringify({
    email: `k6-${random}@example.com`,password:'K6SecurePassword987!'
  }), {headers:{'Content-Type':'application/json'}});
  registrationTime.add(register.timings.duration);
  if (register.status !== 201) {serverErrors.add(true); return;}
  const token = register.json('access_token');
  const r = http.post(`${root}/events/${eventId}/reservations`,
    JSON.stringify(targetSeat ? {seat_number:targetSeat} : {}), {headers: {
      'Authorization': `Bearer ${token}`, 'Content-Type':'application/json',
      'Idempotency-Key': `reserve-${random}`}});
  reservationTime.add(r.timings.duration);
  won.add(r.status === 201);
  waitlisted.add(r.status === 202);
  serverErrors.add(r.status === 0 || r.status >= 500);
  check(r, {'request handled without transport/server error': x => x.status > 0 && x.status < 500});
  sleep(0.1);
}
