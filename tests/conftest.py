"""Shared test setup. pytest loads this file automatically before running any tests.

A "fixture" is something a test needs (sample data, a database connection). A test asks
for one just by naming it as an argument, and pytest builds it and passes it in.
"""

import csv
import io
import os
import time
import zipfile
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

from db import create_schema
from fetch_vehicles import decode_feed, extract_vehicles
from schedule import Schedule

FIXTURES = Path(__file__).parent / "fixtures"

load_dotenv()  # so TEST_DATABASE_URL from .env works locally; CI sets it directly


# ---------- recorded real data ----------

@pytest.fixture(scope="session")  # "session" = build once, share across all tests (loading is slow-ish)
def real_schedule() -> Schedule:
    return Schedule(FIXTURES / "schedule_trimmed.zip")


@pytest.fixture(scope="session")
def snapshots() -> list[list[dict]]:
    """Three real feed snapshots, taken 30s apart, already decoded into vehicle dicts."""
    return [extract_vehicles(decode_feed((FIXTURES / f"vehiclepositions_{i}.pb").read_bytes()))
            for i in range(3)]


# ---------- tiny hand-made schedule for precise tests ----------

def write_gtfs(path: Path, stop_times: list[tuple[str, str, int, str]]) -> Path:
    """Build a minimal GTFS zip. stop_times rows are (trip_id, departure_time, stop_sequence, stop_id)."""
    stop_ids = sorted({row[3] for row in stop_times})

    def to_csv(header, rows):
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(header)
        writer.writerows(rows)
        return out.getvalue()

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("routes.txt", to_csv(["route_id", "route_short_name", "route_desc"],
                                        [["R1", "1", "Test Route"]]))
        z.writestr("stops.txt", to_csv(["stop_id", "stop_name", "stop_lat", "stop_lon"],
                                       [[s, f"Stop {s}", "47.6", "-122.3"] for s in stop_ids]))
        z.writestr("stop_times.txt", to_csv(
            ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
            [[trip, t, t, stop, seq] for trip, t, seq, stop in stop_times]))
    return path


@pytest.fixture
def tiny_schedule(tmp_path) -> Schedule:
    """Trip T1: five stops, two minutes apart, starting 08:00. Trip LATE crosses midnight."""
    rows = [("T1", f"08:{2 * i:02d}:00", i + 1, f"S{i + 1}") for i in range(5)]
    rows += [("LATE", "23:58:00", 1, "S1"), ("LATE", "24:03:00", 2, "S2")]
    return Schedule(write_gtfs(tmp_path / "gtfs.zip", rows))


def report(seq: int, timestamp: int, trip: str = "T1", stop: str | None = None, **overrides) -> dict:
    """A vehicle report shaped like extract_vehicles() output, with sensible defaults."""
    r = {"vehicle_id": "V1", "route_id": "R1", "trip_id": trip, "service_date": "20260928",
         "lat": 47.6, "lon": -122.3, "stop_id": stop or f"S{seq}", "stop_sequence": seq,
         "timestamp": timestamp}
    r.update(overrides)
    return r


# ---------- database (integration tests) ----------

@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping database tests")
    # Safety: these tests delete data. Refuse to run against anything not named *test*.
    if not url.rsplit("/", 1)[-1].endswith("_test"):
        raise RuntimeError(f"TEST_DATABASE_URL must point at a database ending in _test, got {url}")
    return url


@pytest.fixture
def db(db_url):
    """A connection to an empty test database with our schema, cleaned before each test."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        create_schema(conn)
        # Pause TimescaleDB's background jobs (summary refresh, compression). Tests decide
        # when things happen; a job running on its own schedule could collide with a test.
        conn.execute("SELECT alter_job(job_id, scheduled => false) "
                     "FROM timescaledb_information.jobs WHERE job_id >= 1000")
        conn.execute("TRUNCATE stop_departures, routes, stops")
        yield conn


def refresh_route_hourly(conn) -> None:
    """Update the route_hourly summary now, waiting if a background refresh is mid-run.

    A brand-new database starts its refresh job the moment the schema creates it, before
    the fixture above can pause it. Two refreshes of the same hours can't run at once.
    """
    for _ in range(20):
        try:
            conn.execute("CALL refresh_continuous_aggregate('route_hourly', NULL, now())")
            return
        except psycopg.errors.LockNotAvailable:
            time.sleep(0.5)
    raise TimeoutError("route_hourly stayed locked by another refresh for 10 seconds")
