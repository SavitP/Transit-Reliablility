"""The API: answers questions about reliability as JSON, and serves the website.

Run locally:  uvicorn api:app --reload
Then open http://localhost:8000 (website) or http://localhost:8000/docs (API explorer).
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

# Metro's definition of "on time": no more than 1 minute early, no more than 5 minutes late.
ON_TIME = "delay_seconds BETWEEN -60 AND 300"
# Leave out departures scheduled in the last 30 minutes: late buses for those times may not
# have left yet, which would make recent data look better than it is (survivorship bias).
SETTLED = "scheduled_departure < now() - INTERVAL '30 minutes'"
LOCAL_TIME = "(scheduled_departure AT TIME ZONE 'America/Los_Angeles')"
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

pool: ConnectionPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once when the server starts (before `yield`) and once when it stops (after)."""
    global pool
    pool = ConnectionPool(
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=5,  # at most 5 queries at the same time; more requests wait their turn
        kwargs={"autocommit": True, "row_factory": dict_row},  # rows come back as dicts
        open=True,
    )
    yield
    pool.close()


app = FastAPI(title="Transit Reliability API", lifespan=lifespan)


def query(sql: str, params: dict | None = None) -> list[dict]:
    """Borrow a connection from the pool, run one query, return the rows, give it back."""
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def reliability(filter_sql: str, params: dict) -> dict:
    """On-time stats overall, by hour of day, by day of week, and by day x hour.

    `filter_sql` picks which departures to include, e.g. "route_id = %(id)s".
    It's always one of our own fixed strings, never text typed by a user.
    """
    where = f"{filter_sql} AND scheduled_departure > now() - make_interval(days => %(days)s) AND {SETTLED}"

    # One query groups departures into (weekday, hour) cells; we add those up in Python
    # to get the per-hour and per-day numbers too.
    cells = query(f"""
        SELECT extract(isodow FROM {LOCAL_TIME})::int AS dow,    -- 1 = Monday ... 7 = Sunday
               extract(hour   FROM {LOCAL_TIME})::int AS hour,   -- 0 ... 23, Seattle time
               count(*)                                 AS n,
               count(*) FILTER (WHERE {ON_TIME})        AS on_time,
               count(*) FILTER (WHERE delay_seconds < -60) AS early,
               count(*) FILTER (WHERE delay_seconds > 300) AS late
        FROM stop_departures
        WHERE {where}
        GROUP BY 1, 2
    """, params)

    typical = query(f"""
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY delay_seconds) AS median_delay,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY delay_seconds) AS p90_delay
        FROM stop_departures WHERE {where}
    """, params)[0]

    def rollup(key):
        groups: dict[int, list[int]] = {}
        for c in cells:
            g = groups.setdefault(c[key], [0, 0])
            g[0] += c["n"]
            g[1] += c["on_time"]
        return groups

    by_hour = rollup("hour")
    by_day = rollup("dow")
    total = sum(c["n"] for c in cells)
    return {
        "departures": total,
        "pct_on_time": pct(sum(c["on_time"] for c in cells), total),
        "pct_early": pct(sum(c["early"] for c in cells), total),
        "pct_late": pct(sum(c["late"] for c in cells), total),
        "median_delay_min": round(typical["median_delay"] / 60, 1) if total else None,
        "p90_delay_min": round(typical["p90_delay"] / 60, 1) if total else None,
        "by_hour": [{"hour": h, "departures": by_hour.get(h, [0, 0])[0],
                     "pct_on_time": pct(by_hour.get(h, [0, 0])[1], by_hour.get(h, [0, 0])[0])}
                    for h in range(24)],
        "by_day": [{"day": DAY_NAMES[d - 1], "departures": by_day.get(d, [0, 0])[0],
                    "pct_on_time": pct(by_day.get(d, [0, 0])[1], by_day.get(d, [0, 0])[0])}
                   for d in range(1, 8)],
        "grid": [{"day": DAY_NAMES[c["dow"] - 1], "hour": c["hour"], "departures": c["n"],
                  "pct_on_time": pct(c["on_time"], c["n"])} for c in cells],
    }


@app.get("/api/search")
def search(q: str = Query(min_length=1, max_length=50)):
    """Find routes and stops matching what the user typed."""
    params = {"exact": q, "prefix": f"{q}%", "anywhere": f"%{q}%"}
    routes = query("""
        SELECT route_id, short_name, description FROM routes
        WHERE short_name ILIKE %(prefix)s OR description ILIKE %(anywhere)s
        ORDER BY short_name ILIKE %(exact)s DESC, length(short_name), short_name
        LIMIT 10
    """, params)
    stops = query("""
        SELECT stop_id, name FROM stops
        WHERE name ILIKE %(anywhere)s OR stop_id = %(exact)s
        ORDER BY stop_id = %(exact)s DESC, name
        LIMIT 10
    """, params)
    return {"routes": routes, "stops": stops}


@app.get("/api/routes/{route_id}")
def route_reliability(route_id: str, days: int = Query(7, ge=1, le=90)):
    route = query("SELECT route_id, short_name, description FROM routes WHERE route_id = %(id)s",
                  {"id": route_id})
    if not route:
        raise HTTPException(status_code=404, detail="No such route")
    stats = reliability("route_id = %(id)s", {"id": route_id, "days": days})
    return {**route[0], "days": days, **stats}


@app.get("/api/stops/{stop_id}")
def stop_reliability(stop_id: str, days: int = Query(7, ge=1, le=90)):
    stop = query("SELECT stop_id, name, lat, lon FROM stops WHERE stop_id = %(id)s", {"id": stop_id})
    if not stop:
        raise HTTPException(status_code=404, detail="No such stop")
    params = {"id": stop_id, "days": days}
    stats = reliability("stop_id = %(id)s", params)
    # Which routes serve this stop, and how each one does here.
    stats["routes"] = query(f"""
        SELECT r.route_id, r.short_name, count(*) AS departures,
               round(100.0 * count(*) FILTER (WHERE {ON_TIME}) / count(*), 1) AS pct_on_time
        FROM stop_departures d JOIN routes r USING (route_id)
        WHERE d.stop_id = %(id)s
          AND scheduled_departure > now() - make_interval(days => %(days)s) AND {SETTLED}
        GROUP BY r.route_id, r.short_name
        ORDER BY pct_on_time
    """, params)
    return {**stop[0], "days": days, **stats}


@app.get("/api/worst-routes")
def worst_routes(days: int = Query(7, ge=1, le=90), limit: int = Query(15, ge=1, le=100)):
    """Routes ranked from least to most on time. Routes with little data are left out.

    Reads the hourly summary (route_hourly) instead of every departure, so it stays fast
    however much data we collect.
    """
    return query("""
        SELECT r.route_id, r.short_name, r.description,
               sum(h.departures)                                          AS departures,
               round(100.0 * sum(h.on_time) / sum(h.departures), 1)      AS pct_on_time,
               round(100.0 * sum(h.late) / sum(h.departures), 1)         AS pct_late,
               round(sum(h.total_delay_s) / sum(h.departures) / 60.0, 1) AS avg_delay_min
        FROM route_hourly h JOIN routes r USING (route_id)
        WHERE h.hour > now() - make_interval(days => %(days)s)
        GROUP BY r.route_id, r.short_name, r.description
        HAVING sum(h.departures) >= 100
        ORDER BY pct_on_time
        LIMIT %(limit)s
    """, {"days": days, "limit": limit})


# Everything that isn't /api/... is a file from the static/ folder (the website).
# This goes last so it doesn't swallow the API routes above.
app.mount("/", StaticFiles(directory="static", html=True), name="website")
