# YUM repositories

What is true of every repository is in [Repositories](../repositories.md). This is
what is this format's own: RPM packages, for Fedora, Rocky Linux, RHEL and their kin,
installed with dnf.

A hosted repository holds the `.rpm` files you build, and writes and signs their
metadata with a key of its own. Its `repodata_depth` says where the metadata is: at 0,
one `repodata/` at the root for every package; at 2, as here, one in each directory
two levels down, for the packages under it, so that one repository can hold a
directory for each release and architecture:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "yum-hosted", "format": "yum", "type": "hosted",
  "format_config": {"repodata_depth": 2}
}' http://localhost:8000/api/v1/repositories

curl -u ci --upload-file megooarti-hello-1.0-1.noarch.rpm \
  https://repo.example.com/repository/yum-hosted/el10/x86_64/
```

On each machine that installs from it, as root: the repository's public key, and the
repository itself, with the account dnf signs in with. `repo_gpgcheck=1` has dnf check
the repository's signature of its metadata; `gpgcheck` is for the packages' own, and is
`1` only if you sign them.
The repository's page in the web UI gives these commands with its own address, under
"Set up a machine".

```bash
curl -fsS -u ci -o /etc/pki/rpm-gpg/megooarti.asc \
  https://repo.example.com/repository/yum-hosted/public.key
cat > /etc/yum.repos.d/megooarti.repo <<EOF
[megooarti]
name=MegooArti
baseurl=https://repo.example.com/repository/yum-hosted/el10/\$basearch
username=ci
password=$MEGOOARTI_TOKEN
repo_gpgcheck=1
gpgcheck=0
gpgkey=file:///etc/pki/rpm-gpg/megooarti.asc
EOF
chmod 600 /etc/yum.repos.d/megooarti.repo

dnf install megooarti-hello
```

A proxy caches a distribution's mirror: its remote is the directory where
`repodata/repomd.xml` is, and dnf goes on checking the distribution's own signatures
of its packages, with the keys it already has:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "yum-rocky", "format": "yum", "type": "proxy",
  "proxy": {"remote_url": "https://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os"}
}' http://localhost:8000/api/v1/repositories

cat > /etc/yum.repos.d/rocky-baseos.repo <<EOF
[baseos]
name=Rocky Linux BaseOS, through MegooArti
baseurl=https://repo.example.com/repository/yum-rocky
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10
EOF
```

For Fedora, the remote is a mirror's
`.../fedora/linux/releases/44/Everything/x86_64/os` and the key
`/etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-44-primary`. A proxy is of one repository of the
distribution (BaseOS, AppStream, updates, ...): make one for each, and take away the
`metalink=` or `mirrorlist=` lines of the distribution's own `.repo` files, which
would lead dnf past MegooArti.

- **Credentials** go in the `.repo` file, as above: a user name and a password, or a
  user name and an API token. Keep the file readable by root alone.
