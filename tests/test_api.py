"""Integration tests for the API: real FastAPI app, real test database, fake HTTP requests."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from db import save_departures
from tests.conftest import refresh_route_hourly


@pytest.fixture
def client(db, db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)   # make the API use the test database
    db.execute("INSERT INTO routes VALUES ('R1', '7', 'Rainier Beach - Downtown'), "
               "('R2', '44', 'Ballard - U District')")
    db.execute("INSERT INTO stops VALUES ('S1', 'Pike St & 3rd Ave', 47.61, -122.34)")
    from api import app
    with TestClient(app) as c:   # "with" runs the app's startup (opens the connection pool)
        yield c


def add_departures(db, route_id: str, delays: list[int], hours_ago: float = 2) -> None:
    """Save one departure per delay (in seconds), scheduled `hours_ago` hours in the past."""
    base = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    save_departures(db, [
        {"scheduled_departure": base + timedelta(minutes=i), "trip_id": f"{route_id}-{i}",
         "stop_sequence": 1, "route_id": route_id, "stop_id": "S1", "vehicle_id": "V1",
         "departed_at": base + timedelta(minutes=i, seconds=d), "observation_gap_s": 30}
        for i, d in enumerate(delays)
    ])


def test_route_stats(client, db):
    # 7 on time, 2 late (> 5 min), 1 early (> 1 min early)
    add_departures(db, "R1", [0, 30, 60, 120, 200, 250, 299, 400, 900, -120])
    data = client.get("/api/routes/R1?days=7").json()
    assert data["short_name"] == "7"
    assert data["departures"] == 10
    assert (data["pct_on_time"], data["pct_late"], data["pct_early"]) == (70.0, 20.0, 10.0)
    assert len(data["by_hour"]) == 24 and len(data["by_day"]) == 7


def test_very_recent_departures_are_left_out(client, db):
    # Scheduled 10 minutes ago: late buses for that time may not have left yet (survivorship bias).
    add_departures(db, "R1", [0, 0, 0], hours_ago=10 / 60)
    assert client.get("/api/routes/R1").json()["departures"] == 0


def test_search_finds_routes_and_stops(client):
    assert client.get("/api/search?q=7").json()["routes"][0]["short_name"] == "7"
    assert client.get("/api/search?q=pike").json()["stops"][0]["stop_id"] == "S1"


def test_unknown_route_is_404(client):
    assert client.get("/api/routes/NOPE").status_code == 404


def test_invalid_input_is_rejected(client):
    assert client.get("/api/routes/R1?days=0").status_code == 422
    assert client.get("/api/routes/R1?days=abc").status_code == 422
    assert client.get("/api/search?q=").status_code == 422


def test_worst_routes_ranks_least_on_time_first(client, db):
    # The hourly summary only includes *finished* hours, so put these safely in the past.
    # (That also means the live "worst routes" page never includes the current hour.)
    add_departures(db, "R1", [0] * 100, hours_ago=4)               # 100% on time
    add_departures(db, "R2", [0] * 40 + [600] * 60, hours_ago=4)   # 40% on time
    refresh_route_hourly(db)
    ranking = client.get("/api/worst-routes").json()
    assert [r["short_name"] for r in ranking] == ["44", "7"]
    assert ranking[0]["pct_on_time"] == 40.0


def test_website_is_served(client):
    response = client.get("/")
    assert response.status_code == 200 and "Metro Reliability" in response.text


def test_health_ok_when_departures_are_recent(client, db):
    add_departures(db, "R1", [0], hours_ago=0.1)
    response = client.get("/api/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"


def test_health_fails_when_pipeline_is_stale(client, db):
    assert client.get("/api/health").status_code == 503              # no data at all
    add_departures(db, "R1", [0], hours_ago=3)
    assert client.get("/api/health").json()["status"] == "stale"     # data, but 3 hours old


# ---------- commute alert subscriptions ----------

NEW_SUB = {"route_id": "R1", "stop_id": "S1", "days": [1, 2, 3, 4, 5],
           "window_start": "07:00", "window_end": "09:00", "threshold_minutes": 10}


@pytest.fixture
def served(db):
    db.execute("INSERT INTO route_stops VALUES ('R1', 'S1')")   # Route "7" stops at Pike St


def test_create_view_and_delete_subscription(client, served):
    response = client.post("/api/subscriptions", json=NEW_SUB)
    assert response.status_code == 201
    sub = response.json()
    assert sub["route_name"] == "7" and sub["stop_name"] == "Pike St & 3rd Ave"
    assert sub["topic"].startswith("transit-") and len(sub["topic"]) > 25   # long and random
    assert sub["ntfy_url"] == f"https://ntfy.sh/{sub['topic']}"

    assert client.get(f"/api/subscriptions/{sub['id']}").json()["days"] == [1, 2, 3, 4, 5]
    assert client.delete(f"/api/subscriptions/{sub['id']}").status_code == 204
    assert client.get(f"/api/subscriptions/{sub['id']}").status_code == 404


def test_every_subscription_gets_its_own_topic(client, served):
    a = client.post("/api/subscriptions", json=NEW_SUB).json()
    b = client.post("/api/subscriptions", json=NEW_SUB).json()
    assert a["topic"] != b["topic"] and a["id"] != b["id"]


@pytest.mark.parametrize("change", [
    {"stop_id": "NOWHERE"},                                   # route doesn't stop there
    {"route_id": "R2"},                                       # route 44 doesn't serve S1
    {"days": []}, {"days": [0]}, {"days": [8]}, {"days": [1, 1]},
    {"window_start": "09:00", "window_end": "07:00"},
    {"threshold_minutes": 1}, {"threshold_minutes": 500},
])
def test_invalid_subscriptions_are_rejected(client, served, change):
    assert client.post("/api/subscriptions", json={**NEW_SUB, **change}).status_code == 422


def test_bad_subscription_id_is_rejected(client):
    assert client.get("/api/subscriptions/not-a-uuid").status_code == 422
    assert client.get("/api/subscriptions/00000000-0000-0000-0000-000000000000").status_code == 404


def test_test_notification_is_queued_once_per_minute(client, db, served):
    sub = client.post("/api/subscriptions", json=NEW_SUB).json()
    assert client.post(f"/api/subscriptions/{sub['id']}/test").status_code == 202
    assert client.post(f"/api/subscriptions/{sub['id']}/test").status_code == 429
    title, status = db.execute("SELECT title, status FROM alerts").fetchone()
    assert status == "pending" and title.startswith("Test alert")


def test_route_and_stop_lookups_for_the_form(client, served):
    assert client.get("/api/routes/R1/stops").json() == [{"stop_id": "S1", "name": "Pike St & 3rd Ave"}]
    assert [r["short_name"] for r in client.get("/api/stops/S1/routes").json()] == ["7"]
