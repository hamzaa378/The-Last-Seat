"""Frontend transport tests need httpx, not Streamlit or a live database."""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'frontend'))
from api_client import ApiClient, ApiError, describe_error, new_idempotency_key


def test_get_list_events():
    seen = []
    def server(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json=[{'id': 13, 'capacity': 500}])
    api = ApiClient('http://127.0.0.1:8000', transport=httpx.MockTransport(server))
    result = api.get('/events')
    assert result.status == 200 and result.data[0]['capacity'] == 500
    assert seen == [('GET', '/events')]


def test_reservation_headers_and_waitlist_202():
    def server(request):
        assert request.headers['authorization'] == 'Bearer fake-token'
        assert request.headers['idempotency-key'] == 'ui-unique-0001'
        assert request.url.path == '/events/13/reservations'
        assert request.content == b'{}'
        return httpx.Response(202, json={'status': 'WAITING', 'waitlist_id': 'uuid'})
    api = ApiClient('http://localhost:8000', token='fake-token',
                    transport=httpx.MockTransport(server))
    result = api.post('/events/13/reservations', {}, idempotency_key='ui-unique-0001')
    assert result.status == 202 and result.data['status'] == 'WAITING'


def test_expected_booking_conflict_has_readable_message():
    def server(_):
        return httpx.Response(409, json={'detail': {'reason': 'SEAT_UNAVAILABLE',
                                                     'message': 'Try another seat number'}})
    client = ApiClient('http://localhost:8000', transport=httpx.MockTransport(server))
    with pytest.raises(ApiError) as info:
        client.post('/events/1/reservations', {'seat_number': 1}, 'key-12345')
    assert info.value.status == 409
    assert 'another seat' in info.value.message


def test_http_401_does_not_leak_token_in_error():
    def server(_):
        return httpx.Response(401, json={'detail': 'Invalid or expired access token'})
    client = ApiClient('http://localhost:8000', token='keep-private',
                       transport=httpx.MockTransport(server))
    with pytest.raises(ApiError) as info:
        client.get('/bookings')
    assert 'keep-private' not in info.value.message


def test_idempotency_key_is_unique_and_long_enough():
    a, b = new_idempotency_key(), new_idempotency_key()
    assert len(a) >= 8 and len(a) <= 128 and a != b


def test_validation_errors_are_readable():
    assert 'invalid' in describe_error({'detail': [{'msg': 'invalid email'}]}, 422)
