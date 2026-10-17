"""The Last Seat student portal.

Run from the repository root:
    python -m streamlit run frontend/streamlit_app.py
All mutations call the existing FastAPI service. This UI never talks to PostgreSQL.
"""
import html
import os
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from api_client import ApiClient, ApiError, new_idempotency_key
from seat_ui import is_bookable, seat_pages, seat_payload


st.set_page_config(page_title='The Last Seat · Student Portal', page_icon='🎟️',
                   layout='wide', initial_sidebar_state='expanded')
st.markdown(f'<style>{Path(__file__).with_name("styles.css").read_text(encoding="utf-8")}</style>',
            unsafe_allow_html=True)

DEFAULT_API = os.getenv('TICKET_API_URL', 'http://127.0.0.1:8000')
for name, initial in {
    'token': None, 'email': None, 'queue_id': '', 'payment_ids': {},
    'recent_booking_id': None, 'api_url': DEFAULT_API,
}.items():
    if name not in st.session_state:
        st.session_state[name] = initial


def api() -> ApiClient:
    return ApiClient(st.session_state.api_url, st.session_state.token)


def call(method: str, path: str, data: dict | None = None, mutate: bool = False):
    """Return ApiResult or display the exact backend error and return None."""
    client = api()
    try:
        if method == 'GET':
            return client.get(path)
        return client.post(path, data=data,
                           idempotency_key=new_idempotency_key() if mutate else None)
    except ApiError as exc:
        if exc.status == 401 or exc.status == 403:
            st.error('Your session may have expired. Please sign in again.')
        else:
            st.error(f'{exc.message}' + (f' (HTTP {exc.status})' if exc.status else ''))
        if exc.status is None and method != 'GET':
            st.warning('A network error may have occurred after the server accepted the request. '
                       'Check My Tickets or the waitlist before submitting the same action again.')
        return None


def banner(heading: str, subtitle: str, eyebrow: str = 'Campus concert · Student portal'):
    st.markdown('<div class="hero"><div class="eyebrow">' + html.escape(eyebrow) +
                '</div><h1>' + html.escape(heading) + '</h1><p>' +
                html.escape(subtitle) + '</p></div>', unsafe_allow_html=True)


def fmt_time(value):
    if not value:
        return 'Not available'
    try:
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return value.astimezone().strftime('%d %b %Y · %I:%M:%S %p')
    except (TypeError, ValueError):
        return str(value)


