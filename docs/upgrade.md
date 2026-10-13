# Upgrading

An upgrade is a new build of the two images, started on the database and the data
directory that are there. The backend brings the database to its version when it
starts.

1. Read the [changelog](../CHANGELOG.md) for the version: it says what a caller of
   the API and an operator must know, and whether there is something to do afterwards.
2. [Back up](backup.md). A backup made just before is the way back.
3. Get the version's sources (`git pull`, or a checkout of the version you want),
   then build and start:

   ```bash
   docker compose up --build --detach --wait
   curl http://localhost:8000/api/v1/status/ready
   ```

Both images have one version, which `docker compose build` tags them with
(`MEGOOARTI_VERSION` to choose another tag). If your `.env` sets `MEGOOARTI_VERSION`,
change it with the version: otherwise the new build takes the old tag, and the image
of the version you came from no longer has it.

## What happens to the database

The schema is managed only by [Alembic](https://alembic.sqlalchemy.org/).
The container entrypoint waits for the database, runs
`alembic upgrade head`, and then starts the application. If a migration fails, the
container exits with an error and the application does not start. Several containers
may start at once; a database lock ensures only one applies migrations. To run
migrations as a separate deployment step instead, set `MEGOOARTI_RUN_MIGRATIONS=false`
on the application containers and run this once per release:

```bash
docker compose run --rm -e MEGOOARTI_RUN_MIGRATIONS=true backend true
```

The `-e` flag matters: without it the one-off container inherits
`MEGOOARTI_RUN_MIGRATIONS=false` from the service and skips the migration.

While the database is at another revision than a running backend expects,
`/api/v1/status/ready` answers `503`, and the System page of the web UI says which
revision the database is at and which the version expects. That is what a container
that was already running says once another has migrated the database. One that is
started on a database of a newer version does not get that far:
[Going back](#going-back) says what it does.

The migrations create PostgreSQL's `pg_trgm` extension, which search uses. With a
database of your own, where the application's role may not create extensions, have a
database administrator run `CREATE EXTENSION pg_trgm` in the database before the
first start.

## Going back

Starting the older version on a database the newer one has migrated does not undo
the migration, and the older version does not start: its entrypoint finds a revision
it does not know (`Can't locate revision identified by ...`, in
`docker compose logs backend`) and the container exits. The gateway then answers
`502` for the API and the repositories, while the pages of the web UI still load.
To go back, restore the backup made before the upgrade into an installation of the
older version, as [Backup and restore](backup.md) says. What was stored after that
backup is not in it.

## After an upgrade

- **Rebuilding an index.** `POST /api/v1/repositories/<name>/rebuild-index` (for an
  administrator) goes through a repository again: every file is given to the
  component its path says it belongs to, and every component's words are written
  again. It answers with how many files and components it looked at and changed.
  Run it for a repository when the changelog of a version says that what was
  stored before is to be gone through again. The work is done in the request, a
  piece at a time, and takes minutes on a large
  repository. It is safe to repeat: if the request is cut off, for example by a
  reverse proxy's time limit, what was done stays done; run it again.
