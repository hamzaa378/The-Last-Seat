"""Fast, database-independent unit tests."""
from app.idempotency import fingerprint
from app.schemas import Credentials, PaymentRequest, ReservationRequest
from pydantic import ValidationError
import pytest


def test_canonical_idempotency_fingerprint_ignores_object_order():
    assert fingerprint({'b': 2, 'a': 1}) == fingerprint({'a': 1, 'b': 2})


def test_payment_outcomes_limited_to_simulated_cases():
    assert PaymentRequest(outcome='delayed_failure', delay_seconds=0).delay_seconds == 0
    with pytest.raises(ValidationError):
        PaymentRequest(outcome='bank_transfer')


def test_no_negative_seat_number():
    with pytest.raises(ValidationError):
        ReservationRequest(seat_number=0)


def test_delay_has_upper_bound():
    with pytest.raises(ValidationError):
        PaymentRequest(outcome='delayed_success', delay_seconds=999999)


def test_weak_password_not_accepted():
    with pytest.raises(ValidationError):
        Credentials(email='student@example.com',password='123')
