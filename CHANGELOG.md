# Changelog

## 0.1.0

The first version.

### What there is

- **Repositories** of five formats, each hosted, a proxy or a group: Maven, npm, PyPI,
  Docker (an OCI registry, by path, with no port of its own for a repository) and
  Raw. Tested with the formats' own clients: Maven, Gradle and sbt; npm, pnpm and
  Yarn; pip, uv, Poetry and twine; Docker and skopeo.
- **Proxies** that cache, check again after a time you set, remember what the remote
  does not have, and leave a remote alone for a while after it fails. **Groups** that
  keep the names published here from being taken over by a public package of the
  same name.
- **Users, roles and permissions** by format, repository and action; API tokens that
  can be limited and can expire; anonymous access.
- **Browsing, search, upload and delete** without a package client, through the API
  and the web UI.
- **A web UI** for all of it, usable by keyboard, in light and dark, that fetches
  nothing from another host.
- **Blob stores** on the file system, with identical content stored once.
- **Docker Compose** for the whole installation, a database migrated at start, and
  scripts that back it up and restore it.

### For callers of the API

- A hosted Maven repository for releases that is made without a deployment policy
  refuses to replace a version (`disable_redeploy`). Every other hosted repository
  allows it. Name the policy to choose.
- `PUT /api/v1/users/{id}/password` refuses the caller's own account
  (`409 own_password`). One's own password is changed at `PUT /api/v1/me/password`,
  with the present one.
- Signing in is refused from a page on another site, as every other request that
  changes something is (`403 cross_site_request`).

### For operators

- Nothing starts without `MEGOOARTI_DB_PASSWORD`: see
  [Installation](docs/installation.md).
- The images are built from the sources, by Compose. None is published.
- There is no continuous integration yet: the tests, and the scans of what is
  depended on, are run by hand ([Development](docs/development.md)).

### Known issues

- **Under many clients at once, answers are slow.** With a hundred clients asking for
  cached metadata at once, an answer takes about half a second at the median and two
  to three seconds for the slowest twentieth, on a four-core machine. The backend is
  one process, and finds out who is calling anew for every request.
- **An administrator's open session is enough to make another administrator or an API
  token.** Neither asks for the password again.
- **A group answers "not found" when a member's remote could not be asked** (except a
  Docker group). A connection that could not be made is tried three times first.
- **In the web UI:**
  - at 1024 pixels of width the navigation takes three rows;
  - a notification covers the buttons under it for a few seconds;
  - a proxy's page does not say that saving it clears what it last met at its remote;
  - the hint under a proxy's secret says it may be left empty also after the kind of
    sign-in was changed, when the server will ask for it again;
  - long names break every few characters in a narrow window.
- **Not in this version:** `npm audit`; PyPI's JSON index and yanking on a hosted
  repository; Docker's referrers API and mounting a layer from another repository;
  blob stores other than the file system; signing in through LDAP or OIDC.
