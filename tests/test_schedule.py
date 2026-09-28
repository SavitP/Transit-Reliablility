"""Tests for schedule time math: the part most likely to be subtly wrong."""

from datetime import datetime

import pytest

from schedule import SEATTLE, gtfs_time_to_seconds, service_day_start


@pytest.mark.parametrize("text, seconds", [
    ("00:00:00", 0),
    ("07:45:00", 7 * 3600 + 45 * 60),
    ("25:10:00", 25 * 3600 + 10 * 60),   # 1:10am the next morning, still "today's" service
])
def test_gtfs_time_to_seconds(text, seconds):
    assert gtfs_time_to_seconds(text) == seconds


@pytest.mark.parametrize("service_date, expected_local_start", [
    ("20260927", datetime(2026, 9, 27, 0, 0)),    # normal day: midnight
    ("20261101", datetime(2026, 11, 1, 1, 0)),    # clocks fall back: 1am
    ("20260308", datetime(2026, 3, 7, 23, 0)),    # clocks spring forward: 11pm the night before
])
def test_service_day_start_handles_daylight_saving(service_date, expected_local_start):
    # Regression test: the first version of this function got both DST days wrong.
    start = service_day_start(service_date).astimezone(SEATTLE)
    assert start.replace(tzinfo=None) == expected_local_start


def test_scheduled_departure_after_midnight(tiny_schedule):
    # Trip LATE's second stop is "24:03:00" on Sept 28 = 12:03am on Sept 29.
    when = tiny_schedule.scheduled_departure("LATE", 2, "20260928").astimezone(SEATTLE)
    assert (when.day, when.hour, when.minute) == (29, 0, 3)


def test_scheduled_departure_unknown_returns_none(tiny_schedule):
    assert tiny_schedule.scheduled_departure("NOPE", 1, "20260928") is None
    assert tiny_schedule.scheduled_departure("T1", 99, "20260928") is None
