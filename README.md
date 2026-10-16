# MegooArti

An open-source repository and artifact proxy and manager. It keeps Maven, npm, PyPI,
Docker, APT, YUM, apk, NuGet and Raw repositories, each of them hosted, a proxy of a
remote one, or a group of several behind one address, with a web UI and a REST API.
See the
[business requirements](docs/BRD.md) for scope and roadmap, and the
[changelog](CHANGELOG.md) for what this version has and what is known of it.

It is two services and a database: a backend (FastAPI) that is the REST API, the
repositories and the Docker registry, and a web UI (Next.js) that uses that API.

## Quick start

Requires Docker with Compose.

```bash
cp .env.example .env          # then set MEGOOARTI_DB_PASSWORD in it
docker compose up --build --detach --wait
curl http://localhost:8000/api/v1/status/ready
```

Nothing starts until the database has a password of your choosing: `.env.example`
says what else an installation may choose. `docker compose build` makes the images
`ghcr.io/mmhy2003/megooarti-backend` and `ghcr.io/mmhy2003/megooarti-frontend`,
tagged with the version. They are named for the project's own place in GitHub's
registry; nothing is published there yet, so they are built here.

The last command prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`.
The web UI is at <http://localhost:8000>, and interactive API documentation at
<http://localhost:8000/api/docs>.

The first start makes an administrator, and writes its password to a file:

```bash
docker compose exec backend cat /var/lib/megooarti/admin.password
```

(In Git Bash on Windows, with two slashes: `//var/lib/megooarti/admin.password`.)
Sign in with it, as `admin`, at <http://localhost:8000>, and choose a password of
your own. [Installation](docs/installation.md) says the rest.

Compose starts four containers: the database, the backend, the frontend, and a
gateway (nginx) that is the one published address and sends each request to the
backend or the frontend. The gateway speaks plain HTTP: as it is, it is for
development and testing. In production, put
[your own reverse proxy](docs/installation.md#behind-your-own-reverse-proxy), with
TLS, in front of it or in its place.

## Guides

| Guide | What it says |
| --- | --- |
| [Installation](docs/installation.md) | What runs, what to choose before the first start, the first sign-in, the base URL, your own reverse proxy and TLS |
| [Configuration](docs/configuration.md) | Every environment variable, what Compose reads, and the settings kept in the database |
| [Upgrading](docs/upgrade.md) | Bringing an installation to a new version, and going back |
| [Backup and restore](docs/backup.md) | The two scripts, what a backup holds, and what it does not |
| [Administration](docs/administration.md) | Users, roles, permissions, API tokens, anonymous access, and what is running |
| [Repositories](docs/repositories.md) | Hosted, proxy and group repositories, permissions and policies, whatever the format |
| [Maven](docs/formats/maven.md), [npm](docs/formats/npm.md), [PyPI](docs/formats/pypi.md), [Docker](docs/formats/docker.md), [APT](docs/formats/apt.md), [YUM](docs/formats/yum.md), [apk](docs/formats/apk.md), [NuGet](docs/formats/nuget.md), [Raw](docs/formats/raw.md) | Setting up each format, and each of its clients |
| [The web UI](docs/web-ui.md) | What the screens do |
| [The API](docs/api.md) | Who is calling, errors, lists, and browsing, uploading and searching without a package client |
| [Development](docs/development.md) | Running from source, the tests, and the rules of the code |
| [Adding a format](docs/adding-a-format.md) | The interface a format implements, and what is expected of one |

## Licence

MIT: see [LICENSE](LICENSE). Two things in the repository are other projects' and
keep their own licences, each beside its files: Swagger UI, which draws the API's
documentation page (Apache-2.0, in `backend/src/megooarti/static/swagger-ui/`), and
the three typefaces of the web UI, Oxanium, Inter and JetBrains Mono (SIL Open Font
License, in `frontend/src/fonts/`).
