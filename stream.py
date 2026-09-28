"""Shared settings and helpers for talking to Redpanda (our message stream)."""

import os
import signal

from confluent_kafka.admin import AdminClient, NewTopic

BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
TOPIC = "vehicle-positions"
PARTITIONS = 3                         # lets up to 3 processors share the work later
RETENTION_MS = 24 * 60 * 60 * 1000     # keep messages for 24 hours, then delete the oldest


def ensure_topic() -> None:
    """Create the topic if it doesn't exist yet (safe to call every startup)."""
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP_SERVERS})
    if TOPIC in admin.list_topics(timeout=10).topics:
        return
    futures = admin.create_topics([NewTopic(TOPIC, num_partitions=PARTITIONS,
                                            config={"retention.ms": str(RETENTION_MS)})])
    try:
        futures[TOPIC].result()
        print(f"Created topic {TOPIC} with {PARTITIONS} partitions")
    except Exception as e:
        if "TOPIC_ALREADY_EXISTS" not in str(e):  # another service created it at the same moment
            raise


def stop_on_sigterm() -> None:
    """Make "docker stop" (SIGTERM) behave like Ctrl+C so we shut down cleanly."""
    def handler(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, handler)
