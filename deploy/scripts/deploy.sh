#!/usr/bin/env bash
set -euo pipefail

cd /opt/firstlight
test -f .env || { echo "Missing /opt/firstlight/.env" >&2; exit 1; }
deployment_domain="$(sed -n 's/^DOMAIN=//p' .env | tail -n 1)"
test -n "$deployment_domain" || { echo "Missing DOMAIN in .env" >&2; exit 1; }
docker compose -f compose.prod.yaml pull
docker compose -f compose.prod.yaml up -d --remove-orphans
docker compose -f compose.prod.yaml ps
curl --fail --retry 12 --retry-delay 5 "https://${deployment_domain}/api/health"
