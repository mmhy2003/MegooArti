# npm repositories

What is true of every repository is in [Repositories](../repositories.md). This is
what is this format's own.

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-hosted", "format": "npm", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"}
}' http://localhost:8000/api/v1/repositories
```

Point npm at it and sign in. `npm login` asks for a user name and a password, and
MegooArti answers with a personal API token, which npm keeps in `~/.npmrc`:

```bash
npm config set registry https://repo.example.com/repository/npm-hosted/
npm login --auth-type=legacy
npm publish
```

In a pipeline, skip `npm login` and give npm a token directly:

```ini
registry=https://repo.example.com/repository/npm-hosted/
//repo.example.com/repository/npm-hosted/:_authToken=${NPM_TOKEN}
```

A proxy caches the public registry, and a group puts your own packages and the public
ones behind one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-proxy", "format": "npm", "type": "proxy",
  "proxy": {"remote_url": "https://registry.npmjs.org"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-public", "format": "npm", "type": "group",
  "group": {"members": ["npm-hosted", "npm-proxy"]}
}' http://localhost:8000/api/v1/repositories
```

Install through the group and publish to the hosted repository. In `.npmrc`:

```ini
registry=https://repo.example.com/repository/npm-public/
//repo.example.com/repository/npm-public/:_authToken=${NPM_TOKEN}
//repo.example.com/repository/npm-hosted/:_authToken=${NPM_TOKEN}
```

and in the `package.json` of each package you publish:

```json
"publishConfig": {"registry": "https://repo.example.com/repository/npm-hosted/"}
```

- **Signing in** accepts a password, or an API token in place of the password. Each
  sign-in with a password creates a token named `npm login` and the time; it is listed
  with your other tokens and can be revoked there. `npm logout` revokes it. Failed
  attempts are limited as for any sign-in.
- **The package document is generated** on every request from the versions stored, so
  it is right after an unpublish and after two publishes at the same moment.
- **A published tarball is checked** against the `shasum` and `integrity` in its
  manifest. A publish that does not match is refused.
- **Publishing a version again** follows the deployment policy. Use `disable_redeploy`
  to get npm's own rule that a version is published once.
- **Dist-tags.** `latest` is the highest version if the version it named is removed.
- **`npm deprecate` and `npm unpublish` act on the package as it is now.** If someone
  published in between, they answer `409`; run the command again.
- **Permissions.** `npm publish` needs `add`. `npm deprecate` needs `edit`.
  `npm unpublish` needs `delete`, and `add` or `edit` as well when it removes a single
  version, because npm does that by sending the package document back.
- **A publish is read into memory**, up to `MEGOOARTI_NPM_MAX_PUBLISH_BYTES`.
- **Search** (`npm search`) finds the packages a repository holds, by name: at a proxy
  the packages it has cached, at a group those of all its members.
- `npm audit` is not supported; installs do not need it.
- **A proxy** caches what it fetches. It serves the remote's package document with the
  tarball links pointed at MegooArti, so tarballs are downloaded through it and cached
  too. A package document is checked again with the remote after
  `metadata_max_age_minutes`; a tarball after `content_max_age_minutes`.
- **A group protects the names you publish.** If a hosted member holds a package, only
  hosted members answer for it, for its document and its tarballs alike. A package on
  the public registry with the same name as one of yours cannot add a version to it or
  stand in for one (the dependency-confusion attack). While that hosted repository is
  offline the group answers `503` for the package; it does not fall back to the public
  one. To use your own build of a public package beside the public versions, publish
  it under a scope.
- **A group merges** what its hosted members hold of a package, the earlier member
  winning a version or a dist-tag both have. A package only proxies have is served
  from the proxy that has it. If several proxies have it their documents are merged in
  the members' order while they fit in 16 MiB together; the first that does not fit,
  and those after it, are left out. Merging is done again for every request, so list
  each registry once: do not add a proxy of a registry that another proxy's remote
  already includes.
- **A name is protected while a hosted repository holds a version of it.**
  Unpublishing the last version gives the name back to the proxies.
- **Signing in works at every npm repository**, so `npm login` can point at the group.
  `npm publish`, `npm dist-tag`, `npm deprecate` and `npm unpublish` work at a hosted
  repository only.
- **Set the base URL** under `/api/v1/settings` when clients reach MegooArti through a
  reverse proxy. Tarball links in package documents are built on it; without it they
  follow the address of each request.
- **Clients.** Installs are tested with npm, pnpm and Yarn 1. Yarn 1 sends a token for
  an unscoped package only if `.npmrc` also says `always-auth=true`.

Reading through a group needs `read` on the group only, for example
`repository:npm:npm-public:read`.
