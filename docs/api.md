# The API

Everything the web UI does, it does through the REST API under `/api/v1`, and so can
anything else. Its reference, with every address, field and answer, is the
installation's own page at `/api/docs`, drawn from the description at
`/api/v1/openapi.json`. This guide says what is true of all of it, and how the
repositories are looked at, added to and searched without a package client.

The repositories themselves are not under `/api`: package clients reach them at
`/repository/<name>/`, and container clients at `/v2/`. The guide of each format says
how.

A change that would break a caller of `/api/v1` is made under a new version, with the
old one kept for a while.

## Who is calling

- **HTTP Basic**, with a user name and a password, or with an API token in the place
  of the password: `curl -u ci:mga_...`. The name `__token__`, or no name, stands for
  whoever the token belongs to.
- **A bearer token**: `Authorization: Bearer mga_...`.
- **A session**, as the web UI has: `POST /api/v1/auth/login` with a user name and a
  password sets a cookie and answers with a `csrf_token`. A request that uses the
  cookie and changes anything must send that token in an `X-CSRF-Token` header.
  `GET /api/v1/auth/session` says who the caller is, and never answers `401`.

A request with no credentials acts as the `anonymous` user if anonymous access is on.
`401` is the answer to a caller who is not known, and `403` to one who is known and
may not. API tokens are made at `/api/v1/me/tokens`, or in the web UI under Account,
by a caller who signed in with a password: a token can neither make a token nor
change a password (`403 interactive_auth_required`).

Signing in with a password is limited. After five failures for one user name, or
from one address, within fifteen minutes, the answer is `429 too_many_attempts` with
a `Retry-After` header, whatever the password. A token is not refused by this.

## Errors

Every error the API answers with has one shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request is not valid.",
    "details": [{"field": "body.name", "message": "String should match pattern ..."}],
    "request_id": "0d0f6d1e7b0e4f6f9f1f2f3f4f5f6f70"
  }
}
```

- **`code`** is for a program: it does not change with the wording. **`message`** is
  for a person.
- **`details`** names the fields of a request that were refused, where there are any
  (`422 validation_error`): a field of the body as `body.<field>`, a parameter of
  the address as `query.<name>` or `path.<name>`, or a field by its own name where it
  was refused for what it would do and not for how it is written.
- **`request_id`** is also in the `X-Request-ID` header of every answer, and in the
  server's log lines for the request. A caller may send its own in that header: 1 to
  64 letters, digits, `.`, `_` or `-`. Anything else is replaced by one of the
  server's.
- **An answer that is not the API's** does not have this shape. When the backend is
  not running, or does not answer in time, what stands in front of it answers in its
  own way: the gateway of the Compose file with `502` or `504` and a page of HTML.
  Where the body is not JSON, go by the status.
- Under `/v2/`, errors have the registry API's own shape, which container clients
  show.

## Lists

A list is read a page at a time: `limit` (1 to 200, 50 if it is not given) and
`offset`. The answer has the `items`, and the `total` there are:

```json
{"items": [], "total": 0, "limit": 50, "offset": 0}
```

A folder of a repository is the exception. It can hold millions of entries, so it has
no total: each answer has a `next` to give as `after` in the following request.

## Browsing and deleting

What the repositories hold can be looked at and removed without a package client,
through `/api/v1/content`. It is what the web UI uses.

```bash
# The repositories you may browse, and one of them
curl -u alice https://repo.example.com/api/v1/content
curl -u alice https://repo.example.com/api/v1/content/maven-releases

# A folder, a file, and the components (packages and their versions)
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/tree?path=com/acme'
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/asset?path=com/acme/app/1.0/app-1.0.jar'
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/components?namespace=com.acme&name=app'

