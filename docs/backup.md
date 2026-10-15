# Backup and restore

A backup is two files: the database, and the data directory, which holds the blob
stores and the key that stored secrets are sealed with.

```bash
sh scripts/backup.sh /path/to/backup
```

It backs up the installation that `docker compose` finds from the repository's
directory; if yours was started under another project name, set
`COMPOSE_PROJECT_NAME` to it. Nothing is stopped, but the database and the backend
must be running. The database is dumped first and the files are copied after: a file
is on the disk before the database names it, and stays for
`MEGOOARTI_BLOB_GRACE_SECONDS` (a day) after nothing names it, so a copy made after
the dump has every file the dump names, as long as the backup takes less than that.

It writes `database.dump`, `data.tar` and `VERSION` into the directory, readable by
their owner alone where the file system keeps such permissions (on Windows it does
not: choose a directory that only you can read). The dump has every password's hash,
and the copy has the key. A
backup that is there already is replaced only when the new one is whole; if anything
fails, the script says so, ends with an error, and leaves the old one as it was. It
names any blob store whose directory is outside the data directory: those files are
not in the backup, and are yours to copy.

To restore, into an installation that has nothing in it yet (a new machine, or after
`docker compose down --volumes`, which destroys what is there):

```bash
cp .env.example .env          # then set MEGOOARTI_DB_PASSWORD: this installation's own
docker compose build          # where the images have not been built yet
sh scripts/restore.sh /path/to/backup
```

It starts the database, refuses a database or a data directory that is not empty,
and reads both files through before it writes anything. (Without the build, the
script's first look at the data directory builds the backend's image, and says
nothing for as long as that takes.) Should it stop between its two halves, it says so:
what is there is then not whole, and `docker compose down --volumes` empties it for
another try. Users, sessions, API tokens, repositories and their content are then as
they were when the backup was made, and what was stored after it is gone. A backup of
an older version is brought up to this one when the backend starts.

Without the key (`secret.key` in the data directory, or `MEGOOARTI_SECRET_KEY` if you
set one) a proxy's stored password cannot be read and must be entered again, and an
APT, YUM or apk repository's signing key must be generated again and given to every
machine that installs from it. Nothing else that is kept depends on it. If you set `MEGOOARTI_SECRET_KEY`, keep it with the
backup: it is not in it.

Keep a backup as you would keep a password. Besides the hashes, it has the key, which
also seals the tokens a container client is given when it signs in: they last five
minutes, and whoever has the key can make one for any user.

## What a backup does not have

- **A blob store whose directory is outside the data directory.** The script names
  each when it runs. Copy those directories yourself, after the script has run, and
  put them back at the same paths before the restored installation is used.
- **`MEGOOARTI_SECRET_KEY`**, if you set one, and the rest of `.env`.
- **What was stored after it was made.**

## Good to know

- A backup must take less than `MEGOOARTI_BLOB_GRACE_SECONDS` (a day, unless you
  changed it): that is how long a file that nothing names any more stays on the disk.
- A file that was stored between the two halves of a backup is in the copy of the
  files and not in the database. After a restore it is a file that nothing names: it
  takes its space, and does nothing else.
- A backup is restored into the version it was made with, or a newer one. An older
  version cannot read a newer one's database.
- The scripts are plain `sh`, and use nothing that POSIX does not have. They have
  been run from Git Bash on Windows, against the containers, which are Linux.
