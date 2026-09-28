"""Integration tests: our schema and saving code against a real Postgres + TimescaleDB."""

from datetime import datetime, timedelta, timezone

from db import create_schema, save_departures

T = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)


def departure(**overrides) -> dict:
    row = {"scheduled_departure": T, "trip_id": "T1", "stop_sequence": 3, "route_id": "R1",
           "stop_id": "S3", "vehicle_id": "V1", "departed_at": T + timedelta(seconds=75),
           "observation_gap_s": 30}
    row.update(overrides)
    return row


def test_schema_can_be_applied_repeatedly(db):
    create_schema(db)   # the fixture already applied it once; a second time must not fail
    create_schema(db)


def test_delay_is_calculated_by_the_database(db):
    save_departures(db, [departure()])
    assert db.execute("SELECT delay_seconds FROM stop_departures").fetchone()[0] == 75


def test_saving_the_same_departure_twice_keeps_one_row(db):
    assert save_departures(db, [departure()]) == 1
    # Same trip + stop + scheduled time, even with a slightly different estimate: a duplicate.
    assert save_departures(db, [departure(departed_at=T + timedelta(seconds=80))]) == 0
    assert db.execute("SELECT count(*) FROM stop_departures").fetchone()[0] == 1


def test_table_is_a_hypertable(db):
    names = db.execute("SELECT hypertable_name FROM timescaledb_information.hypertables").fetchall()
    assert ("stop_departures",) in names