# Delete a file, a component, or everything under a folder
curl -u alice -X DELETE 'https://repo.example.com/api/v1/content/maven-releases/asset?path=com/acme/app/1.0/app-1.0-sources.jar'
curl -u alice -X DELETE https://repo.example.com/api/v1/content/maven-releases/components/<id>
curl -u alice -X DELETE 'https://repo.example.com/api/v1/content/maven-releases/tree?path=com/acme/app'
```

- **Seeing needs `browse`** on the repository, and downloading needs `read`. Deleting
  through this API needs `browse` and `delete`, and nothing else: not the right to
  publish. The list leaves out what you may not browse, and a group names only the
  members you may browse.
- **A folder** (`tree`) lists what is directly in it, in the byte order of the names,
  each entry a `folder` or a `file`. It is read a page at a time: give the `next` of
  one answer as `after` in the following request. There is no total, because a
  folder can hold millions of entries and counting them would mean reading them. An
  empty `path` is the root, and `limit` is at most 200. A name that is both a file and
  a folder is listed as each.
- **A file** (`asset`) is described with its size, content type, four checksums, blob
  store, who stored it and when, when it was last downloaded, the component it
  belongs to, and the address to download it from.
- **A component** is a package version: a Maven artifact version, an npm package
  version, a PyPI release, a Docker tag. In a Raw repository every file is one.
  `components/<id>` lists its files.
- **How to use a component** is part of its detail: `usage` is a list of snippets,
  each with a `label`, the `language` it is written in (`xml`, `kotlin`, `groovy` or
  `shell`) and the `text` to copy. Maven gets a `<dependency>` and a line for Gradle
  in Kotlin and in Groovy, npm `npm install <name>@<version> --registry=<address>`,
  PyPI `pip install --index-url <address>simple/ <name>==<version>`, a Docker tag
  `docker pull <host>/<repository>/<image>:<tag>`. The address is the repository's
  public one (the `base_url` setting, if it is set). A Raw file has no snippet: it has
  its `download` address. Nor has a component whose name or version holds anything
  but letters, digits and `. _ + ~ / -`, or does not begin with a letter, a digit or
  `_`: the text is there to be pasted into a shell or a build file, and a name is
  chosen by whoever deployed it.
- **Deleting goes through the format**, so the repository is left as the format's own
  client would leave it. A deleted npm tarball is an unpublished version, and
  dist-tags that named it move. A deleted Docker manifest takes its tags and the
  layers nothing else uses with it; a deleted tag goes alone. Maven's metadata and
  checksums and PyPI's pages are computed from the files, so they follow by
  themselves.
- **What a format keeps for itself cannot be deleted on its own** (`409
  managed_by_format`): an npm package's dist-tags, a Docker layer that an image uses.
- **Deleting a folder** removes the files under it through the same rules, at most
  1,000 in one request. The answer says how many of them were `deleted` (what went
  with them, such as the tags and layers of a Docker manifest, is not counted), how
  many were `skipped` because the format keeps them, and gives a `next` to repeat the
  request with, as `after`, while there may be more. The root of a repository cannot
  be deleted this way.
- **An offline repository** can still be browsed, deleted from and uploaded to here.
  Being offline stops package clients, not the people who tend the repository.
- **A proxy** is browsed for what it has cached, and deleting from it removes the
  cached copy: it is fetched again when it is next asked for.
- **A group** holds nothing of its own. It lists its `members`, which are browsed one
  by one.

## Uploading

A file can be put into a hosted repository without a package client: one
`multipart/form-data` request to `/api/v1/content/<repository>/upload`, with the
fields its format needs.

```bash
# Raw: files into a directory, each under its own name
curl -u alice -F directory=docs/v1 -F file=@guide.pdf -F file=@logo.png \
  https://repo.example.com/api/v1/content/files/upload

# Maven: an artifact by its coordinates. A POM is written for it
curl -u alice -F group=com.acme -F artifact=app -F version=1.0 \
  -F file=@app.jar -F file.sources=@app-sources.jar \
  https://repo.example.com/api/v1/content/maven-releases/upload

# npm: the tarball that `npm pack` writes
curl -u alice -F file=@tool-1.0.0.tgz https://repo.example.com/api/v1/content/npm-hosted/upload

# PyPI: wheels and source distributions
curl -u alice -F file=@greeter-1.0-py3-none-any.whl -F file=@greeter-1.0.tar.gz \
  https://repo.example.com/api/v1/content/pypi-hosted/upload
