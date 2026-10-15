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
The repository's page in the web UI gives these commands with its own address, under
"Set up a machine".

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

## Groups

A group puts your own repositories and the mirrors behind one address, and signs
everything it serves with a key of its own: a machine needs that one key, and nothing
else. The group checks for it what apt would have checked, so a proxy can be a member
only if it has its remote's public keys, armoured. For Debian's, on a machine that has
the keyring and GnuPG:

```bash
keys=$(gpg --no-default-keyring --keyring /usr/share/keyrings/debian-archive-keyring.gpg \
  --export --armor)
jq -n --arg keys "$keys" '{
  name: "apt-debian", format: "apt", type: "proxy",
  proxy: {remote_url: "http://deb.debian.org/debian"},
  format_config: {remote_keys: $keys}
}' | curl -u admin -H 'Content-Type: application/json' -d @- \
  http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "apt-public", "format": "apt", "type": "group",
  "group": {"members": ["apt-hosted", "apt-debian"]}
}' http://localhost:8000/api/v1/repositories
```

On each machine, the group's key and a line for each suite:

```bash
curl -fsS -u ci -o /etc/apt/keyrings/apt-public.asc \
  https://repo.example.com/repository/apt-public/public.key
cat > /etc/apt/sources.list.d/megooarti.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/apt-public.asc] https://repo.example.com/repository/apt-public stable main
deb [signed-by=/etc/apt/keyrings/apt-public.asc] https://repo.example.com/repository/apt-public trixie main
EOF
```

- **The group writes a `Release` of its own for each suite**, and says in it whose
  suite it is as its first proxy member that has the suite says it (for Debian,
  `Origin: Debian`, `Codename: trixie`), or else as its first member does: apt refuses
  a suite whose Origin, Label or Codename changes, and unattended upgrades and pins go
  by them. Adding or removing a member before that one changes them, and every
  machine must then run `apt-get update --allow-releaseinfo-change` once. Its `Date`
  does not go back, and it is valid no longer than a member's `Valid-Until` says.
- **A suite one member has** names that member's files as its own `Release` does, and
  every file of the suite is sent on from that member; apt checks each against the
  group's `Release`, as it would have checked it against the mirror's.
- **A suite several members have** (a hosted repository whose suite is `trixie`,
  beside a proxy of Debian; or `stable`, which Debian's mirrors have as well, as a
  name for the current release) names, for a component and architecture one member
  has, that member's files, and for one that several have, one `Packages.gz` written
  from theirs, in the order of the members, a package (the same name, version and
  architecture) that an earlier member has left out of a later one's.
- **A member is checked before it is used**: a proxy's `InRelease` must be signed by
  one of its `remote_keys` and must not have expired, and each `Packages` file the
  group reads must be the one that `Release` names, read by its hash where the remote
  says `Acquire-By-Hash: yes`. A member that fails is left out, it is logged, and the
  proxy's page says why as its last error until the proxy next reaches its remote. A
  proxy whose remote has no `InRelease` is left out without a word.
- **While a member the last index had cannot be checked**, that index is kept a
  minute longer, and the group then tries again; what was written without a member
  is tried again after a minute as well.
- **The index is written again when a member's changes**, behind the requests: a
  machine is given the last one meanwhile, and waits only the first time. Merging
  Debian's `main` for one architecture takes about two seconds; the first time, for a
  suite of several components and architectures over two mirrors, fetching their
  indexes takes minutes.
- **Packages** are asked of the members in order, as in any group. A package's path
  in the pool must therefore be the same file in every member that has it: two hosted
  repositories that each hold `app_1.0-1_amd64.deb`, built for another suite, cannot be
  in one group, as the first one's file would be given for both.
- **The group's key** is made the first time it is needed, and is at
  `/repository/<group>/public.key`, as a hosted repository's is.

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
  is never shown. The repository's settings page in the web UI shows the key, with
  its public key to download, and replaces it after asking.
- **Deleting** a package (`DELETE` on its address under `pool/`) takes it out of the
  indexes at once.
- **A proxy**'s remote is a mirror's root. What is under `dists/` is checked again with
  the remote after `metadata_max_age_minutes`; packages, and files under a `by-hash/`
  directory, never change and are kept.
- **A proxy's `remote_keys`**, its remote's public keys, armoured, are what a group
  it is a member of checks it with; a proxy that is not in a group does not use them,
  and apt checks the mirror's signatures itself.

## Clients

Tested with apt on Debian 13 and Ubuntu 26.04: a package built with `dpkg-deb`,
uploaded and installed from a hosted repository; a repository signed with a key apt
was not given, refused; a package from each distribution's mirror, installed through
a proxy; and, on Debian, both through a group, with a suite of each member and with a
suite they share, and a member signed by a key it was not given left out.
