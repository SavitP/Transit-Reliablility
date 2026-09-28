"""Tests for deciding when to alert a rider (alerts.py). No database or network needed."""

from datetime import time, timedelta

import pytest

from alerts import AlertChecker, clock

SERVICE_DATE = "20260928"   # a Monday


@pytest.fixture
def checker(tiny_schedule):
    c = AlertChecker(tiny_schedule)
    c.set_subscriptions([{
        "id": "sub-1", "route_id": "R1", "stop_id": "S4", "days": [1, 2, 3, 4, 5],
        "window_start": time(7, 0), "window_end": time(9, 0), "threshold_minutes": 10,
    }])
    return c


def departure(schedule, seq: int, delay_minutes: float, trip: str = "T1", observed_extra_s: int = 0) -> dict:
    """A stop departure like find_departures() produces: trip T1 left stop `seq` this late."""
    scheduled = schedule.scheduled_departure(trip, seq, SERVICE_DATE)
    departed = scheduled + timedelta(minutes=delay_minutes, seconds=observed_extra_s)
    return {"trip_id": trip, "route_id": "R1", "stop_sequence": seq, "stop_id": f"S{seq}",
            "scheduled_departure": scheduled, "departed_at": departed}


def test_alerts_when_lateness_is_confirmed_twice(checker, tiny_schedule):
    assert checker.check(departure(tiny_schedule, 1, 12), SERVICE_DATE) == []   # first sighting
    alerts = checker.check(departure(tiny_schedule, 2, 12), SERVICE_DATE)       # confirmed
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["subscription_id"] == "sub-1" and alert["trip_id"] == "T1"
    assert alert["delay_seconds"] == 12 * 60
    # S4 is scheduled at 8:06; 12 minutes late means around 8:18.
    assert clock(alert["expected_at"]) == "8:18am"
    assert alert["title"] == "Route 1 is running 12 min late"
    assert alert["message"] == "The 8:06am Route 1 to Downtown is expected at Stop S4 around 8:18am."
    assert alert["service_date"] == "2026-09-28"


def test_one_late_reading_is_not_enough(checker, tiny_schedule):
    checker.check(departure(tiny_schedule, 1, 2), SERVICE_DATE)
    assert checker.check(departure(tiny_schedule, 2, 12), SERVICE_DATE) == []   # only one late reading


def test_stops_skipped_in_one_jump_count_as_one_observation(checker, tiny_schedule):
    # Bus jumped past stops 1 and 2 between two reports: both rows share one departure time.
    first = departure(tiny_schedule, 1, 12)
    second = departure(tiny_schedule, 2, 10)
    second["departed_at"] = first["departed_at"]
    assert checker.check(first, SERVICE_DATE) == []
    assert checker.check(second, SERVICE_DATE) == []


def test_uses_the_smaller_of_the_two_delays(checker, tiny_schedule):
    checker.check(departure(tiny_schedule, 1, 15), SERVICE_DATE)
    alert = checker.check(departure(tiny_schedule, 2, 11), SERVICE_DATE)[0]
    assert alert["delay_seconds"] == 11 * 60


def test_below_threshold_does_not_alert(checker, tiny_schedule):
    checker.check(departure(tiny_schedule, 1, 9), SERVICE_DATE)
    assert checker.check(departure(tiny_schedule, 2, 9), SERVICE_DATE) == []


def test_no_alert_once_the_bus_has_passed_the_riders_stop(checker, tiny_schedule):
    checker.check(departure(tiny_schedule, 3, 12), SERVICE_DATE)
    assert len(checker.check(departure(tiny_schedule, 4, 12), SERVICE_DATE)) == 0   # just left S4


def test_outside_time_window_does_not_alert(tiny_schedule):
    c = AlertChecker(tiny_schedule)
    c.set_subscriptions([{"id": "s", "route_id": "R1", "stop_id": "S4", "days": [1],
                          "window_start": time(16, 0), "window_end": time(18, 0),
                          "threshold_minutes": 10}])
    c.check(departure(tiny_schedule, 1, 12), SERVICE_DATE)
    assert c.check(departure(tiny_schedule, 2, 12), SERVICE_DATE) == []


def test_wrong_day_does_not_alert(tiny_schedule):
    c = AlertChecker(tiny_schedule)
    c.set_subscriptions([{"id": "s", "route_id": "R1", "stop_id": "S4", "days": [6, 7],   # weekends
                          "window_start": time(7, 0), "window_end": time(9, 0),
                          "threshold_minutes": 10}])
    c.check(departure(tiny_schedule, 1, 12), SERVICE_DATE)
    assert c.check(departure(tiny_schedule, 2, 12), SERVICE_DATE) == []


def test_other_routes_are_ignored(checker, tiny_schedule):
    checker.set_subscriptions([{"id": "s", "route_id": "OTHER", "stop_id": "S4", "days": [1],
                                "window_start": time(7, 0), "window_end": time(9, 0),
                                "threshold_minutes": 10}])
    checker.check(departure(tiny_schedule, 1, 12), SERVICE_DATE)
    assert checker.check(departure(tiny_schedule, 2, 12), SERVICE_DATE) == []
