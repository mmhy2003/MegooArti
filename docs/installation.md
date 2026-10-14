# Installation

MegooArti is installed with Docker Compose, from this repository: the images are built
on the machine that runs them. It needs Docker with Compose (`docker compose`, version
2.1.1 or later, which has `up --wait`), and nothing else: the database is one of its
containers.

## What runs

Compose starts four containers: the database (PostgreSQL), the backend, the frontend,
and a gateway (nginx) that is the one published address and sends each request to the
backend or the frontend. The gateway speaks plain HTTP: as it is, it is for
development and testing. In production, put
[your own reverse proxy](#behind-your-own-reverse-proxy), with TLS, in front of it or
in its place.

What an installation holds is in two volumes: the database's, and the backend's data
directory (`/var/lib/megooarti`), which has the blob stores, where file content is
kept, and the key that stored secrets are sealed with.
[Backup and restore](backup.md) copies both.

## Before the first start

```bash
cp .env.example .env
```

and choose, in `.env`:

- **`MEGOOARTI_DB_PASSWORD`**, the database's password. Nothing starts without it. It
  is set when the database is first made: changing it later changes nothing in a
  database that exists.
- **`MEGOOARTI_HTTP_PORT`**, if the gateway is not to be at port 8000.
- **`MEGOOARTI_DB_PORT`**, if something on this machine has port 5432 already: the
  database is published there, on `127.0.0.1` only, and nothing starts while the port
  is taken.
- **`MEGOOARTI_SECRET_KEY`**, if you want to keep the key that seals stored secrets
  yourself. Without it the backend makes one in its data directory.

[Configuration](configuration.md) has every variable.

## Starting

```bash
docker compose up --build --detach --wait
curl http://localhost:8000/api/v1/status/ready
```

The second command prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`.
The web UI is at <http://localhost:8000>, and the API's documentation at
<http://localhost:8000/api/docs>.

On Windows, run Compose from the repository's path with its drive letter as a capital
(`cd C:\path\to\MegooArti`). From `c:\...`, which is where a VS Code terminal may
open, Docker Compose 5 stops the build with `additional privileges requested: pass
"--allow=fs.read=backend\\Dockerfile"`: it writes the drive letter of the build's
directory one way and of its Dockerfile the other, and Bake takes the Dockerfile
for a file outside the build.

A new installation has one blob store, `default`, and no repository:
[Repositories](repositories.md) makes the first.

`docker compose down` stops and removes the containers and keeps what they hold.
`docker compose down --volumes` destroys that too.

## First sign-in

On first start MegooArti creates the `admin` account with a random password, writes it
to `admin.password` in the data directory, and logs it once:

```bash
docker compose exec backend cat /var/lib/megooarti/admin.password
```

In Git Bash on Windows, write the path with two slashes at its start
(`//var/lib/megooarti/admin.password`): Git Bash makes a Windows path of it otherwise.
The password is also in the line of `docker compose logs backend` that says
`initial_admin_password`.

Sign in with it, as `admin`, at <http://localhost:8000>. You must then choose a new
password, after which the file is deleted. The same with `curl`:

```bash
curl -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<the generated password>"}' \
  http://localhost:8000/api/v1/auth/login

curl -b cookies.txt -X PUT -H 'Content-Type: application/json' \
  -H 'X-CSRF-Token: <the csrf_token of the first answer>' \
  -d '{"current_password":"<the generated password>","new_password":"<one of your own>"}' \
  http://localhost:8000/api/v1/me/password
```

The first answer contains a `csrf_token`. Requests that use the session cookie and
change anything must send it in an `X-CSRF-Token` header, as the second does. The
second answers `204`, with nothing in it. Until the password has been changed, every
other request as `admin` is refused with `403 password_change_required`, with the
session and with the password alike.

## The base URL

MegooArti gives its own address to clients: in the links of an npm package document,
in the address a container client is sent to for signing in, in what the web UI
offers to copy. It takes that address from each request unless the **base URL** is
set, and then from that.

Set it whenever clients reach MegooArti through something that changes the address:
your own reverse proxy, a load balancer, another name. It is set on the System page
of the web UI, or:

```bash
curl -u admin -X PUT -H 'Content-Type: application/json' \
  -d '{"base_url":"https://repo.example.com"}' \
  http://localhost:8000/api/v1/settings/base-url
```

It is an `http` or `https` address without a user name, a password, a query or a
fragment. MegooArti has to be at the root of its host: a base URL with a path does
not make the web UI, or the Docker registry, work under that path.

## Behind your own reverse proxy

One address serves everything, and each request goes to the right service:

| Path | To | What it is |
| --- | --- | --- |
| `/api/` | backend, port 8000 | The REST API and its documentation |
| `/repository/` | backend, port 8000 | Maven, npm, PyPI and Raw repositories |
| `/v2/` | backend, port 8000 | The Docker registry |
| everything else | frontend, port 3000 | The web UI |

[gateway/nginx.conf](../gateway/nginx.conf) does that: it is what Compose runs, and
the real-client tests of this project (Maven, npm, pip, Docker and a browser) pass
through it. It speaks plain HTTP, so something of yours terminates TLS, in one of two
places.

**In front of the gateway.** This is what the Compose file is made for, and nothing
in it changes. Your proxy sends every request to the gateway's port, and:

1. The gateway is published where only your proxy reaches it. For a proxy on the
   same machine, `MEGOOARTI_HTTP_PORT=127.0.0.1:8000` in `.env` publishes it on that
   machine alone.
2. The gateway passes on what your proxy says of the client, in place of what it
   sees itself, which is now your proxy. In `gateway/nginx.conf`:

   ```nginx
   proxy_set_header X-Forwarded-For $http_x_forwarded_for;
   proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
   ```

   and then `docker compose up --detach --force-recreate gateway`. Left as it was,
   the gateway gives every client your proxy's address: all of them share one limit
   of failed sign-ins, the log names the proxy for each, and the backend takes every
   request for plain HTTP, so that the [base URL](#the-base-url) has to be set.

**In the gateway's place.** Your proxy does what the gateway does, by the table
above. The Compose file has to be changed for that: it publishes neither the backend
nor the frontend, and your proxy must reach both, while nothing else may. It also
sets `MEGOOARTI_FORWARDED_ALLOW_IPS` to `*` on the backend, which is right only
while nothing but the gateway reaches the backend: set it to the address your
proxy's requests come from.

Either way, your proxy must do what the gateway does towards the backend:

- **Pass the path on exactly as it was sent.** An npm scope arrives as an encoded
  slash (`@scope%2fname`) and must stay one. In nginx that means `proxy_pass` with no
  path after the address.
- **Put no limit on the size of a body** (`client_max_body_size 0`), and do not buffer
  it: an artifact can be gigabytes, and goes to the backend as it arrives
  (`proxy_request_buffering off`). Do not buffer answers either
  (`proxy_buffering off`).
- **Wait long enough.** A proxy repository may take minutes to fetch a large file
  from its remote before the first byte comes back (`proxy_read_timeout 600s`).
- **Speak HTTP/1.1 to the backend** (`proxy_http_version 1.1`), so that a body of
  unknown length can be passed on as it arrives.
- **Send `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`.** The backend writes
  the addresses it gives to clients (tarball links, the registry's token address)
  from them, unless the base URL is set in the system settings. It believes them
  only from the addresses in `MEGOOARTI_FORWARDED_ALLOW_IPS`.
- **Write `X-Forwarded-For` yourself, from the address you see.** Do not pass on the
  one a client sent: the backend counts failed sign-ins by that address and writes it
  to its log, and a client that could choose it could evade the limit or lock out
  somebody else's address. (`gateway/nginx.conf` sets it to `$remote_addr`. If your
  proxy is itself behind another one that you trust, pass on what that one says.)
- **Terminate TLS**, and add `Strict-Transport-Security` if you want it. The frontend
  leaves compression to you as well.

Clients reach one address and no other. Do not let them at the backend's or the
frontend's own port beside it: the session cookie and the content security policy
assume one origin, and the backend of the Compose file believes whatever reaches it
about who is calling.

## Before it faces a network

- **Use HTTPS.** The session cookie is marked `Secure`: over plain HTTP from another
  machine nobody can sign in to the web UI. Maven and container clients refuse plain
  HTTP to any host but `localhost` as well.
- **Signing in is limited by user name and by address**: five failures within fifteen
  minutes stop further attempts for that name, from anywhere, until the window ends.
  Whoever can reach the sign-in can therefore keep a name, `admin` included, out of
  the web UI by guessing at it. Five failures from one address, whatever the names,
  stop every sign-in with a password from that address for as long
  (`429 too_many_attempts`, with a `Retry-After` header). Clients that share an
  address share that limit: behind one NAT, behind a proxy that does not say who
  they are, and under Docker Desktop, where the gateway sees one address for every
  client. An API token is never refused by this limit.
- **A page on another site cannot make a visitor's browser change anything**, signing
  in included. A page on a sibling of your host's name (`other.example.com` beside
  `repo.example.com`) counts as the site itself, as browsers have it: do not serve
  what you do not trust from one.
- **The API's description is open**: `/api/docs` and `/api/v1/openapi.json` answer
  anyone who can reach the server. They say what the API looks like, and nothing of
  what an installation holds.
- **A proxy repository fetches from whatever address it is given**, by whoever may
  set up repositories. If you proxy remotes you do not trust, restrict the server's
  outbound network access as well: [Repositories](repositories.md#proxy-repositories)
  says what is and is not checked.
