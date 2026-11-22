#!/bin/sh
# The web UI's browser tests (frontend/e2e/) against a stack megoocolab-runner started
# from megoocolab.toml's "ui" set, which gives the variables used here:
#
#   megoocolab-runner services run ui -- sh scripts/ui-e2e.sh
#
# The tests begin with the first sign-in of a new installation: the runner makes a
# fresh stack for every run. Chromium must be installed once:
#   cd frontend && pnpm exec playwright install chromium
set -eu
cd "$(dirname "$0")/.."
: "${MEGOO_SERVICES_PROJECT:?run this through: megoocolab-runner services run ui}"
# Not a developer's own .env beside docker-compose.yml.
export COMPOSE_ENV_FILES="$PWD/backend/tests/compose.env"
stack() {
  docker compose --project-name "$MEGOO_SERVICES_PROJECT" \
    -f docker-compose.yml -f tools/test-services/ui.yml "$@"
}

# The password the backend made for admin when it first started.
tries=0
until MEGOOARTI_INITIAL_PASSWORD=$(stack exec -T backend cat /var/lib/megooarti/admin.password 2>/dev/null) \
  && [ -n "$MEGOOARTI_INITIAL_PASSWORD" ]; do
  tries=$((tries + 1))
  if [ "$tries" -ge 90 ]; then echo "the backend wrote no password for admin" >&2; exit 1; fi
  sleep 2
done
export MEGOOARTI_INITIAL_PASSWORD

# Until the gateway answers.
node -e 'const u = process.env.MEGOOARTI_UI_URL + "/healthz"; let n = 0;
(function t() { fetch(u).then((r) => (r.ok ? process.exit(0) : Promise.reject()))
  .catch(() => (++n < 90 ? setTimeout(t, 2000) : process.exit(1))); })();'

cd frontend
export CI=1
exec pnpm e2e
