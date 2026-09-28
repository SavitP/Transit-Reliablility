"""Notifier: send queued alerts to riders' phones through ntfy.

The processor only *writes down* that an alert should go out (a row in `alerts` with
status 'pending'). This service reads those rows, sends them, and records what happened.
If ntfy is down or slow, alerts wait in the table and are retried; the processor never waits.
"""

import os
import time

import psycopg
import requests

from db import connect
from metrics import notifier_metrics, serve_metrics
from stream import stop_on_sigterm

NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh")      # or your own ntfy server
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")  # for "tap to open" links
POLL_SECONDS = 5
MAX_ATTEMPTS = 5
RATE_LIMIT_PAUSE_SECONDS = 60
METRICS = notifier_metrics()


class RateLimited(Exception):
    """ntfy answered 429 Too Many Requests: we've used up our allowance for now."""


def send_ntfy(topic: str, title: str, message: str, click: str) -> None:
    response = requests.post(NTFY_URL, timeout=10, json={
        "topic": topic, "title": title, "message": message, "click": click,
        "priority": 4,          # "high": makes the phone buzz even if the app is quiet
        "tags": ["bus"],        # shows a 🚌 emoji
    })
    if response.status_code == 429:
        raise RateLimited()
    response.raise_for_status()


def expire_stale(conn: psycopg.Connection) -> int:
    """Don't send alerts that are no longer useful: the bus already reached the stop,
    or (for test notifications) it's been waiting over 2 hours."""
    cur = conn.execute("""
        UPDATE alerts SET status = 'expired'
        WHERE status = 'pending'
          AND ((expected_at IS NOT NULL AND expected_at < now())
               OR created_at < now() - INTERVAL '2 hours')""")
    return cur.rowcount


def send_pending(conn: psycopg.Connection, send=send_ntfy) -> dict:
    """Send up to 20 pending alerts. Returns counts of what happened.

    FOR UPDATE SKIP LOCKED "claims" the rows while we work on them: if a second notifier ever
    ran at the same time, it would skip these rows instead of sending them twice.
    """
    counts = {"sent": 0, "retry": 0, "failed": 0, "rate_limited": False}
    with conn.transaction():
        rows = conn.execute("""
            SELECT a.id, s.topic, a.title, a.message, a.attempts, s.route_id
            FROM alerts a JOIN subscriptions s ON s.id = a.subscription_id
            WHERE a.status = 'pending'
            ORDER BY a.created_at
            LIMIT 20
            FOR UPDATE OF a SKIP LOCKED""").fetchall()
        for alert_id, topic, title, message, attempts, route_id in rows:
            try:
                send(topic, title, message, f"{SITE_URL}/#/route/{route_id}")
            except RateLimited:
                counts["rate_limited"] = True
                break              # stop for now; these stay pending and go out later
            except Exception as e:
                gave_up = attempts + 1 >= MAX_ATTEMPTS
                conn.execute("""UPDATE alerts SET attempts = attempts + 1, last_error = %s,
                                status = CASE WHEN %s THEN 'failed' ELSE status END
                                WHERE id = %s""", (str(e)[:500], gave_up, alert_id))
                counts["failed" if gave_up else "retry"] += 1
                continue
            conn.execute("UPDATE alerts SET status = 'sent', sent_at = now(), attempts = attempts + 1 "
                         "WHERE id = %s", (alert_id,))
            counts["sent"] += 1
    return counts


def wait_for_tables(conn: psycopg.Connection) -> None:
    """The processor creates the tables on startup. On a brand-new system we may start first."""
    while conn.execute("SELECT to_regclass('public.alerts')").fetchone()[0] is None:
        print("Waiting for the processor to create the alerts table...", flush=True)
        time.sleep(5)


def main() -> None:
    serve_metrics()
    conn = connect()
    wait_for_tables(conn)
    print(f"Sending alerts via {NTFY_URL}. Ctrl+C to stop.", flush=True)
    while True:
        METRICS.notifications.labels(result="expired").inc(expire_stale(conn))
        counts = send_pending(conn)
        for result in ("sent", "retry", "failed"):
            METRICS.notifications.labels(result=result).inc(counts[result])
        if counts["sent"] or counts["retry"] or counts["failed"]:
            print(f"sent {counts['sent']}, will retry {counts['retry']}, gave up on {counts['failed']}",
                  flush=True)
        METRICS.pending.set(conn.execute(
            "SELECT count(*) FROM alerts WHERE status = 'pending'").fetchone()[0])
        if counts["rate_limited"]:
            METRICS.rate_limited.inc()
            print(f"ntfy rate limit reached; pausing {RATE_LIMIT_PAUSE_SECONDS}s", flush=True)
            time.sleep(RATE_LIMIT_PAUSE_SECONDS)
        else:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    stop_on_sigterm()
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
