"""Small, testable helpers for the Streamlit clickable seat picker.

Not responsible for concurrency. Every click is verified by FastAPI/PostgreSQL.
"""

from math import ceil


PAGE_SIZE = 50


def seat_pages(seats: list[dict], page_size: int = PAGE_SIZE) -> list[tuple[str, list[dict]]]:
    """Return labeled consecutive pages of seats without dropping any."""
    if page_size < 1:
        raise ValueError('page_size must be positive')
    ordered = sorted(seats, key=lambda s: int(s['number']))
    result = []
    for offset in range(0, len(ordered), page_size):
        group = ordered[offset:offset + page_size]
        result.append((f'Seats {int(group[0]["number"])}–{int(group[-1]["number"])}', group))
    return result


def seat_payload(number: int | None) -> dict:
    """None requests an auto-assigned seat; integer requests that exact seat."""
    if number is None:
        return {}
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValueError('Seat numbers must be positive integers')
    return {'seat_number': number}


def is_bookable(seat: dict) -> bool:
    return bool(seat.get('available', False))
