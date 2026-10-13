#!/bin/sh
# Restore what scripts/backup.sh wrote, into an installation that has nothing in it yet.
#
#   scripts/restore.sh <directory>
#
# The installation is the one `docker compose` finds from the repository's directory
# (with COMPOSE_PROJECT_NAME set if it is to have another name), with its own
# MEGOOARTI_DB_PASSWORD: the password is this installation's, not the backup's. It
# refuses a database or a data directory that is not empty; `docker compose down
# --volumes` empties both. Both halves of the backup are read through before anything
# is written. A backup of an older version is brought up to this one when the backend
# starts.
set -eu

source=${1:?usage: restore.sh <directory>}
if [ ! -s "$source/database.dump" ] || [ ! -s "$source/data.tar" ]; then
    echo "restore: $source has no database.dump and data.tar" >&2
    exit 2
fi
source=$(cd "$source" && pwd)
cd "$(dirname "$0")/.."
# Git Bash on Windows would rewrite the paths meant for the containers.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

if [ -s "$source/VERSION" ]; then
    echo "restore: a backup of version $(tr -d '\r' < "$source/VERSION")"
fi

echo "restore: starting the database"
docker compose up --detach --wait db

tables=$(docker compose exec -T db psql --username megooarti --dbname megooarti --no-align \
    --tuples-only --command \
    "select count(*) from information_schema.tables where table_schema = 'public'") || {
    echo "restore: the database could not be asked what it holds. Nothing was restored." >&2
    exit 1
}
tables=$(printf '%s' "$tables" | tr -d '\r ')
if [ "$tables" != 0 ]; then
    echo "restore: the database is not empty. Restore into a new installation." >&2
    exit 3
fi
# An image that is not there yet is built before it is run, and the building is
# printed where the answer goes: the answer is the line that says it is one.
echo "restore: looking at the data directory (the backend's image is built first, if it is not there)"
found=$(docker compose run --rm --no-deps -T --entrypoint sh backend \
    -c 'echo "found:$(ls -A /var/lib/megooarti | wc -l)"') || {
    echo "restore: the backend's image could not be run. Nothing was restored." >&2
    exit 1
}
found=$(printf '%s\n' "$found" | tr -d '\r ' | sed -n 's/^found:\([0-9][0-9]*\)$/\1/p' | tail -n 1)
case "$found" in
    0) ;;
    '')
        echo "restore: the data directory could not be looked at. Nothing was restored." >&2
        exit 1
        ;;
    *)
        echo "restore: the data directory is not empty. Restore into a new installation." >&2
        exit 3
        ;;
esac

# Read through first: a restore that stops between its halves leaves a database that
# names files that are not there.
echo "restore: reading the backup through"
docker compose exec -T db pg_restore --list < "$source/database.dump" > /dev/null || {
    echo "restore: database.dump cannot be read. Nothing was restored." >&2
    exit 2
}
docker compose run --rm --no-deps -T --entrypoint tar backend --list --file - \
    < "$source/data.tar" > /dev/null || {
    echo "restore: data.tar cannot be read. Nothing was restored." >&2
    exit 2
}

half() {
    echo "restore: it stopped half way, and what is there now is not whole." >&2
    echo "restore: empty it with 'docker compose down --volumes', and restore again." >&2
    exit 1
}

echo "restore: the database"
docker compose exec -T db pg_restore --username megooarti --dbname megooarti --no-owner \
    --exit-on-error --single-transaction < "$source/database.dump" || half

echo "restore: the data directory"
docker compose run --rm --no-deps -T --entrypoint tar backend --extract --file - \
    --directory /var/lib/megooarti < "$source/data.tar" || half

echo "restore: starting everything"
docker compose up --detach --wait || {
    echo "restore: everything was restored, and the installation did not start:" >&2
    echo "restore: 'docker compose logs backend' says why." >&2
    exit 1
}
echo "restore: done"