- **A package is uploaded to the path it is kept at**, with `PUT` (`curl
  --upload-file` to an address ending in `/` adds the file's name), or through the web
  UI or [the API](../api.md#uploading), with a `directory` field and one or more `file`
  fields. The path ends in `.rpm`, is not in a `repodata/` directory, and is at least
  as many directories down as the repository's `repodata_depth`; otherwise it is
  refused with `400 invalid_path`. A file that is not an RPM, and a source RPM, are
  refused with `400 invalid_package`. At most 64 MiB of a package's headers are read,
  and a package may list at most 500,000 files and dependencies.
- **`repodata_depth`** is chosen when the repository is made, from 0 to 5, and fixed
  after. Every directory exactly that deep has a `repodata/`: one without packages has
  an empty one, so a machine can be set up before anything is uploaded for it.
- **A package's version** is its name and `epoch:version-release`, the epoch only when
  it is not 0: that is what the web UI shows, and what `dnf install` is given
  (`dnf install megooarti-tool-2:0.3-2`). Each architecture's file is one file of it.
- **Uploading a package again** to the same path follows the deployment policy. With
  `disable_redeploy` it answers `409`.
- **The metadata is written from the packages**: `primary.xml`, `filelists.xml` and
  `other.xml` (the ten newest changelog entries), packed with gzip and named by their
  hash, as `createrepo_c` writes them, and `repomd.xml`, which names them and is signed
  as `repomd.xml.asc`. It is written once after each change and kept in memory until
  the next. Writing it takes time in proportion to the whole repository, and the
  first request after a change waits for it: about twenty seconds for 30,000
  packages. The files the `repomd.xml` before the last change named are kept as well,
  for a machine that read it a moment before. A client is sent `repomd.xml` again
  unless it has the same bytes (`If-None-Match`): two changes within one second have
  the same date.
- **The signing key** is made the first time it is needed: an Ed25519 OpenPGP key that
  never expires. `GET /api/v1/repositories/<name>/signing-key` shows it, and
  `POST /api/v1/repositories/<name>/signing-key/generate` (with
  `{"algorithm": "rsa4096"}` for an RSA key) or `PUT` of an armoured private key in
  `private_key` replaces it, for whoever holds `admin:repositories:write`. From then on
  the metadata is signed with the new key only: every machine must fetch the new
  `public.key`. The private key is kept sealed with the installation's secret key, and
  is never shown; the repository's settings page in the web UI shows the key, with its
  public key to download, and replaces it after asking. MegooArti signs the metadata,
  not the packages: sign those with
  `rpmsign` before uploading them if machines are to check them (`gpgcheck=1`).
- **Deleting** a package (`DELETE` on its address) takes it out of the metadata at
  once.
- **A proxy**'s `repodata/repomd.xml` (and its signature, if the remote has one) is
  checked again with the remote after `metadata_max_age_minutes`; the files it names
  carry their hash in their names, and are kept, as packages are. A metalink or a
  mirror list is not proxied.
- **A proxy's `remote_keys`**, its remote's public keys, armoured, are what a group it
  is a member of checks its `repomd.xml` with. They are optional: Rocky Linux signs its
  repositories' `repomd.xml`, Fedora does not.

## Groups

A group puts your own repositories and the mirrors behind one address, and signs the
metadata it serves with a key of its own: a machine needs that one key for the
metadata, and dnf goes on checking each package's own signature where `gpgcheck=1`.
Give a proxy of a distribution that signs its metadata its keys, and the group checks
them for the machines. For Rocky Linux's, on a machine that has them and jq:

```bash
keys=$(cat /etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10)
jq -n --arg keys "$keys" '{
  name: "yum-rocky", format: "yum", type: "proxy",
  proxy: {remote_url: "https://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os"},
  format_config: {remote_keys: $keys}
}' | curl -u admin -H 'Content-Type: application/json' -d @- \
  http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "yum-public", "format": "yum", "type": "group",
  "group": {"members": ["yum-flat", "yum-rocky"]}
}' http://localhost:8000/api/v1/repositories
```

Here `yum-flat` is a hosted repository at depth 0, whose packages are signed with
`rpmsign --addsign` and a key of yours, `megooarti-packages.asc`. On each machine,
the group's key, the keys of the packages, and the group:

```bash
curl -fsS -u ci -o /etc/pki/rpm-gpg/yum-public.asc \
  https://repo.example.com/repository/yum-public/public.key
cat > /etc/yum.repos.d/megooarti.repo <<EOF
[megooarti]
name=MegooArti
baseurl=https://repo.example.com/repository/yum-public
username=ci
password=$MEGOOARTI_TOKEN
repo_gpgcheck=1
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/yum-public.asc file:///etc/pki/rpm-gpg/megooarti-packages.asc
  file:///etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10
EOF
```

**Check every package where a member is not checked.** The group checks a member's
metadata as far as its remote signed it, and no further: a proxy without
`remote_keys` (one of Fedora, whose mirrors do not sign their metadata) is taken as
its remote served it, and the group's signature then vouches for whatever came over
the network. With such a member every machine must check each package's own
signature (`gpgcheck=1`, with the distribution's key and your packages' key), and
the remote is best reached over HTTPS. `gpgcheck=0` is enough only for a group whose
every proxy has `remote_keys`, and whose hosted members hold your own packages.

- **The group serves a `repodata/` in each directory where a member has one**: a
  hosted member in a directory as deep as its `repodata_depth` that holds packages, a
  proxy where its remote has `repodata/repomd.xml`.
- **A directory one member has** is that member's: its `repomd.xml`, signed again with
  the group's key, and every file it names sent on from that member. dnf checks each
  against that `repomd.xml`.
- **A directory several members have** (a hosted repository at depth 0 beside a proxy
  of Rocky's BaseOS, both at the root, as above) gets `primary.xml`, `filelists.xml`
  and `other.xml` of the group's own, written from the members' and packed with zstd.
  A package (the same name, epoch, version, release and architecture) that an earlier
  member has is left out of a later one's, and so is a later member's package at a
  path an earlier one holds with another package. Package groups (comps), updates
  (updateinfo) and modules are not merged: the group names those of its first member
  that has them, as that member gave them. The members' databases (`*.sqlite`) and
  zchunk files are not named; dnf reads the XML.
- **A member is checked before it is used**: every file the group reads of it must
  have the checksum its `repomd.xml` names, and a proxy given `remote_keys` must have a
  `repomd.xml.asc` that one of them made. A member that fails is left out, it is
  logged, and the proxy's page says why as its last error until the proxy next
  reaches its remote. While a member the last metadata had cannot be checked, that
  metadata is kept a minute longer, and the group then tries again.
- **The metadata is written again when a member's changes**, behind the requests: a
  machine is given the last one meanwhile, and waits only the first time. The first
  time takes as long as fetching the mirror's metadata and merging it: for Fedora's
  whole release, 70 MB to fetch and about 17 seconds to merge with its updates. That
  is longer than dnf waits for an answer, so ask for the group's `repomd.xml` once
  (`curl -u ci https://repo.example.com/repository/yum-public/repodata/repomd.xml`)
  before the machines do. A directory is written by one request at a time, and
  the others are given the last one meanwhile.
- **What is merged is kept in memory**: about 120 MB for a directory of Fedora's
  release and updates, and twice that for a while after a change, as the files the
  last `repomd.xml` named are kept too. What every group keeps is at most 256 MiB,
  the least recently used going first: a second such directory pushes the first
  out, and the next request for it waits for it to be merged again.
- **A proxy member that seems behind its remote is asked again**: where its
  signature does not fit its `repomd.xml`, or a file it names is gone or not what
  it says, the group fetches its `repomd.xml` and signature again, however new its
  copies, before it leaves the member out.
- **Packages** are asked of the members in order, as in any group. A package's path
  must therefore be the same file in every member that has it.
- **The group's key** is made the first time it is needed, and is at
  `/repository/<group>/public.key`, as a hosted repository's is.

## Clients

Tested with dnf on Fedora 44 (dnf5) and Rocky Linux 10 (dnf 4): a package built with
`rpmbuild`, uploaded two directories down and installed from a hosted repository with
`repo_gpgcheck=1`; metadata signed with a key dnf was not given, refused; a package
from each distribution's mirror, installed through a proxy; and through groups: ours
and the mirror's merged in one directory, a directory one member has, and, on Rocky
Linux, a proxy given a key Rocky does not sign with left out.
