"""The delay logic: match vehicle reports to the schedule and detect stop departures.

This file doesn't know or care how reports arrive (HTTP, a message stream, a test).
It just takes reports in and hands departure rows out.
"""

from datetime import datetime, timezone

from schedule import Schedule

MAX_GAP_SECONDS = 120  # if we lost sight of a bus longer than this, our time estimate is too fuzzy


def matches_schedule(schedule: Schedule, v: dict) -> bool:
    """Is this report something we can line up with a scheduled trip and stop?"""
    if v["trip_id"] is None or v["service_date"] is None:
        return False  # not in passenger service
    stops = schedule.stop_times.get(v["trip_id"])
    if stops is None:
        return False  # trip isn't in our schedule (schedule out of date, or an extra bus)
    row = stops.get(v["stop_sequence"])
    # The stop number and stop ID must agree. If they don't, the report is inconsistent
    # (or the bus hasn't started this trip yet, which shows up as stop_sequence 0).
    return row is not None and row[0] == v["stop_id"]


def find_departures(schedule: Schedule, previous: dict, current: dict) -> list[dict]:
    """Compare two reports from the same trip and return one row per stop the bus left in between.

    If the last report said "heading to stop #5" and this one says "heading to stop #7",
    the bus left stops #5 and #6 sometime between those two reports. We estimate that
    moment as the halfway point.
    """
    if current["stop_sequence"] <= previous["stop_sequence"]:
        return []  # hasn't moved on to a new stop yet
    gap = current["timestamp"] - previous["timestamp"]
    if gap > MAX_GAP_SECONDS:
        return []  # bus went quiet for too long; guessing would give bad data, so skip

    estimated = datetime.fromtimestamp(previous["timestamp"] + gap / 2, tz=timezone.utc)
    rows = []
    stops = schedule.stop_times[current["trip_id"]]
    for seq in range(previous["stop_sequence"], current["stop_sequence"]):
        if seq not in stops:
            continue  # stop numbers can skip values (1, 2, 5...) in GTFS
        rows.append({
            "scheduled_departure": schedule.scheduled_departure(current["trip_id"], seq, current["service_date"]),
            "trip_id": current["trip_id"],
            "stop_sequence": seq,
            "route_id": current["route_id"],
            "stop_id": stops[seq][0],
            "vehicle_id": current["vehicle_id"],
            "departed_at": estimated,
            "observation_gap_s": gap,
        })
    return rows


class DelayCalculator:
    """Remembers the last report for each trip, so it can spot when a bus moves on to a new stop."""

    def __init__(self, schedule: Schedule):
        self.schedule = schedule
        self.last_seen: dict[str, dict] = {}  # trip_id -> most recent matched report for that trip

    def process(self, report: dict) -> list[dict]:
        """Feed in one vehicle report; get back any stop departures it reveals."""
        if not matches_schedule(self.schedule, report):
            return []
        previous = self.last_seen.get(report["trip_id"])
        if previous is not None and report["timestamp"] <= previous["timestamp"]:
            return []  # same or older report than we already have: nothing new
        self.last_seen[report["trip_id"]] = report
        if previous is None:
            return []  # first sighting of this trip: need a second report to see movement
        return find_departures(self.schedule, previous, report)
