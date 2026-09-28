"""Poll the live feed, match buses to the schedule, and record how late they are.

Run:  python track_delays.py      (Ctrl+C to stop)
Results are saved to the stop_departures table in Postgres.
"""

import time
from datetime import datetime, timezone

from db import connect, create_schema, load_reference_data, save_departures
from fetch_vehicles import VEHICLE_POSITIONS_URL, decode_feed, download_feed, extract_vehicles
from schedule import SEATTLE, Schedule, ensure_schedule_downloaded

POLL_SECONDS = 30          # buses report about every 30s; polling faster just re-reads the same data
MAX_GAP_SECONDS = 120      # if we lost sight of a bus longer than this, our time estimate is too fuzzy


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
    moment as the halfway point, then compare it to the schedule.
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
        scheduled = schedule.scheduled_departure(current["trip_id"], seq, current["service_date"])
        rows.append({
            "scheduled_departure": scheduled,
            "trip_id": current["trip_id"],
            "stop_sequence": seq,
            "route_id": current["route_id"],
            "stop_id": stops[seq][0],
            "vehicle_id": current["vehicle_id"],
            "departed_at": estimated,
            "observation_gap_s": gap,
        })
    return rows


def main() -> None:
    schedule = Schedule(ensure_schedule_downloaded())
    conn = connect()
    create_schema(conn)
    load_reference_data(conn, schedule)
    last_seen: dict[str, dict] = {}  # trip_id -> most recent matched report for that trip

    print(f"Polling every {POLL_SECONDS}s. Saving to the database. Ctrl+C to stop.\n")
    while True:
        try:
            vehicles = extract_vehicles(decode_feed(download_feed(VEHICLE_POSITIONS_URL)))
        except Exception as e:  # one failed download shouldn't kill a long-running tracker
            print(f"Fetch failed, will retry: {e}")
            time.sleep(POLL_SECONDS)
            continue

        in_service = [v for v in vehicles if v["trip_id"]]
        matched = [v for v in in_service if matches_schedule(schedule, v)]

        new_rows = []
        for v in matched:
            previous = last_seen.get(v["trip_id"])
            if previous is not None and v["timestamp"] > previous["timestamp"]:
                new_rows.extend(find_departures(schedule, previous, v))
            if previous is None or v["timestamp"] > previous["timestamp"]:
                last_seen[v["trip_id"]] = v

        saved = save_departures(conn, new_rows)

        now = datetime.now(SEATTLE).strftime("%H:%M:%S")
        pct = 100 * len(matched) / len(in_service) if in_service else 0
        late = [r for r in new_rows if (r["departed_at"] - r["scheduled_departure"]).total_seconds() > 300]
        print(f"{now}  {len(in_service)} buses in service, {len(matched)} matched ({pct:.0f}%), "
              f"{saved} stop departures saved, {len(late)} were 5+ min late")
        for r in late[:3]:
            minutes = (r["departed_at"] - r["scheduled_departure"]).total_seconds() / 60
            print(f"          Route {schedule.routes[r['route_id']]['short_name']:<6} {minutes:5.1f} min late "
                  f"leaving {schedule.stops[r['stop_id']]['name']}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
