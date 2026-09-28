"""Decide when a rider should be told their bus is running late.

The processor feeds every new stop departure through AlertChecker.check(). For each
subscription on that route, we ask:

  1. Is this bus still *heading to* the rider's stop? (It hasn't passed it yet.)
  2. Is it scheduled at the rider's stop inside their commute window (day + time)?
  3. Is it late by at least their threshold, confirmed by two separate observations?

If all three are yes, we return an alert. Saving (and not repeating) alerts is db.py's job,
sending them is notifier.py's. This file only decides.
"""

from datetime import datetime, timedelta

from schedule import SEATTLE, Schedule

FORGET_TRIPS_AFTER = timedelta(hours=4)  # trips don't run longer than this; free the memory


class AlertChecker:
    def __init__(self, schedule: Schedule):
        self.schedule = schedule
        self.subscriptions_by_route: dict[str, list[dict]] = {}
        # trip_id -> {"observed_at": when we measured, "delay": seconds, "previous_delay": seconds}
        self.trip_delays: dict[str, dict] = {}

    def set_subscriptions(self, subscriptions: list[dict]) -> None:
        by_route: dict[str, list[dict]] = {}
        for sub in subscriptions:
            by_route.setdefault(sub["route_id"], []).append(sub)
        self.subscriptions_by_route = by_route

    def check(self, departure: dict, service_date: str) -> list[dict]:
        """Look at one new stop departure; return any alerts it should trigger."""
        confirmed_delay = self._record_and_confirm(departure)
        subs = self.subscriptions_by_route.get(departure["route_id"])
        if confirmed_delay is None or not subs:
            return []

        alerts = []
        for sub in subs:
            if confirmed_delay < sub["threshold_minutes"] * 60:
                continue
            upcoming = self._scheduled_at_stop(departure, sub["stop_id"], service_date)
            if upcoming is None:
                continue  # this trip already passed the rider's stop, or never goes there
            if not in_window(upcoming, sub):
                continue
            alerts.append(self._make_alert(sub, departure, service_date, confirmed_delay, upcoming))
        return alerts

    def _record_and_confirm(self, departure: dict) -> int | None:
        """Remember this trip's delay. Return a delay only if two separate observations agree.

        "Separate" matters: when a bus skips past several stops between two reports, we record
        several departures from the *same* pair of reports. Those are one measurement, not
        several, so they don't confirm each other. We take the smaller of the two delays:
        "at least this late, measured twice".
        """
        trip, now = departure["trip_id"], departure["departed_at"]
        delay = int((now - departure["scheduled_departure"]).total_seconds())
        state = self.trip_delays.get(trip)
        if state is None:
            self.trip_delays[trip] = {"observed_at": now, "delay": delay, "previous_delay": None}
            self._forget_old_trips(now)
            return None
        if now != state["observed_at"]:
            state["previous_delay"] = state["delay"]
            state["observed_at"] = now
        state["delay"] = delay
        if state["previous_delay"] is None:
            return None
        return min(state["delay"], state["previous_delay"])

    def _scheduled_at_stop(self, departure: dict, stop_id: str, service_date: str) -> datetime | None:
        """When this trip is scheduled at `stop_id`, if that stop is still ahead of the bus."""
        stops = self.schedule.stop_times.get(departure["trip_id"], {})
        ahead = sorted(seq for seq, (sid, _) in stops.items()
                       if sid == stop_id and seq > departure["stop_sequence"])
        if not ahead:
            return None
        return self.schedule.scheduled_departure(departure["trip_id"], ahead[0], service_date)

    def _make_alert(self, sub, departure, service_date, delay, scheduled_at_stop) -> dict:
        route = self.schedule.routes.get(departure["route_id"], {}).get("short_name", "?")
        headsign = self.schedule.trips.get(departure["trip_id"], {}).get("headsign", "")
        stop = self.schedule.stops.get(sub["stop_id"], {}).get("name", sub["stop_id"])
        expected = scheduled_at_stop + timedelta(seconds=delay)
        minutes = round(delay / 60)
        to = f" to {headsign}" if headsign else ""
        return {
            "subscription_id": sub["id"],
            "trip_id": departure["trip_id"],
            "service_date": f"{service_date[:4]}-{service_date[4:6]}-{service_date[6:]}",
            "delay_seconds": delay,
            "expected_at": expected,
            "title": f"Route {route} is running {minutes} min late",
            "message": (f"The {clock(scheduled_at_stop)} Route {route}{to} is expected at "
                        f"{stop} around {clock(expected)}."),
        }

    def _forget_old_trips(self, now: datetime) -> None:
        if len(self.trip_delays) < 20_000:
            return
        cutoff = now - FORGET_TRIPS_AFTER
        self.trip_delays = {t: s for t, s in self.trip_delays.items() if s["observed_at"] > cutoff}


def in_window(when: datetime, sub: dict) -> bool:
    """Is `when` on one of the subscription's days and inside its time window (Seattle time)?"""
    local = when.astimezone(SEATTLE)
    return (local.isoweekday() in sub["days"]
            and sub["window_start"] <= local.time().replace(tzinfo=None) <= sub["window_end"])


def clock(when: datetime) -> str:
    """UTC datetime -> '8:05am' in Seattle time."""
    local = when.astimezone(SEATTLE)
    return local.strftime("%-I:%M%p").lower()
