"""Tests for decoding the realtime feed, using saved real snapshots and hand-made messages."""

from google.transit import gtfs_realtime_pb2

from fetch_vehicles import count_by_route, decode_feed, describe_age, extract_vehicles
from tests.conftest import FIXTURES


def test_decodes_real_snapshot(snapshots):
    vehicles = snapshots[0]
    assert len(vehicles) > 50
    for v in vehicles:
        # Every bus should be somewhere around King County.
        assert 46.9 < v["lat"] < 48.1 and -122.7 < v["lon"] < -121.3, v
        assert v["timestamp"] > 1_700_000_000


def test_snapshot_header_is_readable():
    feed = decode_feed((FIXTURES / "vehiclepositions_0.pb").read_bytes())
    assert feed.header.gtfs_realtime_version == "2.0"


def test_vehicle_without_trip_gets_none_not_empty_string():
    # A bus heading to the garage has no trip. Protobuf would give "" by default;
    # we want None so it can't be mistaken for a real route.
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    entity = feed.entity.add(id="1")
    entity.vehicle.vehicle.id = "9999"
    entity.vehicle.position.latitude = 47.6
    entity.vehicle.position.longitude = -122.3
    feed.entity.add(id="2").alert.header_text.translation.add(text="not a vehicle")

    vehicles = extract_vehicles(feed)
    assert len(vehicles) == 1                       # the alert entity is skipped
    assert vehicles[0]["route_id"] is None
    assert vehicles[0]["trip_id"] is None
    assert vehicles[0]["stop_id"] is None


def test_describe_age():
    assert describe_age(1000, 1000) == "0s ago"
    assert describe_age(958, 1000) == "42s ago"
    assert describe_age(815, 1000) == "3m 5s ago"
    assert describe_age(1010, 1000) == "just now"


def test_count_by_route_skips_out_of_service():
    vehicles = [{"route_id": "A"}, {"route_id": "B"}, {"route_id": "A"}, {"route_id": None}]
    assert count_by_route(vehicles) == {"A": 2, "B": 1}
