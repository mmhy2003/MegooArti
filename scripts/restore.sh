#!/bin/sh
# Restore what scripts/backup.sh wrote, into an installation that has nothing in it yet.
#
#   scripts/restore.sh <directory>
#
# Run it where docker-compose.yml and .env are, with the same MEGOOARTI_DB_PASSWORD or
# another: the password is this installation's, not the backup's. It refuses a database
# or a data directory that is not empty. `docker compose down --volumes` empties both.
# A backup of an older version is brought up to this one when the backend starts.
set -eu

source=${1:?usage: restore.sh <directory>}
if [ ! -f "$source/database.dump" ] || [ ! -f "$source/data.tar" ]; then
    echo "restore: $source has no database.dump and data.tar" >&2
    exit 2
fi
source=$(cd "$source" && pwd)
cd "$(dirname "$0")/.."
# Git Bash on Windows would rewrite the paths meant for the containers.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

echo "restore: starting the database"
docker compose up --detach --wait db

tables=$(docker compose exec -T db psql --username megooarti --dbname megooarti --no-align \
    --tuples-only --command \
    "select count(*) from information_schema.tables where table_schema = 'public'" | tr -d '\r')
if [ "$tables" != 0 ]; then
    echo "restore: the database is not empty. Restore into a new installation." >&2
    exit 3
fi
if ! docker compose run --rm --no-deps -T --entrypoint sh backend \
    -c 'test -z "$(ls -A /var/lib/megooarti)"'; then
    echo "restore: the data directory is not empty. Restore into a new installation." >&2
    exit 3
fi

echo "restore: the database"
docker compose exec -T db pg_restore --username megooarti --dbname megooarti --no-owner \
    --exit-on-error < "$source/database.dump"

echo "restore: the data directory"
docker compose run --rm --no-deps -T --entrypoint tar backend --extract --file - \
    --directory /var/lib/megooarti < "$source/data.tar"

echo "restore: starting everything"
docker compose up --detach --wait
echo "restore: done"
