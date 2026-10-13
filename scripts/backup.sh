#!/bin/sh
# Back up a running installation into a directory: the database, then the data directory.
#
#   scripts/backup.sh <directory>
#
# The installation is the one `docker compose` finds from the repository's directory:
# with COMPOSE_PROJECT_NAME set if it was started under another name. Nothing is
# stopped. The order is what makes the two halves fit: a file is on the disk before the
# database names it, and is kept there for MEGOOARTI_BLOB_GRACE_SECONDS (a day) after
# nothing names it any more. So a copy of the files made after the database was dumped
# has every file that dump names, as long as the backup takes less than that.
#
# What is in the directory already is replaced only when the new backup is whole: until
# then it is written beside it, under names that end in .part.
set -eu
# The dump has every password's hash and the copy has the key: for the owner alone.
umask 077

target=${1:?usage: backup.sh <directory>}
mkdir -p "$target"
target=$(cd "$target" && pwd)
cd "$(dirname "$0")/.."
# Git Bash on Windows would rewrite the paths meant for the containers.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

fail() {
    echo "backup: $*" >&2
    echo "backup: NOT done. What was in $target before is as it was." >&2
    rm -f "$target/database.dump.part" "$target/data.tar.part" "$target/tar.err.part"
    exit 1
}

# Asked first: a service that is not running ends `docker compose exec` with status 1,
# which is also how tar says that a file changed while it was read.
docker compose exec -T db true || fail "the database is not running"
docker compose exec -T backend true || fail "the backend is not running"

echo "backup: the database"
docker compose exec -T db pg_dump --username megooarti --format custom megooarti \
    > "$target/database.dump.part" || fail "the database could not be dumped"
[ -s "$target/database.dump.part" ] || fail "the dump of the database is empty"

echo "backup: the data directory"
# tar says how it ended on a line of its own, apart from how Docker ended.
docker compose exec -T backend sh -c \
    'tar --create --file - --directory /var/lib/megooarti . ; echo "tar-status:$?" >&2' \
    > "$target/data.tar.part" 2> "$target/tar.err.part" || true
grep -v '^tar-status:' "$target/tar.err.part" >&2 || true
ended=$(sed -n 's/^tar-status:\([0-9][0-9]*\).*/\1/p' "$target/tar.err.part")
rm -f "$target/tar.err.part"
[ -n "$ended" ] || fail "the copy of the data directory was cut off"
# 1 is tar's "a file changed while it was read": an upload that was going on. What the
# database names does not change once it is there.
[ "$ended" -le 1 ] || fail "the data directory could not be read (tar ended with $ended)"
[ -s "$target/data.tar.part" ] || fail "the copy of the data directory is empty"

version=$(docker compose exec -T backend python -c \
    'import megooarti; print(megooarti.__version__)') || fail "the version could not be asked"
version=$(printf '%s' "$version" | tr -d '\r')
[ -n "$version" ] || fail "the backend named no version"

# A blob store may keep its files anywhere. Those under the data directory are in the
# copy; the others are not this script's to find.
outside=$(docker compose exec -T db psql --username megooarti --dbname megooarti --no-align \
    --tuples-only --command "select name || ' at ' || (config->>'path') from blob_stores
        where config->>'path' like '/%' and config->>'path' not like '/var/lib/megooarti/%'") \
    || fail "the blob stores could not be listed"
outside=$(printf '%s' "$outside" | tr -d '\r')

mv -f "$target/database.dump.part" "$target/database.dump"
mv -f "$target/data.tar.part" "$target/data.tar"
printf '%s\n' "$version" > "$target/VERSION"

if [ -n "$outside" ]; then
    echo "backup: NOT in this backup, because they are outside the data directory:" >&2
    printf '%s\n' "$outside" | sed 's/^/backup:   the blob store /' >&2
fi
echo "backup: done, version $version, in $target"
