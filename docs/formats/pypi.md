# PyPI repositories

What is true of every repository is in [Repositories](../repositories.md). This is
what is this format's own.

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-hosted", "format": "pypi", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"}
}' http://localhost:8000/api/v1/repositories
```

Upload to the repository's address, with the slash at its end, and install from
`simple/` beneath it:

```bash
twine upload --repository-url https://repo.example.com/repository/pypi-hosted/ \
  -u __token__ -p "$MEGOOARTI_TOKEN" dist/*
uv publish --publish-url https://repo.example.com/repository/pypi-hosted/ --token "$MEGOOARTI_TOKEN"

pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-hosted/simple/ my-package
```

A proxy caches pypi.org, and a group puts your own packages and the public ones behind
one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-proxy", "format": "pypi", "type": "proxy",
  "proxy": {"remote_url": "https://pypi.org"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-public", "format": "pypi", "type": "group",
  "group": {"members": ["pypi-hosted", "pypi-proxy"]}
}' http://localhost:8000/api/v1/repositories
```

Install through the group, and upload to the hosted repository:

```bash
pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-public/simple/ my-package
uv pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-public/simple/ my-package
```

For Poetry, name the group as the project's primary source and give it the token:

```toml
[[tool.poetry.source]]
name = "megooarti"
url = "https://repo.example.com/repository/pypi-public/simple/"
priority = "primary"
```

```bash
poetry config http-basic.megooarti __token__ "$MEGOOARTI_TOKEN"
```

- **Credentials** are HTTP Basic: a user name and password, a user name and a token, or
  `__token__` and a token. A token in the place of the user name
  (`https://<token>@host/`) is refused.
- **A project's page is generated** on every request from the files stored, so it is
  right after a delete and after two uploads at the same moment. It is the HTML index
  of PEP 503, with each file's `sha256` and the Python versions it requires.
- **Every spelling of a name is one project**: `My_Package`, `my.package` and
  `my-package` are stored and listed as `my-package`.
- **An upload is streamed to disk** as it arrives, whatever its size, and is checked
  against the `sha256` and `md5` digests the client sends. Wheels (`.whl`) and source
  distributions (`.tar.gz`, `.zip`) are taken; the file's name must fit its project.
  `poetry publish` sends the same request as twine, and is tested too.
- **A file name has one address in its project**, whatever version an upload declares
  for it: `packages/<project>/<version in the file name>/<file name>`.
- **Uploading a file again** follows the deployment policy. With `disable_redeploy` it
  answers `409`. `uv publish --check-url <index address>` passes over files that are
  already there; give that address its credentials, because uv does not send the
  token to it. twine's `--skip-existing` works only with pypi.org.
- **Permissions.** Uploading a new file needs `add`, replacing one `edit`, and deleting
  one (`DELETE` on its address under `packages/`) `delete`.
- Signatures sent with an upload are not kept. The JSON index (PEP 691) and yanking a
  release on a hosted repository are not available yet; pip, uv and Poetry do not
  need them.
- **A proxy** keeps the remote's page for each project and writes its own from it,
  with every link pointed at MegooArti, so files are downloaded through it and cached.
  The remote's marks for yanked files, required Python versions and metadata files
  (PEP 658) are passed on, and the metadata files themselves are fetched and cached
  like any file. A project's page is checked again with the remote after
  `metadata_max_age_minutes`. A file, once cached, is not asked about again until
  the proxy's cache is invalidated; it is then checked against the page once more.
- **The remote address** of a proxy is the index's root (`https://pypi.org`), or the
  index itself if the address ends in `/simple` (or devpi's `/+simple`).
- **A proxy fetches each file from the address the remote's page gives for it**, which
  for pypi.org is another host. If the page gives a `sha256`, `sha512`, `sha1` or
  `md5` hash for the file, the file must match it, or it is not kept (`502`); a file
  the page gives no such hash for is kept unchecked and listed without one. The
  remote's credentials are sent only to the remote's own scheme, host and port. A
  file address that is not on the public internet (loopback, link-local, private,
  however the address is written) is refused unless the remote itself is at that
  host. Host names are not resolved for this check: network egress rules are the
  complete defence.
- **A group protects the names you upload.** If a hosted member holds a project, only
  hosted members answer for it, for its page and its files alike: a project on the
  public index with the same name as one of yours cannot add a file to it or stand in
  for one (the dependency-confusion attack). While that hosted repository is offline
  the group answers `503` for the project. A name is protected while a hosted
  repository holds a file of it.
- **A group lists a project once**, from all the hosted members that hold it, or from
  all the proxies that have it. A file name two members list is taken from the earlier
  one.
- The root index (`simple/`) of a proxy lists the projects it has cached a file of,
  not the remote's; a group lists those of all its members.
- **Clients.** Installs are tested with pip, uv and Poetry; uploads with twine,
  `uv publish` and `poetry publish`.

Reading through a group needs `read` on the group only, for example
`repository:pypi:pypi-public:read`.
