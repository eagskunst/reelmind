import pytest

from reelmind.models import Event, Place


@pytest.mark.parametrize("value", ["", "  ", "null", "NULL", "none", "Unknown", "N/A"])
def test_place_emptyish_strings_become_none(value):
    p = Place(name="X", address=value, city=value, kind=value, notes=value)
    assert p.address is None and p.city is None and p.kind is None and p.notes is None


def test_place_real_values_kept_and_stripped():
    p = Place(name="X", city="  Madrid ", price_range="€€")
    assert p.city == "Madrid" and p.price_range == "€€"


@pytest.mark.parametrize("value", ["", "unknown", "15 de marzo", "2026-1-1", "tomorrow"])
def test_event_bad_dates_become_none(value):
    e = Event(name="Feria", start_date=value, end_date=value)
    assert e.start_date is None and e.end_date is None


def test_event_iso_dates_kept():
    e = Event(name="Feria", start_date="2026-10-03", end_date="2026-10-05", venue="unknown")
    assert e.start_date == "2026-10-03" and e.end_date == "2026-10-05"
    assert e.venue is None
