"""Tests for the matching and delay logic: the heart of the project."""

from datetime import datetime, timezone

from delays import DelayCalculator, find_departures, matches_schedule
from tests.conftest import report

# 08:00 Seattle time on the service date used by report() (2026-09-28, PDT = UTC-7).
EIGHT_AM = int(datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc).timestamp())


# ---------- matching ----------

def test_matches_a_consistent_report(tiny_schedule):
    assert matches_schedule(tiny_schedule, report(seq=2, timestamp=EIGHT_AM))


def test_rejects_out_of_service_bus(tiny_schedule):
    assert not matches_schedule(tiny_schedule, report(2, EIGHT_AM, trip_id=None))


def test_rejects_trip_missing_from_schedule(tiny_schedule):
    assert not matches_schedule(tiny_schedule, report(2, EIGHT_AM, trip="UNKNOWN"))


def test_rejects_stop_number_and_stop_id_that_disagree(tiny_schedule):
    assert not matches_schedule(tiny_schedule, report(seq=2, timestamp=EIGHT_AM, stop="S4"))


def test_rejects_bus_not_yet_on_its_trip(tiny_schedule):
    # Buses assigned to their next trip show up with stop_sequence 0 and no stop.
    assert not matches_schedule(tiny_schedule, report(seq=0, timestamp=EIGHT_AM, stop=""))


# ---------- departure detection ----------

def test_departure_is_estimated_halfway_between_reports(tiny_schedule):
    # Heading to stop 2 at 8:03:00, heading to stop 3 at 8:03:30 -> left stop 2 at ~8:03:15.
    # Stop 2 was scheduled at 8:02:00, so it's 75 seconds late.
    rows = find_departures(tiny_schedule, report(2, EIGHT_AM + 180), report(3, EIGHT_AM + 210))
    assert len(rows) == 1
    row = rows[0]
    assert row["stop_sequence"] == 2 and row["stop_id"] == "S2"
    assert row["departed_at"] == datetime.fromtimestamp(EIGHT_AM + 195, tz=timezone.utc)
    assert (row["departed_at"] - row["scheduled_departure"]).total_seconds() == 75
    assert row["observation_gap_s"] == 30


def test_skipping_stops_records_each_one(tiny_schedule):
    # Went from "heading to 2" to "heading to 5": left stops 2, 3 and 4.
    rows = find_departures(tiny_schedule, report(2, EIGHT_AM), report(5, EIGHT_AM + 60))
    assert [r["stop_sequence"] for r in rows] == [2, 3, 4]


def test_no_movement_means_no_departures(tiny_schedule):
    assert find_departures(tiny_schedule, report(3, EIGHT_AM), report(3, EIGHT_AM + 30)) == []


def test_long_silence_is_skipped_rather_than_guessed(tiny_schedule):
    assert find_departures(tiny_schedule, report(2, EIGHT_AM), report(4, EIGHT_AM + 121)) == []


# ---------- the calculator's memory ----------

def test_calculator_needs_two_reports(tiny_schedule):
    calc = DelayCalculator(tiny_schedule)
    assert calc.process(report(2, EIGHT_AM)) == []          # first sighting: nothing to compare
    assert len(calc.process(report(3, EIGHT_AM + 30))) == 1  # second: one departure


def test_calculator_ignores_repeated_and_older_reports(tiny_schedule):
    calc = DelayCalculator(tiny_schedule)
    calc.process(report(2, EIGHT_AM))
    assert calc.process(report(2, EIGHT_AM)) == []            # exact repeat (feed not refreshed)
    assert calc.process(report(1, EIGHT_AM - 30)) == []       # older report arriving late
    assert calc.last_seen["T1"]["timestamp"] == EIGHT_AM      # memory not overwritten


def test_replaying_the_same_reports_gives_the_same_rows(tiny_schedule):
    # Phase 5 relies on this: after a restart the processor re-reads old messages.
    reports = [report(1, EIGHT_AM), report(2, EIGHT_AM + 30), report(4, EIGHT_AM + 60)]
    runs = []
    for _ in range(2):
        calc = DelayCalculator(tiny_schedule)
        runs.append([row for r in reports for row in calc.process(r)])
    assert runs[0] == runs[1] and len(runs[0]) == 3


# ---------- end to end on real recorded data ----------

def test_real_snapshots_produce_sensible_delays(real_schedule, snapshots):
    calc = DelayCalculator(real_schedule)
    rows = [row for snapshot in snapshots for v in snapshot for row in calc.process(v)]

    assert len(rows) > 20, "expected plenty of departures from three real snapshots"
    for row in rows:
        delay = (row["departed_at"] - row["scheduled_departure"]).total_seconds()
        assert -30 * 60 < delay < 90 * 60, row          # nothing absurd, like a day off
        assert row["observation_gap_s"] <= 120
        assert real_schedule.stop_times[row["trip_id"]][row["stop_sequence"]][0] == row["stop_id"]


def test_real_snapshots_match_rate(real_schedule, snapshots):
    in_service = [v for v in snapshots[0] if v["trip_id"]]
    matched = [v for v in in_service if matches_schedule(real_schedule, v)]
    assert len(matched) / len(in_service) > 0.9
