"""Public REST API: OpenAPI UI is available at /docs."""
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from psycopg.errors import UniqueViolation
from app.database import start_pool, stop_pool, transaction, reader
from app.cache import get as cache_get, set_snapshot
from app.security import password_hash, make_token, current_user
from app.idempotency import execute_once
from app.schemas import Credentials, ReservationRequest, PaymentRequest
from app import service


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_pool()
    yield
    stop_pool()


API_DESCRIPTION = """
### The Last Seat · Campus Concert API

A concurrency-safe booking system backed by **PostgreSQL**. Seats are held briefly
before payment. Payments are **simulated**, never real charges.

**Quick start in Swagger**

1. **POST `/auth/register`** with an email and password (at least 8 characters).
2. Copy `access_token`. Click **Authorize** and paste the token.
3. **GET `/events`** and **GET `/events/{event_id}/seats`** to view the venue.
4. **POST `/events/{event_id}/reservations`** with `{}` for the next free seat or
   `{"seat_number":10}` for a specific seat, plus an **Idempotency-Key** header
   such as `reserve-demo-0001`.
5. **201** means HELD (save `booking_id`). **202** means WAITING (save `waitlist_id`).
6. **POST `/bookings/{booking_id}/payments`** with `{"outcome":"success"}` and a
   new idempotency key. The **background worker** completes payments asynchronously.

Retry an identical operation with the **same** idempotency key; use a **new** key for
any new action. HTTP **409** can be an expected seat conflict, not a server outage.

The optional **Student Portal** runs separately on port 8501.
"""

TAG_DETAILS = [
    {'name': 'Auth', 'description': 'Register and log in. Paste the bearer token into Swagger Authorize.'},
    {'name': 'Events', 'description': 'Explore concerts and available numbered seats.'},
    {'name': 'Bookings', 'description': 'Hold, inspect and cancel seats. Mutations require an Idempotency-Key.'},
    {'name': 'Payments', 'description': 'Asynchronous, simulated payments; the background worker processes them.'},
    {'name': 'Waitlist', 'description': 'Track queue position, receive a seat offer or leave the queue.'},
    {'name': 'Audit', 'description': 'Append-only booking history visible to the booking owner.'},
    {'name': 'Operations', 'description': 'Readiness and integrity diagnostics.'},
]

app = FastAPI(
    title='The Last Seat | Booking API',
    version='1.2.0',
    description=API_DESCRIPTION,
    openapi_tags=TAG_DETAILS,
    docs_url=None,
    redoc_url='/redoc',
    lifespan=lifespan,
)
app.mount('/_ui', StaticFiles(directory=Path(__file__).resolve().parent / 'static'),
          name='docs-static')


@app.get('/docs', include_in_schema=False)
def enhanced_swagger():
    """FastAPI's official Swagger renderer with a local stylesheet and helper header."""
    page = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title='The Last Seat · API Explorer',
        swagger_ui_parameters={
            'deepLinking': True, 'filter': True, 'docExpansion': 'list',
            'displayRequestDuration': True, 'defaultModelsExpandDepth': -1,
            'persistAuthorization': False,
            'requestSnippetsEnabled': True,
        },
    ).body.decode('utf-8')
    page = page.replace('</head>',
                        '<link rel="stylesheet" href="/_ui/swagger_theme.css"></head>', 1)
    guide = '''<div class="booking-guide">
    <div><strong>THE LAST SEAT</strong><span>Developer API Explorer</span></div>
    <nav><span class="steps">1. Register → 2. Authorize → 3. Reserve → 4. Pay</span>
    <a href="http://127.0.0.1:8501" target="_blank" rel="noopener noreferrer">Student Portal ↗</a></nav>
    </div>'''
    page = page.replace('<div id="swagger-ui">',
                        guide + '<div id="swagger-ui">', 1)
    return HTMLResponse(page)


def reply(result):
    code, body = result
    return JSONResponse(status_code=code, content=body)


def valid_key(key: str | None):
    if not key:
        raise HTTPException(400, 'Idempotency-Key header is required for mutations')
    return key


@app.get('/health/live', tags=['Operations'])
def liveness():
    return {'status': 'alive'}


@app.get('/health/ready', tags=['Operations'])
def readiness():
    with reader() as conn:
        conn.execute('SELECT 1').fetchone()
    return {'status': 'ready', 'database': 'postgresql'}


@app.post('/auth/register', status_code=201, tags=['Auth'], summary='Create a student account')
def register(body: Credentials):
    email = str(body.email).lower()
    with transaction() as conn:
        try:
            user = conn.execute('''INSERT INTO users(email,password_hash) VALUES (%s,%s)
                                   ON CONFLICT (email) DO NOTHING RETURNING id''',
                                (email, password_hash.hash(body.password))).fetchone()
        except UniqueViolation:
            user = None
        if not user:
            raise HTTPException(409, 'Email already registered')
        return {'user_id': user['id'], 'access_token': make_token(user['id']),
                'token_type': 'bearer'}


