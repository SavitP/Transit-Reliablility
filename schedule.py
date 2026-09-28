"""Load King County Metro's static GTFS schedule (the "plan") into memory."""

import csv
import io
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SCHEDULE_URL = "https://metro.kingcounty.gov/GTFS/google_transit.zip"
SCHEDULE_PATH = Path("data/google_transit.zip")
MAX_AGE_SECONDS = 24 * 60 * 60  # re-download once a day; Metro publishes changes every few weeks
SEATTLE = ZoneInfo("America/Los_Angeles")


def ensure_schedule_downloaded() -> Path:
    """Download the schedule zip if we don't have it or our copy is over a day old."""
    fresh = SCHEDULE_PATH.exists() and time.time() - SCHEDULE_PATH.stat().st_mtime < MAX_AGE_SECONDS
    if not fresh:
        print("Downloading static schedule (~10 MB)...")
        SCHEDULE_PATH.parent.mkdir(exist_ok=True)
        response = requests.get(SCHEDULE_URL, timeout=120)
        response.raise_for_status()
        SCHEDULE_PATH.write_bytes(response.content)
    return SCHEDULE_PATH


def gtfs_time_to_seconds(hhmmss: str) -> int:
    """'07:45:00' -> 27900. Hours can go past 24 ('25:10:00' = 1:10am the next morning)."""
    h, m, s = hhmmss.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def service_day_start(service_date: str) -> datetime:
    """The moment a GTFS service day's clock starts counting from.

    GTFS defines it as "noon minus 12 hours", in local time. That's midnight on
    normal days, but 1am or 11pm on the two days a year the clocks change.
    """
    d = date(int(service_date[:4]), int(service_date[4:6]), int(service_date[6:]))
    noon = datetime(d.year, d.month, d.day, 12, tzinfo=SEATTLE)
    # Do the subtraction in UTC. Python's math on local times ignores clock changes.
    return noon.astimezone(timezone.utc) - timedelta(hours=12)


def _read_csv(zf: zipfile.ZipFile, name: str):
    # utf-8-sig quietly strips an invisible marker some tools put at the start of CSV files
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, "utf-8-sig"))


class Schedule:
    """Everything we need from the static GTFS, organized for fast lookups."""

    def __init__(self, path: Path):
        started = time.time()
        with zipfile.ZipFile(path) as zf:
            # route_id -> names riders know, e.g. "100001" -> {"short_name": "1", ...}
            self.routes = {
                r["route_id"]: {"short_name": r["route_short_name"], "description": r["route_desc"] or None}
                for r in _read_csv(zf, "routes.txt")
            }
            self.stops = {
                r["stop_id"]: {"name": r["stop_name"], "lat": float(r["stop_lat"]), "lon": float(r["stop_lon"])}
                for r in _read_csv(zf, "stops.txt")
            }

            # trip_id -> {stop_sequence: (stop_id, scheduled departure in seconds since service-day start)}
            self.stop_times: dict[str, dict[int, tuple[str, int]]] = {}
            for r in _read_csv(zf, "stop_times.txt"):
                self.stop_times.setdefault(r["trip_id"], {})[int(r["stop_sequence"])] = (
                    r["stop_id"],
                    gtfs_time_to_seconds(r["departure_time"]),
                )
        print(f"Loaded schedule: {len(self.routes)} routes, {len(self.stop_times):,} trips "
              f"in {time.time() - started:.1f}s")

    def scheduled_departure(self, trip_id: str, stop_sequence: int, service_date: str) -> datetime | None:
        """When this trip was scheduled to leave this stop, as a UTC date+time. None if unknown."""
        row = self.stop_times.get(trip_id, {}).get(stop_sequence)
        if row is None:
            return None
        return service_day_start(service_date) + timedelta(seconds=row[1])