```

| Format | Fields | Files |
| --- | --- | --- |
| Raw | `directory` (the root without it) | One or more `file`, each stored in the directory under its own name |
| Maven | `group`, `artifact`, `version`; `packaging` (default `jar`); `generate_pom` (default `true`) | `file` for the artifact, `file.<classifier>` for a file beside it (`file.sources`), `pom` for its POM |
| npm | `tag` (default `latest`) | One `file`: a package tarball. Its `package.json` says the name and the version |
| PyPI | `summary`, `requires_python`, `keywords`, each optional and said of every file | One or more `file`: wheels and source distributions (`.whl`, `.tar.gz`, `.zip`) |

- **The answer** is `201` with the `files` that were stored, each described as `asset`
  describes a file, and the `components` they belong to.
- **All or nothing.** If one file of a form is refused, none of them is stored, in
  the repository or in the blob store.
- **Permissions and policy are those of any upload:** `add` for a new file, `edit` to
  replace one, and the repository's deployment policy. Uploading needs no right to
  browse or to read.
- **A file must be sent as a file**, with a file name: `-F file=@app.jar`, not
  `-F file=app.jar`. A field the format does not know is refused, so a misspelt one
  is not silently ignored.
- **Maven.** The files go where a deploy would put them, and checksums and
  `maven-metadata.xml` follow by themselves. What a file is (`jar`, `war`, `tar.gz`,
  `jar.asc`) is read from the end of its own name; the rest of its name does not
  matter. Without a POM, one is written that says the group, artifact, version and
  packaging: enough for a build that depends on the artifact. None is written if the
  form sends one, if the version already has one, or with `generate_pom=false`. The
  repository's version policy applies. A snapshot (`1.0-SNAPSHOT`) is not uploaded: a
  build deploys it, and numbers it as it does. A checksum file (`.sha1`, `.md5`) is
  refused: checksums are computed from the files.
- **npm.** What is stored is what `npm publish` would store: the tarball, and the
  `package.json` inside it as the version's manifest. A package whose `package.json`
  says `"private": true` is refused, as npm refuses to publish it. The tarball may be
  as large as a publish may be (`MEGOOARTI_NPM_MAX_PUBLISH_BYTES`), and is read into
  memory to find its `package.json`, which must be among its first 100,000 files and
  256 MiB. Every other upload goes to the blob store as it arrives.
- **PyPI.** A file's name says its project and version. A source distribution's is
  read as the project, a hyphen and the version, so its version must be written
  without a hyphen (`1.0.post1`, not `1.0-1`), as current build tools write it. What
  the form does not say of a release that exists, its summary and keywords, stays as
  it was. `requires_python` is kept with each file and is not read out of it: give it
  for a package that needs a certain Python, or installers will offer the file to all.
- **Docker images are pushed** with a container client. A Docker repository, a proxy
  and a group answer `409 upload_not_supported`.
- **A form that cannot be used** answers `422 validation_error`, and its `details`
  name the field. A file that is not what its format takes answers as that format's
  own upload does (`400 invalid_package`, `400 version_policy_violation`,
  `400 invalid_path`).

## Search

`/api/v1/search` finds components in every repository you may browse.

```bash
curl -u alice 'https://repo.example.com/api/v1/search?q=commons+lang'
curl -u alice 'https://repo.example.com/api/v1/search?format=maven&namespace=com.acme&name=app*'
curl -u alice 'https://repo.example.com/api/v1/search?sha1=2ef7bde608ce5404e97d5f042f95f89f1c232871'
```

- **`q`** is matched as it reads: each word must be contained in the component's
  group, name or version, or in the words its format adds, whatever the case. `*`
  stands for anything; every other character is itself. At most ten words are looked
  at. Results are in the order of their names by bytes (capitals first), not ranked.
- **What a format adds:** for Maven `group:artifact:version` as one word; for npm
  `@scope/name` and the keywords and description of `package.json`; for PyPI the
  summary and keywords of the upload; for Docker `image:tag`. In a Raw repository a
  file is found by its folder and name. What a proxy has cached is found by its name
  and version only: descriptions and keywords are those of packages published here.
- **`namespace`, `name` and `version`** match a whole value, whatever the case, with
  `*` for anything: `name=commons*`. The namespace is a Maven group, an npm scope
  (without the `@`), a Raw file's folder.
- **`md5`, `sha1`, `sha256`, `sha512`** find the components that have a file with
  exactly that checksum, written as tools print it: in either case, and with or
  without its name in front (`sha256:...`).
- **`format` and `repository`** narrow where to look. With nothing given, everything
  you may browse is listed, a page at a time (`limit`, `offset`).
- Each result names its `repository` and has an `id`, which opens at
  `/api/v1/content/<repository>/components/<id>`.
- A Docker manifest without a tag is not found: tags are. A group is not searched;
  what is behind it is.
- **Rebuilding an index** of a repository, after an upgrade that asks for it, is in
  [Upgrading](upgrade.md#after-an-upgrade).