@app.post('/auth/login', tags=['Auth'], summary='Log in and obtain a bearer token')
def login(body: Credentials):
    with reader() as conn:
        user = conn.execute('SELECT id,password_hash FROM users WHERE email=%s',
                            (str(body.email).lower(),)).fetchone()
    if not user or not password_hash.verify(body.password, user['password_hash']):
        raise HTTPException(401, 'Invalid credentials')
    return {'access_token': make_token(user['id']), 'token_type': 'bearer'}


@app.get('/events', tags=['Events'], summary='List concerts and their capacities')
def list_events():
    with reader() as conn:
        rows = conn.execute('''SELECT e.id,e.slug,e.title,e.starts_at,COUNT(s.id) AS capacity
                               FROM events e JOIN seats s ON e.id=s.event_id
                               GROUP BY e.id ORDER BY e.id''').fetchall()
    return [{'id': r['id'], 'slug': r['slug'], 'title': r['title'],
             'starts_at': r['starts_at'].isoformat(), 'capacity': r['capacity']} for r in rows]


@app.get('/events/{event_id}/seats', tags=['Events'], summary='View numbered seats (availability snapshot)')
def view_seats(event_id: int):
    cached = cache_get(event_id)
    if cached is not None:
        return {**cached, 'cache': 'HIT'}
    with reader() as conn:
        if not conn.execute('SELECT 1 FROM events WHERE id=%s', (event_id,)).fetchone():
            raise HTTPException(404, 'Event not found')
        seats = conn.execute('''SELECT s.number, NOT EXISTS (
             SELECT 1 FROM bookings b WHERE b.seat_id=s.id AND
               (b.status='CONFIRMED' OR
                 (b.status='HELD' AND b.hold_expires_at > clock_timestamp()))) AS available
             FROM seats s WHERE s.event_id=%s ORDER BY s.number''',
                             (event_id,)).fetchall()
    payload = {'event_id': event_id, 'available_count': sum(r['available'] for r in seats),
               'seats': [{'number': r['number'], 'available': r['available']} for r in seats],
               'snapshot_only': True}
    set_snapshot(event_id, payload)
    return {**payload, 'cache': 'MISS'}


@app.post('/events/{event_id}/reservations', tags=['Bookings'], summary='Hold a seat or join the queue',
          description='Use an empty JSON body for automatic allocation, or a numbered seat for specific selection. **201:** held, **202:** waitlisted, **409:** conflict. Requires Idempotency-Key.')
def create_reservation(event_id: int, body: ReservationRequest,
                       idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
                       user_id: int = Depends(current_user)):
    with transaction() as conn:
        result = execute_once(conn, user_id, f'reserve:{event_id}', valid_key(idempotency_key),
                              body.model_dump(),
                              lambda: service.reserve(conn, event_id, user_id, body.seat_number))
    return reply(result)


@app.post('/events/{event_id}/waitlist', tags=['Waitlist'])
def enqueue(event_id: int,
            idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
            user_id: int = Depends(current_user)):
    with transaction() as conn:
        result = execute_once(conn, user_id, f'waitlist:{event_id}', valid_key(idempotency_key),
                              {}, lambda: service.explicit_waitlist(conn, event_id, user_id))
    return reply(result)


