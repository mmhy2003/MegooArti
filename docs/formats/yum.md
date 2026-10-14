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
  "proxy": {"remote_url": "http://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os"}
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
  refused with `400 invalid_package`. At most 64 MiB of a package's headers are read.
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
  the next. The files the `repomd.xml` before the last change named are kept as well,
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
  is never shown. MegooArti signs the metadata, not the packages: sign those with
  `rpmsign` before uploading them if machines are to check them (`gpgcheck=1`).
- **Deleting** a package (`DELETE` on its address) takes it out of the metadata at
  once.
- **A proxy**'s `repodata/repomd.xml` (and its signature, if the remote has one) is
  checked again with the remote after `metadata_max_age_minutes`; the files it names
  carry their hash in their names, and are kept, as packages are. A metalink or a
  mirror list is not proxied.

## Clients

Tested with dnf on Fedora 44 (dnf5) and Rocky Linux 10 (dnf 4): a package built with
`rpmbuild`, uploaded two directories down and installed from a hosted repository with
`repo_gpgcheck=1`; metadata signed with a key dnf was not given, refused; and a
package from each distribution's mirror, installed through a proxy.
