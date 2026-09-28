"""Integration tests: queuing alerts (db.save_alerts) and sending them (notifier.py).

A fake `send` function stands in for ntfy, so no real notifications go out.
"""

from datetime import datetime, timedelta, timezone

import pytest

from db import save_alerts
from notifier import MAX_ATTEMPTS, RateLimited, expire_stale, send_pending


@pytest.fixture
def sub_id(db):
    db.execute("INSERT INTO routes VALUES ('R1', '7', 'Test route')")
    db.execute("INSERT INTO stops VALUES ('S1', 'Pike St', 47.6, -122.3)")
    return db.execute("""INSERT INTO subscriptions (topic, route_id, stop_id, days, window_start, window_end)
                         VALUES ('test-topic', 'R1', 'S1', '{1,2,3,4,5}', '07:00', '09:00')
                         RETURNING id""").fetchone()[0]


def alert(sub_id, trip="T1", minutes_until_bus=20) -> dict:
    return {"subscription_id": sub_id, "trip_id": trip, "service_date": "2026-09-28",
            "delay_seconds": 720,
            "expected_at": datetime.now(timezone.utc) + timedelta(minutes=minutes_until_bus),
            "title": "Route 7 is running 12 min late", "message": "The 8:06am Route 7 ..."}


def statuses(db):
    return [r[0] for r in db.execute("SELECT status FROM alerts ORDER BY id").fetchall()]


# ---------- queuing ----------

def test_same_trip_is_only_alerted_once(db, sub_id):
    assert save_alerts(db, [alert(sub_id)]) == 1
    assert save_alerts(db, [alert(sub_id)]) == 0     # processor sees the same late trip again


def test_cooldown_between_alerts_for_one_subscription(db, sub_id):
    assert save_alerts(db, [alert(sub_id, trip="T1"), alert(sub_id, trip="T2")]) == 1
    db.execute("UPDATE alerts SET created_at = now() - INTERVAL '31 minutes'")
    assert save_alerts(db, [alert(sub_id, trip="T3")]) == 1   # cooldown over


# ---------- sending ----------

def test_sends_pending_alerts(db, sub_id):
    save_alerts(db, [alert(sub_id)])
    sent = []
    counts = send_pending(db, send=lambda topic, title, message, click: sent.append((topic, title, click)))
    assert counts["sent"] == 1
    assert sent == [("test-topic", "Route 7 is running 12 min late", "http://localhost:8000/#/route/R1")]
    assert statuses(db) == ["sent"]
    assert send_pending(db, send=lambda *a: sent.append(a))["sent"] == 0   # not sent twice


def test_failed_send_is_retried_then_given_up(db, sub_id):
    save_alerts(db, [alert(sub_id)])

    def broken(*args):
        raise ConnectionError("ntfy unreachable")

    for _ in range(MAX_ATTEMPTS - 1):
        assert send_pending(db, send=broken)["retry"] == 1
        assert statuses(db) == ["pending"]
    assert send_pending(db, send=broken)["failed"] == 1
    row = db.execute("SELECT status, attempts, last_error FROM alerts").fetchone()
    assert row == ("failed", MAX_ATTEMPTS, "ntfy unreachable")


def test_rate_limit_leaves_alerts_pending_without_using_an_attempt(db, sub_id):
    save_alerts(db, [alert(sub_id)])

    def limited(*args):
        raise RateLimited()

    assert send_pending(db, send=limited)["rate_limited"] is True
    assert db.execute("SELECT status, attempts FROM alerts").fetchone() == ("pending", 0)


def test_alerts_for_buses_that_already_arrived_expire(db, sub_id):
    save_alerts(db, [alert(sub_id, minutes_until_bus=-1)])
    assert expire_stale(db) == 1
    assert statuses(db) == ["expired"]
    assert send_pending(db, send=lambda *a: pytest.fail("should not send"))["sent"] == 0
