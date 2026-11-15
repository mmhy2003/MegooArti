# Compose restart policy: design

A small change. An installation started with `docker compose up` comes back by itself
after a container crashes or the host reboots, unless someone stopped it on purpose.

## Intent

Today no service in `docker-compose.yml` has a restart policy: a crash, or a reboot of
the host, leaves the installation down until someone starts it again.

## Goals, non-goals

- **Goal:** every service (`db`, `backend`, `frontend`, `gateway`) restarts after a crash
  and after the Docker daemon starts again.
- **Goal:** a container stopped on purpose (`docker compose stop`) stays stopped, even
  across a reboot.
- **Non-goal:** anything beyond Compose: systemd units, orchestrators, health-based
  restarts of a container that is running but unhealthy.

## Constraints

- After a reboot Docker restarts the containers itself; Compose's `depends_on` and its
  `service_healthy` conditions are not applied. The installation must still converge:
  - the gateway resolves `backend` and `frontend` at each request
    (`gateway/nginx.conf`), so the order the containers start in does not matter to it;
  - a backend that starts before the database is ready and exits is restarted until the
    database answers.
- Containers come back after a reboot only if the Docker service itself starts at boot.

## Approaches

| Approach | Trade-off | |
|---|---|---|
| `restart: unless-stopped` on every service | Comes back after a crash or reboot; a stop on purpose is kept. | **Chosen** (asked for). |
| `restart: always` | Also restarts, at the daemon's start, a container someone stopped for maintenance. | Undoes a deliberate stop. |
| `restart: on-failure` | Restarts after a crash only, not after a reboot. | Misses the reboot. |

## The design

- `restart: unless-stopped` on all four services in `docker-compose.yml`, the database
  included: without it nothing else can start.
- One sentence in `docs/installation.md`, by the `docker compose down` lines: the
  containers start again after a crash or a reboot unless they were stopped, and for a
  reboot the Docker service must be enabled at boot.

## Left to the builder

- Where in each service the key goes (my call: right after `image`/`build`, the same
  place in each).
- The wording of the sentence in `docs/installation.md`.