@app.get('/waitlist/{wait_id}', tags=['Waitlist'])
def waitlist_status(wait_id: UUID, user_id: int = Depends(current_user)):
    with reader() as conn:
        row = conn.execute('''SELECT w.id,w.event_id,w.status,w.offered_booking_id,
                             (SELECT count(*) FROM waitlist ahead WHERE ahead.event_id=w.event_id
                              AND ahead.status='WAITING'
                              AND (ahead.joined_at, ahead.id) <= (w.joined_at, w.id)) AS position
                             FROM waitlist w WHERE w.id=%s AND w.user_id=%s''',
                           (wait_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Waitlist entry not found')
    return {'waitlist_id': str(row['id']), 'event_id': row['event_id'],
            'status': row['status'], 'position': row['position'] if row['status']=='WAITING' else None,
            'offered_booking_id': str(row['offered_booking_id']) if row['offered_booking_id'] else None}


@app.get('/bookings', tags=['Bookings'], summary='Your booking history')
def booking_history(user_id: int = Depends(current_user)):
    with reader() as conn:
        rows = conn.execute('''SELECT b.id,b.event_id,s.number AS seat_number,b.status,
                              b.hold_expires_at,b.created_at FROM bookings b JOIN seats s
                              ON s.id=b.seat_id WHERE b.user_id=%s
                              ORDER BY b.created_at DESC LIMIT 200''', (user_id,)).fetchall()
    return {'bookings': [dict(r, id=str(r['id']),
                              hold_expires_at=r['hold_expires_at'].isoformat(),
                              created_at=r['created_at'].isoformat()) for r in rows]}


@app.get('/bookings/{booking_id}', tags=['Bookings'])
def booking_status(booking_id: UUID, user_id: int = Depends(current_user)):
    with reader() as conn:
        row = conn.execute('''SELECT b.id,b.event_id,s.number AS seat_number,b.status,
                            b.hold_expires_at,b.created_at,b.confirmed_at,clock_timestamp() AS db_now
                            FROM bookings b JOIN seats s ON s.id=b.seat_id
                            WHERE b.id=%s AND b.user_id=%s''', (booking_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Booking not found')
    result = dict(row)
    result.pop('db_now', None)
    result['id'] = str(row['id'])
    for name in ('hold_expires_at','created_at','confirmed_at'):
        result[name] = row[name].isoformat() if row[name] else None
    # A past-due HELD value is presented as logically expired even before sweeper runs.
    if row['status']=='HELD' and row['hold_expires_at'] <= row['db_now']:
        result['status'] = 'EXPIRED_PENDING_RECONCILIATION'
    return result


@app.post('/bookings/{booking_id}/payments', tags=['Payments'], summary='Request simulated asynchronous payment',
          description='Returns **202** with a `payment_id`. Run the worker then check `/payments/{payment_id}`.')
def pay(booking_id: UUID, body: PaymentRequest,
        idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
        user_id: int = Depends(current_user)):
    with transaction() as conn:
        result = execute_once(conn, user_id, f'payment:{booking_id}', valid_key(idempotency_key),
                              body.model_dump(),
                              lambda: service.request_payment(conn,user_id,booking_id,
                                                             body.outcome,body.delay_seconds))
    return reply(result)


@app.get('/payments/{payment_id}', tags=['Payments'])
def payment_status(payment_id: UUID, user_id: int = Depends(current_user)):
    with reader() as conn:
        row = conn.execute('''SELECT id,booking_id,status,outcome,ready_at,processed_at
                              FROM payment_attempts WHERE id=%s AND user_id=%s''',
                           (payment_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Payment not found')
    return {**row,'id':str(row['id']),'booking_id':str(row['booking_id']),
            'ready_at':row['ready_at'].isoformat(),
            'processed_at':row['processed_at'].isoformat() if row['processed_at'] else None}


@app.post('/bookings/{booking_id}/cancel', tags=['Bookings'], summary='Cancel and release your booking')
def cancel(booking_id: UUID,
           idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
           user_id: int = Depends(current_user)):
    with transaction() as conn:
        result = execute_once(conn, user_id, f'cancel:{booking_id}', valid_key(idempotency_key),
                              {}, lambda: service.cancel_booking(conn,user_id,booking_id))
    return reply(result)


@app.get('/bookings/{booking_id}/audit', tags=['Audit'])
def booking_audit(booking_id: UUID, user_id: int = Depends(current_user)):
    with reader() as conn:
        owner = conn.execute('SELECT 1 FROM bookings WHERE id=%s AND user_id=%s',
                             (booking_id,user_id)).fetchone()
        if not owner:
            raise HTTPException(404, 'Booking not found')
        rows = conn.execute('''SELECT id,action,details,created_at FROM booking_audit
                              WHERE booking_id=%s ORDER BY id''', (booking_id,)).fetchall()
    return {'audit': [{**r,'created_at':r['created_at'].isoformat()} for r in rows]}


@app.get('/events/{event_id}/integrity', tags=['Operations'], summary='Verify inventory uniqueness and event capacity')
def integrity_report(event_id: int):
    """A read-only, live invariant report to accompany load test screenshots."""
    with reader() as conn:
        event = conn.execute('SELECT id FROM events WHERE id=%s', (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, 'Event not found')
        x = conn.execute('''SELECT count(*) AS active_tickets,
             count(*) FILTER (WHERE status='CONFIRMED') AS confirmed,
             count(*) FILTER (WHERE status='HELD') AS held,
             count(DISTINCT seat_id) AS distinct_seats
             FROM bookings WHERE event_id=%s AND status IN ('HELD','CONFIRMED')''',
                         (event_id,)).fetchone()
        size = conn.execute('SELECT count(*) AS n FROM seats WHERE event_id=%s',
                            (event_id,)).fetchone()['n']
        queued = conn.execute('''SELECT count(*) AS n FROM waitlist WHERE event_id=%s
                                 AND status='WAITING' ''', (event_id,)).fetchone()['n']
    return {'event_id': event_id, 'capacity': size, 'active_tickets': x['active_tickets'],
            'confirmed': x['confirmed'], 'held': x['held'], 'unique_active_seats': x['distinct_seats'],
            'waiting': queued, 'no_double_booking': x['active_tickets']==x['distinct_seats'],
            'not_oversold': x['active_tickets'] <= size}


@app.post('/waitlist/{wait_id}/leave', tags=['Waitlist'])
def leave_waitlist(wait_id: UUID,
                   idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
                   user_id: int = Depends(current_user)):
    with transaction() as conn:
        result = execute_once(conn, user_id, f'waitlist-leave:{wait_id}',
                              valid_key(idempotency_key), {},
                              lambda: service.leave_waitlist(conn,user_id,wait_id))
    return reply(result)
