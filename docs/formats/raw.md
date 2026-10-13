# Raw repositories

A Raw repository holds files by their paths, and nothing else is known of them. It is
what every other format is built on: what [Repositories](../repositories.md) says of
all of them is all there is to say of this one.

```bash
curl -u admin -H 'Content-Type: application/json' \
  -d '{"name":"files","format":"raw","type":"hosted"}' \
  http://localhost:8000/api/v1/repositories

curl -u admin -T ./build/app.tar.gz http://localhost:8000/repository/files/releases/app.tar.gz
curl -u admin -O http://localhost:8000/repository/files/releases/app.tar.gz
curl -u admin -X DELETE http://localhost:8000/repository/files/releases/app.tar.gz
```

- **Any HTTP client is its client**: `PUT` stores a file (`201` for a new path, `204`
  for one that was replaced), `GET` and `HEAD` read it, `DELETE` removes it.
- **A proxy** caches the files of any web server that serves them by path, and a
  **group** puts several repositories behind one address.
- **In search and in the web UI** every file is a component of its own, found by its
  folder and its name.
- Several files can be uploaded at once into a folder through the web UI or
  [the API](../api.md#uploading).
