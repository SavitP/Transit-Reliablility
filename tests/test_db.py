"""Integration tests: our schema and saving code against a real Postgres + TimescaleDB."""

from datetime import datetime, timedelta, timezone

import pytest

from db import create_schema, save_departures
from tests.conftest import refresh_route_hourly

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


def test_api_reader_can_read_but_not_write(db, db_url):
    import psycopg
    from db import ensure_api_reader

    ensure_api_reader(db, "test-reader-pw")
    ensure_api_reader(db, "test-reader-pw")   # running it again must be fine (every startup)
    save_departures(db, [departure()])
    refresh_route_hourly(db)

    host_part = db_url.split("@", 1)[1]
    with psycopg.connect(f"postgresql://api_reader:test-reader-pw@{host_part}", autocommit=True) as reader:
        assert reader.execute("SELECT count(*) FROM stop_departures").fetchone()[0] == 1
        reader.execute("SELECT count(*) FROM route_hourly").fetchone()   # the summary view too
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("DELETE FROM stop_departures")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("INSERT INTO routes VALUES ('X', 'X', 'X')")

        # The one exception: riders' alert subscriptions (and queuing a test alert).
        db.execute("INSERT INTO routes VALUES ('R1', '7', 'x')")
        db.execute("INSERT INTO stops VALUES ('S3', 'Pike', 47.6, -122.3)")
        sub = reader.execute("""INSERT INTO subscriptions (topic, route_id, stop_id, days, window_start, window_end)
                                VALUES ('t', 'R1', 'S3', '{1}', '07:00', '09:00') RETURNING id""").fetchone()[0]
        reader.execute("INSERT INTO alerts (subscription_id, title, message) VALUES (%s, 'hi', 'test')", (sub,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("UPDATE alerts SET status = 'sent'")        # only the notifier does that
        reader.execute("DELETE FROM subscriptions WHERE id = %s", (sub,))
