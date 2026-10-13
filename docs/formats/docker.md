# Docker repositories

What is true of every repository is in [Repositories](../repositories.md). This is
what is this format's own.

MegooArti is a container registry for Docker, Podman and containerd. A Docker
repository is not used under `/repository/`: container clients speak to `/v2/` at the
root of a host, and the first part of an image's name says which repository it is in.
A Docker repository's name therefore has to be one a container client can write:
lower-case letters and digits, with single `.`, `_` or `-` between them.

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-hosted", "format": "docker", "type": "hosted"
}' http://localhost:8000/api/v1/repositories

docker login repo.example.com
docker tag my-app:1.0 repo.example.com/docker-hosted/team/my-app:1.0
docker push repo.example.com/docker-hosted/team/my-app:1.0
docker pull repo.example.com/docker-hosted/team/my-app:1.0
```

- **HTTPS.** Container clients refuse plain HTTP to every host but `localhost`, so
  put MegooArti behind HTTPS for clients on other machines. The registry has to be at
  the root of its host: a deployment under a path prefix cannot serve Docker. Behind a
  reverse proxy, set the base URL under `/api/v1/settings`: it is where clients are
  sent to sign in.
- **Signing in.** `docker login` takes a user name with a password or with an API
  token. The client is then given a registry token that lasts five minutes, and
  fetches a new one by itself. Disabling a user or revoking an API token takes effect
  at once; a changed password within five minutes. Tools that send HTTP Basic
  credentials or an API token with every request are accepted too. A registry token
  is taken under `/v2/` only: it cannot be used on the rest of the API.
- **Permissions.** Pulling needs `read`. Pushing needs `read` and `add`, because a
  client first asks which layers are already there; moving a tag needs `edit` as
  well, and deleting needs `delete`. For example
  `repository:docker:docker-hosted:read`.
- **Public images.** With anonymous access on, `docker pull` works without
  `docker login` wherever the `anonymous` user may read. Out of the box that is every
  repository, Docker ones included. To make only some public, take the built-in
  `anonymous` role away from the `anonymous` user and give it a role with `read` on
  those repositories, such as `repository:docker:docker-public:read`.
- **Tags that cannot be moved.** With the deployment policy `disable_redeploy`, a tag
  that exists cannot be given to another image (`409`). Pushing the image it already
  names again changes nothing and is accepted.
- **Images for several platforms** are pushed and pulled as one. Docker's and the OCI's
  manifests and manifest lists are taken; the retired schema 1 is not.
- **A layer is stored once** in a repository, however many of its images use it, and
  is not uploaded again. Whoever may read a repository may fetch any layer in it by
  its digest.
- **Uploads are streamed to disk** in the chunks the client sends, whatever the size
  of the layer, and can be resumed. A layer sent in one request, as Docker, containerd
  and Podman send it, is written once; one sent in several is joined when the upload
  completes, and may have at most 10,000 chunks. A layer must match its digest or it
  is not kept.
- **Deleting an image** is done by its digest, and removes the tags that name it and
  the layers nothing else in the repository uses. Deleting a tag removes the tag
  alone: the image can still be pulled by its digest. Docker has no command for
  either, so use the API:

  ```bash
  curl -u admin -I https://repo.example.com/v2/docker-hosted/team/my-app/manifests/1.0
  # Docker-Content-Digest: sha256:...
  curl -u admin -X DELETE https://repo.example.com/v2/docker-hosted/team/my-app/manifests/sha256:...
  ```

- **Cleaning up.** A layer that no image refers to, and an upload that was never
  finished, are removed after a day. A push that stops half-way leaves nothing behind
  for longer than that.
- **Listing.** `GET /v2/_catalog` lists the images you may read as
  `<repository>/<image>`, and `GET /v2/<repository>/<image>/tags/list` an image's tags.
- Errors under `/v2/` have the registry API's own shape, which container clients
  show: `{"errors": [{"code": "...", "message": "..."}]}`.
- Not available: the referrers API (clients fall back to tags), mounting a layer from
  another repository (it is uploaded instead), and deleting a single layer.
- **Clients.** Tested with the Docker client and daemon, whose pushes and pulls go
  through containerd's registry client, and with skopeo, which is built on the image
  library Podman uses.

A proxy is a pull-through cache of another registry:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-hub", "format": "docker", "type": "proxy",
  "proxy": {"remote_url": "https://registry-1.docker.io"}
}' http://localhost:8000/api/v1/repositories

docker pull repo.example.com/docker-hub/alpine:3
docker pull repo.example.com/docker-hub/grafana/grafana:latest
```

