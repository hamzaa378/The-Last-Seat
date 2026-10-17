"""Protect real events from maintenance cleanup even if an ID is mistyped."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cleanup_test_event import is_test_event


def test_main_concert_protected():
    assert not is_test_event({'id': 1, 'slug': 'campus-concert'})
    assert not is_test_event({'id': 13, 'slug': 'campus-concert'})
    assert not is_test_event({'id': 2, 'slug': 'regular-concert'})


def test_temporary_events_allowed():
    assert is_test_event({'id': 13, 'slug': 'load-test-abc123'})
    assert is_test_event({'id': 2, 'slug': 'race-abcdef'})
    assert is_test_event({'id': 3, 'slug': 'test-aabbcc'})


def test_id_1_never_deleted():
    assert not is_test_event({'id': 1, 'slug': 'test-deliberate'})
