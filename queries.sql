-- Handy queries to explore the data.  Run all:  psql "$DATABASE_URL" -f queries.sql

-- How much have we collected?
SELECT count(*) AS departures, min(scheduled_departure) AS first, max(scheduled_departure) AS last
FROM stop_departures;

-- Least reliable routes in the last day ("on time" = 1 min early to 5 min late, Metro's definition)
SELECT r.short_name AS route,
       count(*) AS departures,
       round(100.0 * count(*) FILTER (WHERE delay_seconds BETWEEN -60 AND 300) / count(*)) AS pct_on_time,
       round(avg(delay_seconds) / 60.0, 1) AS avg_min_late
FROM stop_departures d
JOIN routes r USING (route_id)
WHERE scheduled_departure > now() - INTERVAL '1 day'
GROUP BY r.short_name
HAVING count(*) >= 10
ORDER BY pct_on_time
LIMIT 10;

-- On-time percentage by hour of day (Seattle time), across all routes
SELECT extract(hour FROM scheduled_departure AT TIME ZONE 'America/Los_Angeles') AS hour,
       count(*) AS departures,
       round(100.0 * count(*) FILTER (WHERE delay_seconds BETWEEN -60 AND 300) / count(*)) AS pct_on_time
FROM stop_departures
GROUP BY 1
ORDER BY 1;