def hold_remaining(value):
    try:
        expiry = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        remaining = int((expiry - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            return 'Hold deadline passed; waiting for reconciliation'
        return f'{remaining // 60}m {remaining % 60}s remaining at last refresh'
    except (ValueError, TypeError):
        return 'Refresh for the latest hold status'


def sign_out():
    """Clear the browser session without modifying any bookings in PostgreSQL."""
    for key, value in [('token', None), ('email', None), ('queue_id', ''),
                       ('payment_ids', {}), ('recent_booking_id', None)]:
        st.session_state[key] = value
    st.rerun()


def reserve(event_id: int, seat_number: int | None):
    """Use the existing API to atomically reserve a seat or join FIFO waitlist."""
    response = call('POST', f'/events/{event_id}/reservations',
                    seat_payload(seat_number), mutate=True)
    if not response:
        return
    if response.status == 201:
        st.session_state.recent_booking_id = response.data.get('booking_id')
        st.success(f'Seat {response.data.get("seat_number")} reserved temporarily. '
                   'Go to My Tickets to complete the simulated payment.')
        st.info('Hold expires: ' + fmt_time(response.data.get('hold_expires_at')))
    elif response.status == 202:
        st.session_state.queue_id = response.data.get('waitlist_id', '')
        st.warning('The seat could not be held because the event is full. '
                   'You have joined the waiting list. Open Waitlist to track your entry.')
        st.code(st.session_state.queue_id, language='text')


def clickable_seat_map(seats: list[dict], event_id: int):
    """Native buttons are keyboard accessible and trigger actual API reservations.

    Show 50 at a time to avoid creating 500 Streamlit widgets each rerun.
    """
    pages = seat_pages(seats)
    if not pages:
        st.info('No seats have been configured for this event.')
        return
    options = {label: group for label, group in pages}
    chosen = st.selectbox('Seat section', list(options), key=f'seat_page_{event_id}')
    visible = options[chosen]
    st.caption('Click any available seat number to reserve it immediately. '
               'Unavailable seats cannot be clicked. Availability can change at any time.')
    if not st.session_state.token:
        st.warning('Sign in below to enable seat booking.')
    for start in range(0, len(visible), 5):
        cols = st.columns(5, gap='small')
        for index, seat in enumerate(visible[start:start + 5]):
            number = int(seat['number'])
            available = is_bookable(seat)
            with cols[index]:
                if st.button(('● ' if available else '✕ ') + str(number),
                             key=f'click_seat_{event_id}_{number}',
                             disabled=not available or not st.session_state.token,
                             help=(f'Click to reserve seat {number}' if available
                                   else f'Seat {number} is unavailable'),
                             use_container_width=True):
                    reserve(event_id, number)
    st.caption('● Available and clickable  ·  ✕ Held or confirmed. '
               'The database, not the screen, makes the final decision.')


def auth_screen():
    banner('Your ticket starts here',
           'Sign in to reserve a seat, track a simulated payment and follow the waiting queue.')
    login_tab, register_tab = st.tabs(['Sign in', 'Create an account'])
    with login_tab:
        with st.form('login_form', clear_on_submit=False):
            email = st.text_input('Email address', key='login_email')
            pwd = st.text_input('Password', type='password', key='login_password')
            submitted = st.form_submit_button('Sign in', use_container_width=True)
        if submitted:
            result = call('POST', '/auth/login', {'email': email, 'password': pwd})
            if result and result.data.get('access_token'):
                st.session_state.token = result.data['access_token']
                st.session_state.email = email.lower().strip()
                st.rerun()
    with register_tab:
        st.caption('Demo project. Do not reuse a sensitive personal password.')
        with st.form('register_form', clear_on_submit=False):
            new_email = st.text_input('Email address', key='registration_email')
            new_pwd = st.text_input('Password (8–128 characters)', type='password',
                                    key='registration_password')
            submitted = st.form_submit_button('Register and sign in', use_container_width=True)
        if submitted:
            result = call('POST', '/auth/register', {'email': new_email, 'password': new_pwd})
            if result and result.data.get('access_token'):
                st.session_state.token = result.data['access_token']
                st.session_state.email = new_email.lower().strip()
                st.rerun()


def event_picker():
    result = call('GET', '/events')
    if not result:
        return None
    all_events = result.data
    if not all_events:
        st.info('No concerts found. An administrator must seed an event in PostgreSQL.')
        return None
    show_tests = st.toggle('Show temporary test events', value=False,
                           help='Hide load tests and integration events during student demos.')
    test_prefixes = ('test-', 'load-test-', 'k6-test-', 'race-')
    events = all_events if show_tests else [e for e in all_events
             if not str(e.get('slug', '')).startswith(test_prefixes)]
    if not events:
        st.info('No public concert is available. Enable Show temporary test events to inspect tests.')
        return None
    labels = {f'#{e["id"]}  •  {e["title"]}  ({e["capacity"]} seats)': e for e in events}
    selected = st.selectbox('Choose a concert', list(labels), key='event_picker')
    return labels[selected]


def explore():
    banner('Find your place in the crowd',
           'Browse available seats and hold one before the timer expires.')
    event = event_picker()
    if not event:
        return
    event_id = event['id']
    seats_result = call('GET', f'/events/{event_id}/seats')
    if not seats_result:
        return
    snapshot = seats_result.data
    seats = snapshot.get('seats', [])
    capacity = len(seats)
    available = snapshot.get('available_count', 0)
    k1, k2, k3 = st.columns(3)
    k1.metric('Total seats', capacity)
    k2.metric('Available at last refresh', available)
    k3.metric('Unavailable', capacity - available)
    st.caption('Concert starts: ' + fmt_time(event.get('starts_at')))
    if st.button('↻ Refresh availability', use_container_width=False):
        st.rerun()
    st.markdown('### Choose your seat')
    clickable_seat_map(seats, event_id)
    if not st.session_state.token:
        st.info('Log in below or create an account to enable the seat buttons.')
        return
    st.divider()
    st.markdown('### Prefer any available seat?')
    st.caption('Choose automatic allocation if you do not care which seat you get. '
               'When all seats are held, you will join the waiting list.')
    if st.button('🎟️ Reserve best available seat', type='primary',
                 key=f'auto_reserve_{event_id}', use_container_width=True):
        reserve(event_id, None)


def tickets():
    banner('My Tickets', 'Track your holds, complete a simulated payment and review every booking action.')
    result = call('GET', '/bookings')
    if not result:
        return
    bookings = result.data.get('bookings', [])
    if not bookings:
        st.info('No bookings yet. Select Explore Seats and reserve your first ticket.')
        return
    labels = {f'Seat {b["seat_number"]} · Event {b["event_id"]} · {b["status"]} · {b["id"][:8]}': b
              for b in bookings}
    option_list = list(labels)
    preferred = st.session_state.recent_booking_id
    selected_index = next((i for i, label in enumerate(option_list)
                           if labels[label]['id'] == preferred), 0)
    chosen_label = st.selectbox('Select a booking', option_list, index=selected_index)
    b = labels[chosen_label]
    booking_id = b['id']
    current = call('GET', f'/bookings/{booking_id}')
    if not current:
        return
    row = current.data
    a, c, d = st.columns(3)
    a.metric('Seat', row['seat_number'])
    c.metric('Booking status', row['status'])
    d.metric('Event', row['event_id'])
    st.caption('Booking ID: ' + booking_id)
    if row['status'] == 'HELD':
        st.warning('⏳ ' + hold_remaining(row.get('hold_expires_at')))
        st.caption('Expires at ' + fmt_time(row.get('hold_expires_at')))
        st.markdown('### Simulate payment')
        with st.form('payment_form'):
            outcome = st.selectbox('Payment outcome', ['success', 'failure',
                'delayed_success', 'delayed_failure'],
                help='These are test outcomes. No actual payment is collected.')
            delay = st.slider('Delay in seconds', 0, 120, 10,
                              disabled=not outcome.startswith('delayed'))
            submitted = st.form_submit_button('Process simulated payment',
                                              use_container_width=True)
        if submitted:
            payload = {'outcome': outcome}
            if outcome.startswith('delayed'):
                payload['delay_seconds'] = delay
            response = call('POST', f'/bookings/{booking_id}/payments', payload, mutate=True)
            if response:
                payment_id = response.data.get('payment_id')
                if payment_id:
                    st.session_state.payment_ids[booking_id] = payment_id
                    st.success('Payment requested. The background worker will process it.')
                    st.caption('Payment ID: ' + payment_id)
    elif row['status'] == 'EXPIRED_PENDING_RECONCILIATION':
        st.warning('This hold deadline has passed. Refresh after the worker processes expiration.')
    elif row['status'] == 'CONFIRMED':
        st.success('Your simulated payment is confirmed.')
    else:
        st.info('This booking is not currently payable. Status: ' + row['status'])
    payment_id = st.session_state.payment_ids.get(booking_id)
    if payment_id:
        st.markdown('### Payment tracker')
        st.caption('Your latest payment ID is ' + payment_id)
        if st.button('↻ Refresh payment status'):
            st.rerun()
        payment = call('GET', f'/payments/{payment_id}')
        if payment:
            st.info(f'Payment status: **{payment.data.get("status")}**')
            st.caption('Scheduled: ' + fmt_time(payment.data.get('ready_at')))
    if row['status'] in ('HELD', 'CONFIRMED'):
        st.markdown('### Cancel booking')
        cancel = st.checkbox('I understand that cancellation releases my seat',
                             key=f'cancel_confirm_{booking_id}')
        if st.button('Cancel this booking', disabled=not cancel):
            response = call('POST', f'/bookings/{booking_id}/cancel', {}, mutate=True)
            if response:
                st.success('Booking cancelled. Refunds are simulated only.')
                st.session_state.recent_booking_id = None
                st.rerun()
    st.markdown('### Booking audit trail')
    audit = call('GET', f'/bookings/{booking_id}/audit')
    if audit:
        actions = audit.data.get('audit', [])
        if actions:
            st.dataframe([{'Action': item['action'],
                           'Time': fmt_time(item.get('created_at')),
                           'Details': str(item.get('details', {}))} for item in actions],
                         use_container_width=True, hide_index=True)
        else:
            st.caption('No audit events found.')


def queue_page():
    banner('The waiting room', 'Keep track of your place and act quickly if a seat is offered.')
    wait_id = st.text_input('Waitlist entry ID', value=st.session_state.queue_id,
                             help='Copy the UUID returned when a reservation is waitlisted.')
    if wait_id != st.session_state.queue_id:
        st.session_state.queue_id = wait_id.strip()
    if not wait_id:
        st.info('No waitlist ID saved in this browser session. If you joined earlier, paste its ID above.')
        return
    if st.button('↻ Refresh queue status'):
        st.rerun()
    result = call('GET', f'/waitlist/{wait_id.strip()}')
    if not result:
        return
    row = result.data
    status = row['status']
    col_a, col_b = st.columns(2)
    col_a.metric('Queue status', status)
    col_b.metric('Position', row.get('position') if row.get('position') is not None else '—')
    if status == 'OFFERED':
        st.success('A seat has been offered! Open My Tickets to pay before the hold expires.')
        st.session_state.recent_booking_id = row.get('offered_booking_id')
        st.caption('Offered booking ID: ' + str(row.get('offered_booking_id')))
    elif status == 'WAITING':
        st.info('You are still waiting. A worker may allocate a seat when another hold expires.')
    else:
        st.info('This queue entry is no longer active.')
    if status in ('WAITING', 'OFFERED'):
        if st.button('Leave queue / decline offer'):
            reply = call('POST', f'/waitlist/{wait_id.strip()}/leave', {}, mutate=True)
            if reply:
                st.success('You have left the queue. Any active offer has been released.')
                st.rerun()
    st.caption('The browser stores your last waitlist ID only during this session. '
               'The backend currently does not expose a list of all your queue entries.')


def operations():
    banner('System status', 'Read-only operational evidence from PostgreSQL, the seat authority.')
    event = event_picker()
    if not event:
        return
    report = call('GET', f'/events/{event["id"]}/integrity')
    if not report:
        return
    x = report.data
    a, b, c, d = st.columns(4)
    a.metric('Capacity', x['capacity'])
    b.metric('Active holds', x['held'])
    c.metric('Confirmed', x['confirmed'])
    d.metric('Waiting', x['waiting'])
    if x['no_double_booking'] and x['not_oversold']:
        st.success('Integrity checks pass: no duplicate active seats and no overselling.')
    else:
        st.error('Inventory invariant failed. Stop load tests and investigate the database.')
    st.json(x)
    st.caption('This endpoint is read-only and shows the current database snapshot, not historical totals.')


def help_page():
    banner('How the system works', 'A short guide to the reservation lifecycle.')
    st.markdown('''
**1. Choose a seat.** The portal displays a snapshot of numbered seats. The
PostgreSQL transaction decides availability at the moment of booking.

**2. Hold it.** A successful request creates a time-limited `HELD` booking.
If the event is full, the API places you on a durable first-in-first-out waiting list.

**3. Pay (simulation).** Start a successful, failed or delayed test payment.
The worker processes payments, expirations and new queue offers.

**4. Track the result.** In My Tickets, refresh the booking or payment status.
The audit trail records important state changes. Cancelling an active booking
releases the seat and can trigger a waitlist offer.

**Technical notes**
- No actual money is charged.
- PostgreSQL enforces unique active seat ownership.
- Redis is optional and never the source of truth.
- Streamlit uses HTTP requests and contains no SQL credentials.
- The GUI remembers your JWT only in the active Streamlit session.
- If the FastAPI server restarts with a new JWT secret, sign in again.
''')
    st.link_button('Open detailed REST API docs', st.session_state.api_url + '/docs')


# Sidebar and main routing
with st.sidebar:
    st.markdown('## 🎟️ THE LAST SEAT')
    st.caption('CONCERT RESERVATION PORTAL')
    st.text_input('FastAPI base URL', key='api_url', help='Usually http://127.0.0.1:8000 on Windows.')
    try:
        status = api().get('/health/ready').data
        st.success('API connected · ' + status.get('database', 'ready'))
    except ApiError:
        st.error('API offline · start FastAPI on port 8000')
    st.divider()
    if st.session_state.token:
        st.caption('Signed in as')
        st.write(st.session_state.email or 'Student')
        if st.button('Sign out', key='sidebar_sign_out',
                     type='primary', use_container_width=True):
            sign_out()
    else:
        st.caption('Guest mode · sign in to reserve and pay')
    st.divider()
    menus = ['Explore seats', 'My Tickets', 'Waitlist', 'System status', 'How it works']
    selected_page = st.radio('Navigation', menus, label_visibility='collapsed')

if st.session_state.token:
    account, exit_button = st.columns([4, 1], vertical_alignment='center')
    with account:
        st.caption('● Signed in as ' + html.escape(st.session_state.email or 'Student'))
    with exit_button:
        if st.button('↪ Sign out', key='top_sign_out',
                     use_container_width=True, type='secondary'):
            sign_out()

if not st.session_state.token and selected_page in ('My Tickets', 'Waitlist'):
    auth_screen()
elif selected_page == 'Explore seats':
    explore()
elif selected_page == 'My Tickets':
    tickets()
elif selected_page == 'Waitlist':
    queue_page()
elif selected_page == 'System status':
    operations()
else:
    help_page()

if not st.session_state.token and selected_page == 'Explore seats':
    st.divider()
    auth_screen()
