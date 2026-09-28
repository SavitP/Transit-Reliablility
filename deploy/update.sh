#!/usr/bin/env bash
# Deploy the newest version. Run on the server, in the project folder:  ./deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

git pull --ff-only                 # newest config files (compose, Caddyfile, monitoring)
$COMPOSE pull                      # newest images, including the one CI built and tested
$COMPOSE up -d --remove-orphans    # restart only what changed
docker image prune -f              # delete old image versions to save disk
$COMPOSE ps
