"""Ingester: fetch the live feed every 30s and publish each vehicle report to Redpanda.

It does one small job and doesn't need the schedule or the database, so it rarely breaks.
"""

import json
import time

from confluent_kafka import Producer

from fetch_vehicles import VEHICLE_POSITIONS_URL, decode_feed, download_feed, extract_vehicles
from metrics import ingester_metrics, serve_metrics
from stream import BOOTSTRAP_SERVERS, TOPIC, ensure_topic, stop_on_sigterm

POLL_SECONDS = 30
METRICS = ingester_metrics()

failed_deliveries = 0


def on_delivery(err, msg) -> None:
    """Called by the producer for each message once Redpanda confirms it (or gives up)."""
    global failed_deliveries
    if err is not None:
        failed_deliveries += 1
        METRICS.publish_failures.inc()


def main() -> None:
    serve_metrics()
    ensure_topic()
    producer = Producer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "acks": "all",                 # only count a message as sent once it's safely stored
        "enable.idempotence": True,    # retries never create duplicate or out-of-order messages
        "linger.ms": 50,               # wait up to 50ms to send messages in batches
    })
    print(f"Publishing to {TOPIC} every {POLL_SECONDS}s. Ctrl+C to stop.")

    while True:
        try:
            feed = decode_feed(download_feed(VEHICLE_POSITIONS_URL))
        except Exception as e:
            METRICS.feed_fetches.labels(result="error").inc()
            print(f"Fetch failed, will retry: {e}", flush=True)
            time.sleep(POLL_SECONDS)
            continue
        METRICS.feed_fetches.labels(result="ok").inc()
        METRICS.feed_timestamp.set(feed.header.timestamp)
        vehicles = extract_vehicles(feed)

        for v in vehicles:
            producer.produce(
                TOPIC,
                # The key decides the partition. Same trip -> same partition -> kept in order.
                key=v["trip_id"] or v["vehicle_id"],
                value=json.dumps(v),
                timestamp=v["timestamp"] * 1000,   # when the bus reported, in milliseconds
                on_delivery=on_delivery,
            )
        METRICS.reports_published.inc(len(vehicles))
        # If Redpanda is down, messages wait in memory here and are retried automatically.
        unsent = producer.flush(10)
        print(f"published {len(vehicles)} reports "
              f"({unsent} still waiting to send, {failed_deliveries} failed so far)", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    stop_on_sigterm()
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
