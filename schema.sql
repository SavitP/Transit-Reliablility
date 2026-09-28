-- Database design for the transit tracker.
-- Safe to run repeatedly: everything uses IF NOT EXISTS / if_not_exists.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Reference data: names for routes and stops, loaded from the static GTFS.
-- Small tables that rarely change. Kept separate so the big table below
-- doesn't repeat "Martin L King Jr Way S & S Raymond St" millions of times.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS routes (
    route_id    TEXT PRIMARY KEY,   -- Metro's code, e.g. '100001'
    short_name  TEXT NOT NULL,      -- what riders call it, e.g. '1'
    description TEXT                -- e.g. 'Kinnear - Downtown Seattle'
);

CREATE TABLE IF NOT EXISTS stops (
    stop_id TEXT PRIMARY KEY,       -- e.g. '2110'
    name    TEXT NOT NULL,          -- e.g. 'Olympic Way W & 9th Ave W'
    lat     DOUBLE PRECISION NOT NULL,
    lon     DOUBLE PRECISION NOT NULL
);

-- ---------------------------------------------------------------------------
-- The main table: one row each time a bus leaves a stop.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stop_departures (
    scheduled_departure  TIMESTAMPTZ NOT NULL,  -- when the timetable said it would leave (UTC)
    trip_id              TEXT        NOT NULL,  -- which scheduled trip
    stop_sequence        SMALLINT    NOT NULL,  -- 1st, 2nd, 3rd... stop on that trip
    route_id             TEXT        NOT NULL,
    stop_id              TEXT        NOT NULL,
    vehicle_id           TEXT        NOT NULL,  -- which physical bus
    departed_at          TIMESTAMPTZ NOT NULL,  -- our estimate of when it actually left (UTC)
    observation_gap_s    SMALLINT    NOT NULL,  -- seconds between the two reports we estimated from
    delay_seconds        INTEGER GENERATED ALWAYS AS
                           (EXTRACT(EPOCH FROM departed_at - scheduled_departure)::INTEGER) STORED,

    -- A trip leaves each stop once per day, so these three together identify a row.
    -- Recording the same departure twice is rejected instead of double-counted.
    PRIMARY KEY (trip_id, stop_sequence, scheduled_departure)
);

-- Turn it into a hypertable: TimescaleDB splits it into one-week "chunks" by scheduled time.
SELECT create_hypertable('stop_departures', by_range('scheduled_departure', INTERVAL '7 days'),
                         if_not_exists => TRUE);

-- Indexes for the questions the website will ask (Phase 6): "how is route X doing?",
-- "how is stop Y doing?". Like the index at the back of a book.
CREATE INDEX IF NOT EXISTS stop_departures_route_idx ON stop_departures (route_id, scheduled_departure DESC);
CREATE INDEX IF NOT EXISTS stop_departures_stop_idx  ON stop_departures (stop_id,  scheduled_departure DESC);

-- Compress weeks we're done writing to. Grouping by route packs similar rows together,
-- which compresses better and keeps per-route queries fast.
ALTER TABLE stop_departures SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'route_id',
    -- The primary key's other columns go here too, so duplicate checks stay fast on compressed data.
    timescaledb.compress_orderby   = 'scheduled_departure DESC, trip_id, stop_sequence'
);
SELECT add_compression_policy('stop_departures', INTERVAL '14 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- A continuous aggregate: an hourly summary per route that TimescaleDB keeps up to date.
-- "Worst routes this week" reads ~140 routes x 168 hours = ~24k summary rows
-- instead of ~2.5 million individual departures.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS route_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', scheduled_departure)                  AS hour,
       route_id,
       count(*)                                                     AS departures,
       count(*) FILTER (WHERE delay_seconds BETWEEN -60 AND 300)   AS on_time,
       count(*) FILTER (WHERE delay_seconds > 300)                 AS late,
       sum(delay_seconds)                                           AS total_delay_s
FROM stop_departures
GROUP BY 1, 2
WITH NO DATA;

-- Every 10 minutes, recompute any hours whose departures changed, up to 30 minutes ago.
-- (start_offset NULL = look all the way back, so late-arriving data is never missed.)
SELECT add_continuous_aggregate_policy('route_hourly',
    start_offset => NULL,
    end_offset => INTERVAL '30 minutes',
    schedule_interval => INTERVAL '10 minutes',
    if_not_exists => TRUE);
