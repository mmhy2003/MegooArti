#!/bin/sh
# Migrate the database, then start the application.
set -eu

if [ "${MEGOOARTI_RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "entrypoint: waiting for the database"
    python -m megooarti.db.wait
    echo "entrypoint: applying database migrations"
    alembic upgrade head
else
    echo "entrypoint: MEGOOARTI_RUN_MIGRATIONS is not 'true'; skipping migrations"
fi

exec "$@"