- **The remote address** is the registry's own, without `/v2/`: for Docker Hub
  `https://registry-1.docker.io` (not `docker.io` or `hub.docker.com`), or for example
  `https://ghcr.io`, `https://quay.io`, `https://registry.k8s.io`. On Docker Hub an
  image with a one-part name is an official image, so `alpine` is fetched as
  `library/alpine`, as Docker does.
- **Signing in to the remote.** Public registries hand out a token before they serve
  anything, usually from another host. The proxy fetches one, with the user name and
  password (or access token) in `remote_auth` if there is one, and uses it until it
  runs out. The credential is sent to the remote and to the sign-in address the remote
  names, never to the host its layers are downloaded from. A sign-in address must use
  HTTPS if the remote does, and must not be an internal address unless the remote is
  at that host.
- **A tag** is asked about again after `metadata_max_age_minutes`. Only its digest is
  asked for, which registries that count pulls do not count; the image is fetched
  again only if the tag names another one. While the remote cannot be reached, or if
  it has dropped the tag, what is held is served.
- **An image by its digest, and a layer,** are fetched once and checked against the
  digest. What does not match is not kept (`502`). They are never asked about again.
- **A manifest is read before it is kept**, so the proxy knows the layers each image
  uses. A layer that no kept manifest refers to is removed after a day, as on a hosted
  repository, and fetched again if it is asked for.
- **Tags** (`tags/list`) are the remote's, kept for `metadata_max_age_minutes`. The
  catalog lists the images that have been pulled through the proxy.
- An image the remote does not have, or will not show to the proxy's credential, is
  answered `404`. A registry says the same of both.
- Nothing can be pushed to a proxy or deleted from it through the registry API (`405`).

A group puts your own images and the public ones behind one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-all", "format": "docker", "type": "group",
  "group": {"members": ["docker-hosted", "docker-hub"]}
}' http://localhost:8000/api/v1/repositories

docker pull repo.example.com/docker-all/team/my-app:1.0
docker pull repo.example.com/docker-all/alpine:3
```

- **A group protects the images you push.** If a hosted repository behind the group
  has an image, only hosted repositories answer for that image: its tags, its
  manifests and its layers. An image on a public registry with the same name cannot
  stand in for yours or add a tag to it (the dependency-confusion attack), whatever
  the order of the members. If the only hosted repositories that have the image are
  offline, the group answers `503` for it.
- **A name is protected while a hosted repository holds anything of the image**, with
  a tag or without. Deleting a tag withdraws a release and does not hand the name to
  a public image: the tag is then `404`, and the image is still pulled by its digest.
  The name is free again once every manifest of the image has been deleted by its
  digest.
- **Everything else** comes from the proxies behind the group, the first that has it.
  If none has it and one of them could not ask its remote, the answer is `502`, not
  `404`.
- **Tags** (`tags/list`) are those of every repository that answers for the image,
  each once. The catalog lists every image with a tag in the online repositories
  behind the group, as `<group>/<image>`.
- Push to the hosted repository, not to the group: a group takes no pushes (`405`).
  Groups can contain groups.

Reading through a group needs `read` on the group only, for example
`repository:docker:docker-all:read`.
