# apk repositories

What is true of every repository is in [Repositories](../repositories.md). This is
what is this format's own: Alpine Linux packages, installed with apk.

A hosted repository holds the `.apk` files you build with abuild, laid out as Alpine's
mirrors are: each architecture's packages in a directory of that name, under a path
of your choosing (`v3.24/main/x86_64/`). It writes each directory's
`APKINDEX.tar.gz` and signs it with an RSA key of its own:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "apk-hosted", "format": "apk", "type": "hosted"
}' http://localhost:8000/api/v1/repositories

curl -u ci --upload-file megooarti-hello-1.0-r0.apk \
  https://repo.example.com/repository/apk-hosted/v3.24/main/x86_64/
```

On each machine that installs from it, as root: the repository's public key, saved
under the name apk finds it by, and the repository, with the account apk signs in with.
apk adds the machine's architecture to the address itself.

```bash
wget -q -O /etc/apk/keys/megooarti-apk-hosted.rsa.pub \
  "https://ci:$MEGOOARTI_TOKEN@repo.example.com/repository/apk-hosted/megooarti-apk-hosted.rsa.pub"
echo "https://ci:$MEGOOARTI_TOKEN@repo.example.com/repository/apk-hosted/v3.24/main" \
  >> /etc/apk/repositories

apk update && apk add megooarti-hello
```

A proxy caches Alpine's mirror. apk goes on checking Alpine's own signatures, with the
keys it already has:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "apk-alpine", "format": "apk", "type": "proxy",
  "proxy": {"remote_url": "https://dl-cdn.alpinelinux.org/alpine"}
}' http://localhost:8000/api/v1/repositories

echo "https://repo.example.com/repository/apk-alpine/v3.24/main" > /etc/apk/repositories
```

- **Credentials** go in the address, as above: a user name and a password, or a user
  name and an API token. `/etc/apk/repositories` then holds a secret: keep it readable
  by root alone.
