# APT repositories

What is true of every repository is in [Repositories](../repositories.md). This is
what is this format's own: Debian and Ubuntu packages, installed with apt.

A hosted repository holds the `.deb` files you build, and signs its indexes with a key
of its own:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "apt-hosted", "format": "apt", "type": "hosted",
  "format_config": {"suite": "stable"}
}' http://localhost:8000/api/v1/repositories

curl -u ci --upload-file megooarti-hello_1.0_all.deb https://repo.example.com/repository/apt-hosted/
```

On each machine that installs from it, as root: the repository's public key, the
repository itself, and the account apt signs in with.

```bash
curl -fsS -u ci -o /etc/apt/keyrings/megooarti.asc \
  https://repo.example.com/repository/apt-hosted/public.key
echo "deb [signed-by=/etc/apt/keyrings/megooarti.asc] https://repo.example.com/repository/apt-hosted stable main" \
  > /etc/apt/sources.list.d/megooarti.list
printf 'machine repo.example.com\nlogin ci\npassword %s\n' "$MEGOOARTI_TOKEN" \
  > /etc/apt/auth.conf.d/megooarti.conf
chmod 600 /etc/apt/auth.conf.d/megooarti.conf

apt-get update && apt-get install megooarti-hello
```

A proxy caches a distribution's mirror. apt goes on checking the distribution's own
signatures, with the keyring it already has:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "apt-debian", "format": "apt", "type": "proxy",
  "proxy": {"remote_url": "http://deb.debian.org/debian"}
}' http://localhost:8000/api/v1/repositories

echo "deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://repo.example.com/repository/apt-debian trixie main" \
  > /etc/apt/sources.list.d/debian.list
```

For Ubuntu, the remote is `http://archive.ubuntu.com/ubuntu` and the keyring
`/usr/share/keyrings/ubuntu-archive-keyring.gpg`.

- **Credentials** go in a file of `/etc/apt/auth.conf.d/`, as above: a user name and a
  password, or a user name and an API token. apt sends them over HTTPS to the host a
  `machine` line names; over plain HTTP only if the line says so
  (`machine http://repo.example.com`).
- **A hosted repository has one suite**, chosen when it is made (`stable` unless you
  say otherwise) and fixed after, and one component, `main`. For a second suite, make
  a second repository.
- **A package is uploaded to the repository's root**, with `PUT` or `POST`, or
  through the web UI or [the API](../api.md#uploading) (one or more `file` fields). Its
  `control` file says where it goes:
  `pool/main/<letter>/<name>/<name>_<version>_<architecture>.deb`, with the version's
  epoch left out of the file's name, as Debian does. A file that is not a Debian
  package, or whose `control` has no `Package`, `Version` or `Architecture`, is
  refused with `400 invalid_package`. Packages whose control archive is compressed
  with gzip, xz, zstd or nothing are taken; at most 16 MiB of it is read.
- **Uploading a package again** (the same name, version and architecture) follows the
  deployment policy. With `disable_redeploy` it answers `409`.
- **The indexes are written from the packages**: `Packages` (also `.gz` and `.xz`) for
  each architecture, and `Release`, signed as `InRelease` and `Release.gpg`. They are
  written once after each change and kept in memory until the next. `amd64` and
  `arm64` are always listed, beside the architectures of the packages, and a package
  for `all` architectures is listed under each: a machine of either keeps finding
  those whatever is uploaded for another. A client is sent an index again unless it
  has the same bytes (`If-None-Match`): two changes within one second have the same
  date.
- **The signing key** is made the first time it is needed: an Ed25519 OpenPGP key that
  never expires. `GET /api/v1/repositories/<name>/signing-key` shows it, and
  `POST /api/v1/repositories/<name>/signing-key/generate` (with
  `{"algorithm": "rsa4096"}` for an RSA key) or `PUT` of an armoured private key in
  `private_key` replaces it, for whoever holds `admin:repositories:write`. From then on
  the indexes are signed with the new key only: every machine must fetch the new
  `public.key`. The private key is kept sealed with the installation's secret key, and
  is never shown.
- **Deleting** a package (`DELETE` on its address under `pool/`) takes it out of the
  indexes at once.
- **A proxy**'s remote is a mirror's root. What is under `dists/` is checked again with
  the remote after `metadata_max_age_minutes`; packages, and files under a `by-hash/`
  directory, never change and are kept.
- Groups of APT repositories are not available yet.

## Clients

Tested with apt on Debian 13 and Ubuntu 26.04: a package built with `dpkg-deb`,
uploaded and installed from a hosted repository; a repository signed with a key apt
was not given, refused; and a package from each distribution's mirror, installed
through a proxy.
