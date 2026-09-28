# Learning Log

## Phase 1: Just get the data

**What we built:** `fetch_vehicles.py`, a single script that downloads King County
Metro's live vehicle positions, decodes them, and prints a table.

**How data flows:**

```
King County Metro servers
   │  (every few seconds they rewrite vehiclepositions.pb on Amazon S3)
   ▼
download_feed()   → raw bytes (unreadable binary, ~35 KB)
   ▼
decode_feed()     → FeedMessage object (protobuf decoded using the GTFS-RT "schema")
   ▼
extract_vehicles() → list of plain dicts: vehicle, route, trip, lat/lon, stop, timestamp
   ▼
main()            → printed table
```

**Key ideas:**
- **GTFS** (static) is the published *plan*: routes, stops, trips, and scheduled times, as a
  zip of CSV files. It changes every few weeks.
- **GTFS-Realtime** is the *reality*: where vehicles are right now. It changes every few seconds.
- **Protobuf** is a compact binary format. Both sides share a "schema" (a description of the
  fields), so the file doesn't need to repeat field names. It's smaller and faster to parse
  than JSON, which matters when thousands of apps poll the feed every few seconds.
- The feed is a **snapshot**. Each download replaces the previous one and keeps no history.
  If we want history (and we do, to measure lateness), *we* have to store it.
- IDs in the feed (`route_id` "100001") are internal codes. Turning them into human names
  ("Route 1") requires the static GTFS. That's Phase 2.
- A vehicle with no `trip` isn't in passenger service, so we ignore it for reliability.
- Timestamps are **Unix time**: seconds since Jan 1, 1970, UTC. One number, no time zones.

**Secrets:** this feed needs no API key. `.env` is already in `.gitignore` for when we need one.

## Phase 2: Match to the schedule and calculate delays

**What we built:**
- `schedule.py` downloads Metro's static GTFS zip (once a day) and loads routes, stops, and
  1.1 million scheduled stop times into memory, organized so "trip X, stop #N" is an instant lookup.
- `track_delays.py` polls the live feed every 30s, matches each bus to its scheduled trip,
  detects when it leaves stops, and appends one row per stop departure to `data/delays.csv`.

**How data flows:**

```
google_transit.zip ──▶ Schedule (in memory): trip_id → {stop #: (stop_id, scheduled time)}
                                  │
live feed every 30s ─▶ extract_vehicles ─▶ matches_schedule? ──no──▶ skipped (counted)
                                                 │ yes
                           compare with last report for this trip (last_seen)
                                                 │ stop # went up?
                                                 ▼
                     find_departures: estimated time − scheduled time = delay
                                                 ▼
                                          data/delays.csv
```

**Key ideas:**
- **Matching is by trip_id, not by location.** The live feed says which scheduled trip each bus
  is driving, so we look it up directly. No map math is needed. It works about 97% of the time.
- **We measure delay at the moment a bus *leaves* a stop.** We never see that moment directly.
  We see "heading to stop #5" in one report and "heading to stop #7" 30s later, so we estimate
  the bus left #5 and #6 halfway between. That's accurate to about ±15 seconds.
- **We need two reports to learn anything.** A single snapshot can't tell you when a stop was
  passed. So the tracker keeps memory (`last_seen`) between polls. That's the first time the
  system has **state**.