- **A package is uploaded to its architecture's directory**, under the name apk asks
  for it by, `<name>-<version>.apk`, with `PUT` (`curl --upload-file` to an address
  ending in `/` adds the file's name), or through the web UI or
  [the API](../api.md#uploading), with a `directory` field (the architecture's
  directory) and one or more `file` fields, which are stored under that name whatever
  they are called. A package for an architecture uploaded to another's directory, or
  under another name, is refused with `400 invalid_path`. A package for no
  architecture (`noarch`) may go in any architecture's directory, and is listed there
  as that architecture's, as `abuild` lists it.
- **What is read of a package** is its `.PKGINFO`, at most 16 MiB of its signature
  and control part. A `.PKGINFO` larger than 1 MiB, a field of it longer than 64 KiB
  (all its `depend` lines together count as one), or one that holds a NUL, is
  refused: apk stops reading an index at a line longer than it holds, and would lose
  every package after it. A file that is not an apk package as `abuild` writes it is refused
  with `400 invalid_package`, and so is one in apk-tools 3's newer package format
  (ADB), which Alpine does not publish yet. A package's own signature is not checked:
  apk installs a package the repository's signed index names, by its checksum,
  whatever key it was built with.
- **A package's version** is its name and `<version>-r<release>`: that is what the
  web UI shows, and what `apk add` is given (`apk add megooarti-hello=1.0-r0`). Each
  architecture's file is one file of it.
- **Uploading a package again** to the same path follows the deployment policy. With
  `disable_redeploy` it answers `409`.
- **The indexes are written from the packages**: each directory's `APKINDEX.tar.gz`,
  with each package's record as apk-tools 3's `apk index` writes it, signed as
  `abuild-sign` signs one (RSA, SHA-1). Every directory has one: one without packages
  has an empty one, so a machine can be set up before anything is uploaded for it.
  They are written once after each change and kept in memory until the next. A client
  is sent an index again unless it has the same bytes (`If-None-Match`).
- **The signing key** is made the first time it is needed: an RSA key of 4096 bits,
  served at `/repository/<name>/megooarti-<name>.rsa.pub`.
  `GET /api/v1/repositories/<name>/signing-key` shows it, and
  `POST /api/v1/repositories/<name>/signing-key/generate` or `PUT` of a PEM private
  key in `private_key` (as `abuild-keygen` makes one, of 2048 to 8192 bits) replaces
  it, for whoever holds `admin:repositories:write`. From then on the indexes are
  signed with the new key only: every machine must fetch it again. The private key is
  kept sealed with the installation's secret key, and is never shown.
- **Deleting** a package (`DELETE` on its address) takes it out of its directory's
  index at once.
- **A proxy**'s remote is a mirror's root. Each `APKINDEX.tar.gz` is checked again
  with the remote after `metadata_max_age_minutes`; packages never change, and are
  kept.
- **A proxy's `remote_keys`**, its remote's public keys, PEM, one after the other, are
  what a group it is a member of checks its indexes with; a proxy that is not in a
  group does not use them, and apk checks the mirror's signatures itself.

## Groups

A group puts your own repositories and the mirror behind one address, and signs every
index it serves with a key of its own: a machine needs that one key, and nothing else.
The group checks for it what apk would have checked, so a proxy can be a member only if
it has its remote's public keys. Alpine's are on every Alpine machine; on one that has
jq and curl:

```bash
keys=$(cat /etc/apk/keys/*.rsa.pub)
jq -n --arg keys "$keys" '{
  name: "apk-alpine", format: "apk", type: "proxy",
  proxy: {remote_url: "https://dl-cdn.alpinelinux.org/alpine"},
  format_config: {remote_keys: $keys}
}' | curl -u admin -H 'Content-Type: application/json' -d @- \
  http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "apk-public", "format": "apk", "type": "group",
  "group": {"members": ["apk-hosted", "apk-alpine"]}
}' http://localhost:8000/api/v1/repositories
```

On each machine, the group's key, under the name apk finds it by, and the group in
place of Alpine's mirror:

```bash
wget -q -O /etc/apk/keys/megooarti-apk-public.rsa.pub \
  "https://ci:$MEGOOARTI_TOKEN@repo.example.com/repository/apk-public/megooarti-apk-public.rsa.pub"
echo "https://ci:$MEGOOARTI_TOKEN@repo.example.com/repository/apk-public/v3.24/main" \
  > /etc/apk/repositories
```

- **The group serves an index in each directory where a member has one**: a hosted
  member where it holds packages, a proxy where its remote has `APKINDEX.tar.gz`.
- **A directory one member has** is that member's index, its records as the member
  wrote them, signed again with the group's key.
- **A directory several members have** gets an index of the group's own: the members'
  records in their order, and of a name and version (the file apk asks for), the first
  member's alone. Packages are asked of the members in order, as in any group, so a
  package's file must be the same in every member that has it.
- **A member is checked before it is used**: a proxy's index must be signed by one of
  its `remote_keys` (with SHA-1 or SHA-256, as `abuild-sign` signs). A member that
  fails is left out, it is logged, and the proxy's page says why as its last error
  until the proxy next reaches its remote. While a member the last index had cannot be
  checked, that index is kept a minute longer, and the group then tries again.
- **The index is written again when a member's changes**, behind the requests: a
  machine is given the last one meanwhile, and waits only the first time. One index
  of a directory is written at a time.
- **The group's key** is made the first time it is needed, and is at
  `/repository/<group>/megooarti-<group>.rsa.pub`, as a hosted repository's is.

## Clients

Tested with apk on Alpine Linux 3.24 and 3.23 (apk-tools 3.0): a package built with
`abuild`, uploaded and installed from a hosted repository; an index signed with a key
apk was not given, refused; a package from Alpine's mirror, installed through a proxy;
and both through a group, with the group's key the only one apk has, and a member
signed by a key it was not given left out.
