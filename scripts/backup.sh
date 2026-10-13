#!/bin/sh
# Back up a running installation into a directory: the database, then the data directory.
#
#   scripts/backup.sh <directory>
#
# Run it where docker-compose.yml and .env are. Nothing is stopped. The order is what
# makes the two halves fit: a file is on the disk before the database names it, and is
# kept there for a day after nothing names it any more. So a copy of the files made
# after the database was dumped has every file that dump names.
set -eu

target=${1:?usage: backup.sh <directory>}
cd "$(dirname "$0")/.."
# Git Bash on Windows would rewrite the paths meant for the containers.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
mkdir -p "$target"

echo "backup: the database"
docker compose exec -T db pg_dump --username megooarti --format custom megooarti \
    > "$target/database.dump"

echo "backup: the data directory"
status=0
docker compose exec -T backend tar --create --file - --directory /var/lib/megooarti \
    --exclude './blobs/*/tmp' . > "$target/data.tar" || status=$?
# 1 is tar's "a file changed while it was read": an upload that was going on. What the
# database names does not change once it is there.
if [ "$status" -gt 1 ]; then
    echo "backup: the data directory could not be read (tar ended with $status)" >&2
    exit "$status"
fi

docker compose exec -T backend python -c 'import megooarti; print(megooarti.__version__)' \
    | tr -d '\r' > "$target/VERSION"

# A blob store may keep its files anywhere. Those under the data directory are in the
# copy; the others are not this script's to find.
outside=$(docker compose exec -T db psql --username megooarti --dbname megooarti --no-align \
    --tuples-only --command \
    "select name || ' at ' || (config->>'path') from blob_stores where config->>'path' like '/%'" \
    | tr -d '\r')
if [ -n "$outside" ]; then
    echo "backup: NOT in this backup, because they are outside the data directory:" >&2
    echo "$outside" | sed 's/^/backup:   the blob store /' >&2
fi

echo "backup: done, version $(cat "$target/VERSION"), in $target"
