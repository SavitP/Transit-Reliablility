"""Connecting to Postgres and writing our data into it."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from schedule import Schedule

load_dotenv()  # copies the lines from .env into os.environ (only ones not already set)


def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return psycopg.connect(url, autocommit=True)


def create_schema(conn: psycopg.Connection) -> None:
    conn.execute(Path(__file__).with_name("schema.sql").read_text())


def load_reference_data(conn: psycopg.Connection, schedule: Schedule) -> None:
    """Copy route and stop names from the schedule into the database (insert or update)."""
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO routes (route_id, short_name, description) VALUES (%s, %s, %s)
               ON CONFLICT (route_id) DO UPDATE
               SET short_name = EXCLUDED.short_name, description = EXCLUDED.description""",
            [(rid, r["short_name"], r["description"]) for rid, r in schedule.routes.items()],
        )
        cur.executemany(
            """INSERT INTO stops (stop_id, name, lat, lon) VALUES (%s, %s, %s, %s)
               ON CONFLICT (stop_id) DO UPDATE
               SET name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon""",
            [(sid, s["name"], s["lat"], s["lon"]) for sid, s in schedule.stops.items()],
        )


def save_departures(conn: psycopg.Connection, rows: list[dict]) -> int:
    """Insert departure rows. Returns how many were new (duplicates are skipped)."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO stop_departures
                   (scheduled_departure, trip_id, stop_sequence, route_id, stop_id,
                    vehicle_id, departed_at, observation_gap_s)
               VALUES (%(scheduled_departure)s, %(trip_id)s, %(stop_sequence)s, %(route_id)s,
                       %(stop_id)s, %(vehicle_id)s, %(departed_at)s, %(observation_gap_s)s)
               ON CONFLICT DO NOTHING""",
            rows,
            returning=False,
        )
        return cur.rowcount