- **Reject rather than guess.** Inconsistent reports, buses not yet on their trip (stop #0),
  and gaps over 2 minutes are all skipped. Missing data is better than wrong data.
- **GTFS time is weird.** "25:10:00" means 1:10am the next morning, counted from the service
  day's start. The day starts at "noon minus 12 hours", which isn't midnight on daylight-saving
  days. Always do time math in UTC, and convert to local time only for display.
- **Check against an independent source.** Metro's own trip-updates feed agreed with our
  delays within 1 minute for 84% of trips.

**Limitations (on purpose, for now):** the CSV file grows forever, is slow to search, and two
programs can't safely write to it at once. Restarting the tracker loses `last_seen`, so the first
30 seconds after a restart record nothing. Phase 3 (a real database) fixes the file problems.

## Phase 3: A real database

**What we built:**
- A Postgres + TimescaleDB database (first started with a `start_db.sh` script, replaced by Docker Compose in Phase 4).
- `schema.sql`: the table design (`routes`, `stops`, `stop_departures`).
- `db.py`: connecting to the database, creating tables, and saving rows.
- `track_delays.py` now writes to the database instead of `data/delays.csv`.
- `queries.sql`: example questions you can ask the data.

**How data flows:**

```
google_transit.zip ─▶ Schedule (memory) ─┬─▶ routes, stops tables (names, once at startup)
                                         │
live feed every 30s ─▶ match ─▶ find_departures ─▶ INSERT ... ON CONFLICT DO NOTHING
                                                          ▼
                                    stop_departures (hypertable, split into weekly chunks)
                                                          ▼
                                      SQL queries: "which routes are least on time?"
```

**Key ideas:**
- **Database vs. file:** a database can find matching rows without reading everything (indexes),
  lets several programs read and write at once safely, enforces rules (no missing values, no
  duplicates), and answers questions in SQL instead of custom Python.
- **Time-series data** is data where every row is "something measured at a time," and new rows
  keep arriving in time order. You mostly ask about time ranges ("last week", "by hour").
- **TimescaleDB** is Postgres plus time-series features: a *hypertable* automatically splits the
  table into weekly *chunks*, so "last week" only touches one chunk. Old chunks get *compressed*,
  and `time_bucket()` groups rows by any time interval.
- **The primary key is our duplicate guard.** (trip, stop #, scheduled time) can only happen once,
  so saving the same departure twice does nothing (`ON CONFLICT DO NOTHING`).
- **The time column is `scheduled_departure`, not `departed_at`.** It's fixed and known in advance,
  it's part of the natural identity of a row, and it's what riders mean by "the 5:15 bus."
- **Store names once** (`routes`, `stops`) and refer to them by ID. That avoids repeating long
  names millions of times, and a renamed stop only needs one update.
- **Secrets live in `.env`** (ignored by git). `.env.example` (committed) shows which settings
  are needed, with fake values. The code reads secrets from environment variables.
- **Watch for survivorship bias:** departures scheduled in the *future* only appear if the bus
  left early. Recent time buckets therefore look too early until the late buses show up.

## Phase 4: Docker

**What we built:**
- `Dockerfile`: a two-stage recipe that packages the tracker into an image (303 MB, down from
  1.54 GB with a single stage).
- `.dockerignore`: keeps `.env`, `.venv`, `data/`, and `.git` out of the image.
- `docker-compose.yml`: runs the database and the tracker (the "ingester") together with one command.
- `track_delays.py` now exits cleanly when Docker asks it to stop.

**How data flows:**

```
 Your Mac
 ├── .env ──(Compose fills in ${POSTGRES_PASSWORD})──┐
 │                                                   ▼
 │   ┌──────────── Compose network "transit-reliablility_default" ────────────┐
 │   │  ingester container                     db container                   │
 │   │  python track_delays.py ──"db:5432"──▶  Postgres + TimescaleDB         │
 │   │  /app/data ◀─ volume: schedule-cache    /var/lib/postgresql/data       │
 │   └──────────────────────────────────────────────── ▲ ─────────────────────┘
 │                                                     │ volume: transit-db-data
 └── psql / your tools ──"localhost:5433"──────────────┘ (port published to your Mac only)
         │
 Internet: Metro's feed + schedule (the ingester downloads them directly)
```

**Key ideas:**
- **Image vs. container:** an image is a frozen, read-only package (the recipe baked into a
  meal kit). A container is a running copy of an image (the meal being cooked). You can run
  many containers from one image, and deleting a container doesn't touch the image.
- **Dockerfile:** step-by-step instructions to build an image. Each step is a cached *layer*,
  so ordering matters: copy `requirements.txt` and install packages *before* copying code,
  and code changes rebuild in seconds.
- **Multi-stage build:** build in a big image that has compilers, then copy only the finished
  result into a slim image. The build tools, caches, and leftovers never ship.
- **Compose:** describes several containers, their settings, and how they connect, in one file.
  `docker compose up -d` starts everything, and `docker compose down` removes the containers.
- **Volumes:** a container's own files disappear when the container is deleted. A volume is
  storage kept *outside* the container and plugged in. That's why the database survives `down`/`up`.
- **Networking:** Compose puts the services on a private network where each is reachable by
  its service name (`db`). `localhost` inside a container means *that container itself*.
  `ports:` opens a door from your Mac into a container (`localhost:5433` → `db:5432`).
- **Secrets:** `.env` stays on your Mac. Compose reads it and passes values in as environment
  variables when a container starts. They're never baked into the image.
- **Restart policy:** `restart: unless-stopped` brings a crashed container back automatically.
