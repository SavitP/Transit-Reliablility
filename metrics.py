"""Measurements our services expose for Prometheus to collect.

Each service starts a tiny web server (port 9100) whose /metrics page lists its numbers
as plain text. Prometheus fetches that page every 15 seconds and remembers every value.

Naming follows Prometheus conventions: a `transit_` prefix, units in the name
(`_seconds`), and `_total` for counters.

Metrics are created inside functions, and each service calls only its own function.
Creating a metric registers it in that program, so defining everything at the top of
this file would make the ingester report processor metrics (stuck at 0) and vice versa.
"""

from types import SimpleNamespace

from prometheus_client import Counter, Gauge, Histogram, start_http_server

METRICS_PORT = 9100


def ingester_metrics() -> SimpleNamespace:
    feed_fetches = Counter("transit_feed_fetches_total", "Attempts to download the live feed", ["result"])
    # A labeled series doesn't exist until first used. Create both now, so "errors" shows
    # as 0 instead of "no data" (and alerts like "errors > 5" have something to compare).
    for result in ("ok", "error"):
        feed_fetches.labels(result=result)
    return SimpleNamespace(
        feed_fetches=feed_fetches,
        feed_timestamp=Gauge(
            "transit_feed_timestamp_seconds", "When Metro generated the last feed we downloaded (Unix time)"),
        reports_published=Counter(
            "transit_reports_published_total", "Vehicle reports handed to Redpanda"),
        publish_failures=Counter(
            "transit_publish_failures_total", "Vehicle reports Redpanda never confirmed"),
    )


def processor_metrics() -> SimpleNamespace:
    return SimpleNamespace(
        reports_processed=Counter(
            "transit_reports_processed_total", "Vehicle reports read from Redpanda"),
        reports_in_service=Counter(
            "transit_reports_in_service_total", "Processed reports from buses on a passenger trip"),
        reports_matched=Counter(
            "transit_reports_matched_total", "In-service reports that lined up with the schedule"),
        departures_saved=Counter(
            "transit_departures_saved_total", "New stop departures written to the database"),
        last_report_timestamp=Gauge(
            "transit_processor_last_report_timestamp_seconds",
            "Bus report time of the newest message processed (Unix time)"),
        messages_behind=Gauge(
            "transit_processor_messages_behind", "Messages waiting in Redpanda that we haven't read yet"),
        db_write_seconds=Histogram(
            "transit_db_write_seconds", "Time to save one batch of departures",
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5]),
    )


def serve_metrics() -> None:
    start_http_server(METRICS_PORT)  # runs in a background thread; doesn't block
