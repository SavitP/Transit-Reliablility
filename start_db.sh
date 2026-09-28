#!/bin/sh
# Start the TimescaleDB database in Docker (Phase 4 explains every part of this).
# Reads the password from .env so it never appears in this file.
set -e
. ./.env

if docker ps -a --format '{{.Names}}' | grep -qx transit-db; then
    docker start transit-db          # already created before: just start it again
else
    docker run -d \
        --name transit-db \
        -e POSTGRES_USER=transit \
        -e POSTGRES_DB=transit \
        -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
        -p 127.0.0.1:5433:5432 \
        -v transit-db-data:/var/lib/postgresql/data \
        timescale/timescaledb:2.30.1-pg17
fi
