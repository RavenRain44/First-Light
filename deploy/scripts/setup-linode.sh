#!/usr/bin/env bash
# One-time (re-runnable) setup for an Ubuntu/Debian Linode. From the repo root:
#   sudo bash deploy/scripts/setup-linode.sh            # free hostname from the Linode's IP
#   sudo bash deploy/scripts/setup-linode.sh example.org  # your own domain (point its A record here first)
# Installs Docker, writes .env (live weather, Akamai AI, object storage), sets the manager login,
# and starts the app behind Caddy with automatic HTTPS.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
set_env() {  # set_env KEY VALUE: replace or append in .env
  local k="$1" v="$2"
  if grep -q "^${k}=" .env; then sed -i "s|^${k}=.*|${k}=${v//|/\|}|" .env; else printf '%s=%s\n' "$k" "$v" >> .env; fi
}
get_env() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
ask() {  # ask KEY "Prompt" [secret]: prompt only when the value is empty
  local k="$1" cur; cur="$(get_env "$k")"
  if [ -z "$cur" ]; then
    if [ "${3:-}" = secret ]; then read -rsp "$2: " cur; echo; else read -rp "$2: " cur; fi
    set_env "$k" "$cur"
  fi
}

say "Installing Docker"
if ! command -v docker >/dev/null; then
  apt-get update -qq && apt-get install -y -qq ca-certificates curl git
  curl -fsSL https://get.docker.com | sh
fi

# Building the images needs more memory than a 2 GB Linode has free; a swap file avoids failed builds.
if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 3500 ] && ! swapon --show | grep -q /swapfile; then
  say "Adding a 2 GB swap file for the build"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "Choosing the public address"
IP="$(hostname -I | awk '{print $1}')"
if [ -n "${1:-}" ]; then
  SITE="$1"
else
  # Every Linode has a reverse-DNS hostname for its IP; use it if it resolves back here, else sslip.io.
  SITE="$(python3 - "$IP" <<'PY' 2>/dev/null || true
import socket, sys
ip = sys.argv[1]
name = socket.gethostbyaddr(ip)[0]
print(name if ip in socket.gethostbyname_ex(name)[2] else "")
PY
)"
  [ -n "$SITE" ] || SITE="${IP//./-}.sslip.io"
fi
echo "Site address: https://$SITE"

say "Writing .env"
[ -f .env ] || cp .env.example .env
chmod 600 .env
set_env SITE_ADDRESS "$SITE"
set_env DEMO_MODE false                 # live weather
set_env REFRESH_INTERVAL_SECONDS 600    # re-evaluate every 10 minutes on its own
set_env MODEL_PROVIDER akamai
set_env STRANDS_FALLBACK_ENABLED false  # needs AWS credentials; Akamai only
set_env OBJ_PREFIX ""                   # the server writes to the top level of the bucket
[ -n "$(get_env OBJ_ENDPOINT)" ] || set_env OBJ_ENDPOINT https://us-ord-10.linodeobjects.com
[ -n "$(get_env OBJ_REGION)" ] || set_env OBJ_REGION us-ord
grep -q '^NWS_USER_AGENT=.*@\|^NWS_USER_AGENT=.*http' .env || ask NWS_USER_AGENT "NWS contact (app name and email or URL, e.g. ClosureCall (you@example.com))"
ask AKAMAI_API_KEY "Akamai workshop API key" secret
ask OBJ_BUCKET "Object Storage bucket name (e.g. weather-data-storage)"
ask OBJ_ACCESS_KEY "Object Storage access key"
ask OBJ_SECRET_KEY "Object Storage secret key" secret

say "Manager login"
# deploy/manager-auth holds Caddy config: a login on manager actions, or only a comment (open site).
if [ ! -s deploy/manager-auth ]; then
  read -rp "Require a manager login to record decisions and send notifications? [Y/n]: " WANT
  if [[ ! "$WANT" =~ ^[Nn] ]]; then
    read -rp "Manager username [manager]: " U; U="${U:-manager}"
    while :; do
      read -rsp "Manager password (12+ characters): " P; echo
      [ "${#P}" -ge 12 ] && break; echo "Too short."
    done
    HASH="$(docker run --rm caddy:2.8.4 caddy hash-password --plaintext "$P")"
    unset P
    cat > deploy/manager-auth <<AUTH
@manager_actions {
	path /api/*
}
basic_auth @manager_actions {
	$U $HASH
}
AUTH
  else
    # A comment plus a harmless directive (an empty import file only draws a warning, but this is unambiguous).
    {
      echo "# No manager login: anyone with the address can record decisions and send notifications."
      echo "header -X-Powered-By"
    } > deploy/manager-auth
  fi
  chmod 644 deploy/manager-auth  # a bcrypt hash at most; Caddy's container reads it
fi

if command -v ufw >/dev/null && ufw status | grep -q active; then
  say "Opening ports 80 and 443 in ufw"
  ufw allow 80/tcp && ufw allow 443 && ufw allow OpenSSH
fi

say "Checking the front-door configuration"
docker run --rm -e SITE_ADDRESS="$SITE" -v "$PWD/deploy/Caddyfile:/etc/caddy/Caddyfile:ro"   -v "$PWD/deploy/manager-auth:/etc/caddy/manager-auth:ro" caddy:2.8.4   caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

say "Building and starting (first build takes several minutes)"
docker compose -f deploy/compose.prod.yaml up -d --build

say "Waiting for the app"
for _ in $(seq 1 60); do curl -fs http://127.0.0.1:8000/api/health >/dev/null && break; sleep 5; done
curl -fs http://127.0.0.1:8000/api/health >/dev/null || { echo "App did not start; see: docker compose -f deploy/compose.prod.yaml logs app"; exit 1; }
curl -fs http://127.0.0.1:8000/api/storage/status; echo

say "Done"
echo "Open https://$SITE (the HTTPS certificate can take a minute on first visit)."
echo "Update later: git pull && docker compose -f deploy/compose.prod.yaml up -d --build"
