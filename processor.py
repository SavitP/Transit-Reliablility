"""Processor: read vehicle reports from Redpanda, calculate delays, save them to Postgres."""

import json
import time
from datetime import timedelta

from confluent_kafka import OFFSET_BEGINNING, OFFSET_END, Consumer, TopicPartition

from db import connect, create_schema, load_reference_data, save_departures
from delays import DelayCalculator, matches_schedule
from metrics import processor_metrics, serve_metrics
from schedule import Schedule, ensure_schedule_downloaded
from stream import BOOTSTRAP_SERVERS, TOPIC, ensure_topic, stop_on_sigterm

REWIND = timedelta(minutes=3)   # how far to re-read on startup, to rebuild memory of each bus
METRICS = processor_metrics()
STATUS_EVERY_SECONDS = 15   # also how often we update the "messages behind" measurement


def main() -> None:
    serve_metrics()
    schedule = Schedule(ensure_schedule_downloaded())
    conn = connect()
    create_schema(conn)
    load_reference_data(conn, schedule)
    calculator = DelayCalculator(schedule)
    ensure_topic()

    def rewind(consumer: Consumer, partitions: list[TopicPartition]) -> None:
        """Decide where to start reading, each time we're given partitions to read.

        We ask the database how far we got, then start REWIND earlier than that. Re-reading
        a few minutes rebuilds `last_seen`. Rows we already saved are skipped by the
        database's duplicate check, so re-reading is harmless.
        """
        last_saved = conn.execute("SELECT max(departed_at) FROM stop_departures").fetchone()[0]
        if last_saved is None:
            for p in partitions:
                p.offset = OFFSET_BEGINNING      # empty database: start from the oldest message
        else:
            start_ms = int((last_saved - REWIND).timestamp() * 1000)
            for p in partitions:
                p.offset = start_ms              # offsets_for_times reads this as a timestamp
            partitions = consumer.offsets_for_times(partitions, timeout=10)
            for p in partitions:
                if p.offset < 0:
                    p.offset = OFFSET_END        # nothing that recent: wait for new messages
            print(f"Resuming from {(last_saved - REWIND):%H:%M:%S} UTC "
                  f"({REWIND.seconds // 60} min before the last saved departure)", flush=True)
        consumer.assign(partitions)

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": "delay-processor",   # processors with the same group share the partitions
        "enable.auto.commit": False,     # our bookmark is the database, not Redpanda (see rewind)
    })
    consumer.subscribe([TOPIC], on_assign=rewind)
    print("Waiting for vehicle reports. Ctrl+C to stop.", flush=True)

    processed, saved, last_status = 0, 0, time.time()
    newest_report = 0   # bus report time of the newest message we've processed
    try:
        while True:
            messages = consumer.consume(num_messages=500, timeout=1.0)
            rows = []
            for msg in messages:
                if msg.error():
                    print(f"Stream error: {msg.error()}", flush=True)
                    continue
                report = json.loads(msg.value())
                METRICS.reports_processed.inc()
                if report["trip_id"]:
                    METRICS.reports_in_service.inc()
                    if matches_schedule(schedule, report):
                        METRICS.reports_matched.inc()
                newest_report = max(newest_report, report["timestamp"])
                rows.extend(calculator.process(report))
            if newest_report:   # stays unset until the first message, instead of reporting 0 (1970)
                METRICS.last_report_timestamp.set(newest_report)
            processed += len(messages)
            with METRICS.db_write_seconds.time():
                new_rows = save_departures(conn, rows)
            METRICS.departures_saved.inc(new_rows)
            saved += new_rows

            if time.time() - last_status >= STATUS_EVERY_SECONDS:
                behind = messages_behind(consumer)
                METRICS.messages_behind.set(behind)
                print(f"processed {processed} reports, saved {saved} departures, "
                      f"{behind} reports waiting", flush=True)
                processed, saved, last_status = 0, 0, time.time()
    finally:
        consumer.close()   # tell Redpanda we're leaving, so partitions are handed off quickly


def messages_behind(consumer: Consumer) -> int:
    """How many messages have arrived in the stream that we haven't read yet ("lag")."""
    behind = 0
    for p in consumer.assignment():
        _, newest = consumer.get_watermark_offsets(p, cached=False, timeout=5)
        position = consumer.position([p])[0].offset
        if position >= 0:
            behind += newest - position
    return behind


if __name__ == "__main__":
    stop_on_sigterm()
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
