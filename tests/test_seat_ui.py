"""Frontend seat-picker helpers: no Streamlit or database required."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'frontend'))
from seat_ui import is_bookable, seat_pages, seat_payload


def test_seat_click_payload():
    assert seat_payload(17) == {'seat_number': 17}
    assert seat_payload(None) == {}
    with pytest.raises(ValueError):
        seat_payload(0)
    with pytest.raises(ValueError):
        seat_payload(True)


def test_available_only():
    assert is_bookable({'number': 1, 'available': True})
    assert not is_bookable({'number': 2, 'available': False})
    assert not is_bookable({'number': 3})


def test_seats_500_paged_without_loss():
    source = [{'number': i, 'available': i % 2 == 0} for i in range(500, 0, -1)]
    pages = seat_pages(source)
    assert len(pages) == 10
    assert pages[0][0] == 'Seats 1–50'
    assert pages[-1][0] == 'Seats 451–500'
    assert [int(s['number']) for _, block in pages for s in block] == list(range(1, 501))


def test_seat_page_rejects_invalid_size():
    with pytest.raises(ValueError):
        seat_pages([{'number': 1}], 0)
