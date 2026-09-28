"""Phase 1: download King County Metro's live vehicle positions and print them.

Run:  python fetch_vehicles.py
"""

from datetime import datetime, timezone

import requests
from google.transit import gtfs_realtime_pb2

# King County Metro publishes this file publicly. No API key needed.
# It is regenerated every few seconds with every bus's latest position.
VEHICLE_POSITIONS_URL = "https://s3.amazonaws.com/kcm-alerts-realtime-prod/vehiclepositions.pb"


def download_feed(url: str) -> bytes:
    """Download the raw protobuf bytes from the agency."""
    response = requests.get(url, timeout=20)
    response.raise_for_status()  # turn a 404/500 into a loud error instead of garbage data
    return response.content


def decode_feed(raw: bytes) -> gtfs_realtime_pb2.FeedMessage:
    """Turn raw protobuf bytes into a Python object we can read."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(raw)
    return feed


def extract_vehicles(feed: gtfs_realtime_pb2.FeedMessage) -> list[dict]:
    """Pull out the fields we care about into plain Python dicts."""
    vehicles = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue  # this entity is something else (e.g. an alert), skip it
        v = entity.vehicle
        vehicles.append(
            {
                "vehicle_id": v.vehicle.id,
                # A bus that isn't in service (driving back to the garage) has no trip.
                "route_id": v.trip.route_id if v.HasField("trip") else None,
                "trip_id": v.trip.trip_id if v.HasField("trip") else None,
                "service_date": v.trip.start_date or None,  # "20260927": which day's schedule
                "lat": v.position.latitude,
                "lon": v.position.longitude,
                "stop_id": v.stop_id or None,
                "stop_sequence": v.current_stop_sequence,  # 1st, 2nd, 3rd... stop of this trip
                "timestamp": v.timestamp,  # seconds since 1970-01-01 UTC
            }
        )
    return vehicles


def describe_age(vehicle_timestamp: int, now: int) -> str:
    """Say how old a position report is, in words.

    Both arguments are Unix timestamps (whole seconds).
      - under 60 seconds old  -> "42s ago"
      - 60 seconds or older   -> "3m 5s ago"   (minutes, then leftover seconds)
      - timestamp in the future (clock mismatch) -> "just now"
    """
    seconds = now - vehicle_timestamp
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes, leftover = divmod(seconds, 60)
    return f"{minutes}m {leftover}s ago"


def count_by_route(vehicles: list[dict]) -> dict[str, int]:
    """Count how many vehicles are on each route.

    Takes the list from extract_vehicles() and returns e.g. {"100001": 4, "100039": 2}.
    Skip vehicles whose route_id is None (they aren't carrying passengers).
    """
    counts: dict[str, int] = {}
    for v in vehicles:
        if v["route_id"] is None:
            continue
        counts[v["route_id"]] = counts.get(v["route_id"], 0) + 1
    return counts


def main() -> None:
    raw = download_feed(VEHICLE_POSITIONS_URL)
    feed = decode_feed(raw)
    vehicles = extract_vehicles(feed)

    feed_time = datetime.fromtimestamp(feed.header.timestamp, tz=timezone.utc)
    print(f"Downloaded {len(raw):,} bytes; feed generated at {feed_time:%Y-%m-%d %H:%M:%S} UTC")
    print(f"{len(vehicles)} vehicles reporting\n")

    print(f"{'VEHICLE':<8} {'ROUTE':<8} {'TRIP':<11} {'LAT':>10} {'LON':>12}  {'STOP':<7} AGE")
    for v in vehicles[:25]:  # the first 25 is enough to eyeball; there are hundreds
        age = describe_age(v["timestamp"], feed.header.timestamp)
        print(
            f"{v['vehicle_id']:<8} {v['route_id'] or '-':<8} {v['trip_id'] or '-':<11} "
            f"{v['lat']:>10.5f} {v['lon']:>12.5f}  {v['stop_id'] or '-':<7} {age}"
        )
    print(f"... and {max(0, len(vehicles) - 25)} more\n")

    counts = count_by_route(vehicles)
    busiest = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]
    print("Busiest routes right now:", ", ".join(f"{r} ({n})" for r, n in busiest))


if __name__ == "__main__":
    main()
