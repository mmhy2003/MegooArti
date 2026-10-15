# Adding a format

A format is one class. The base class, `Format` in
`backend/src/megooarti/repositories/formats.py`, is a complete format by itself: files
stored and served by path, a proxy that fetches and caches, a group that asks its
members in order. A format subclasses it, sets `name`, and overrides only what is its
own. The Raw format is the whole of that and nothing more:

```python
from megooarti.repositories.formats import Format, register


class RawFormat(Format):
    """Entirely the generic behaviour."""

    name = "raw"


register(RawFormat())
```

A format never touches a table or a file. It works through the repository context it
is handed (`RepositoryContext` in `repositories/content.py`), which checks
permissions and policies, stores and reads files, and knows the components:
`context.respond(path, request)` answers with a stored file, `context.put(...)` and
`context.store(...)` store one, `context.delete(path)` removes one. A handler does
not commit: the route does, once the handler has returned, and nothing is kept if it
raises.

## The steps

1. **Write the class**, in a module or a package of its own under
   `backend/src/megooarti/repositories/`, and call `register` with an instance of it.
2. **Import the module in `backend/src/megooarti/main.py`**, beside the others: a
   format is known once its module has been imported.
3. **Say what is its own** by overriding what the table below lists. Start from what
   the format's own client sends: which requests it makes, in which order, and what
   it does with each answer.
4. **Give the web UI its name**: `FORMATS` in `frontend/src/lib/repository-form.ts`
   and in `frontend/src/components/permission-rows.tsx`,
   and, if a hosted repository of it takes uploads through the API, `UPLOADABLE` in
   `frontend/src/lib/content.ts` and in `frontend/src/screens/upload.tsx`, which
   also has the fields of each format's form.
5. **Write its guide** as `docs/formats/<name>.md`, add it to the README's table,
   and name the clients it is tested with in `CLIENTS` in
   `backend/tests/test_documents.py`. A test fails until every registered format has
   a guide that names them.
6. **If its clients reach it at an address of its own**, as Docker's do at `/v2/`,
   send that address to the backend in `gateway/nginx.conf`, and add it to the table
   in [Installation](installation.md#behind-your-own-reverse-proxy).

## What a format says of itself

| Member | What it is for | The generic format |
| --- | --- | --- |
| `name` | What repositories of the format are called in the API and in permissions | none: it must be set |
| `types` | Which of `hosted`, `proxy` and `group` there are | all three |
| `served_at` | Where clients reach it: under `/repository/<name>/`, or through a protocol with an address of its own, which then has its own routes (Docker's `/v2/`) | `repository` |
| `remote_signs_in` | Whether its remotes hand out tokens, as container registries do, so that a proxy signs in | no |
| `unlisted_namespaces` | Namespaces that are the format's own bookkeeping: not listed as components, not found by search | none |
| `no_upload` | Why a hosted repository takes no upload through the API, if it takes none: what its users are told to do instead | it takes uploads |
| `derives_indexes` | Whether a hosted repository's indexes are written from the packages it holds. It then counts its changes, and `snapshot()` and the `derived` cache serve an index once for each | no |
| `signs` | The kind of key a hosted repository signs its indexes with (`openpgp`). It is made the first time it is needed, and kept sealed | none |
| `validate_name` | Refuse a repository name the format cannot be used under | any name |
| `validate_config` | Check and return the format's own settings (`format_config`), and refuse a change that cannot be made | no settings |
| `validate_member` | Refuse a repository a group of the format cannot have as a member (an APT proxy without its remote's keys) | any |
| `default_deployment_policy` | The policy of a hosted repository that was given none | `allow_redeploy` |
| `describe_component` | Which component (namespace, name, version) a stored file belongs to, from its path and what was recorded about it at upload, or none | the file, in its folder |
| `search_text` | The words a component is found by | namespace, name and version |
| `delete_asset` | Delete a file as the format's own client would, with what goes with it; refuse one the format keeps itself | removes the file |
| `upload` | Store what an upload form carries, as the format's own client's upload would | a `directory`, and each `file` in it |
| `usage` | How a component is used, as text a person copies | nothing |
| `setup` | How a machine is set up to use a repository, as text a person copies: its key, its address, its credentials | nothing |
| `download_path` | Where a stored file is fetched | `/repository/<name>/<path>` |
| `content_type` | The content type to record for a file | what was declared |
| `remote_url` | Where a proxy finds a path on its remote | the path under the remote's address |
| `is_metadata` | Whether a path is an index that changes as packages are published, and so is asked about again sooner | no |
| `takes_body_credentials` | Whether a request carries its credentials in its body (npm's sign-in does) | no |
| `maintain` | What a repository needs done from time to time | nothing |
| `handle_hosted` | Answer a request to a hosted repository | `GET`, `HEAD`, `PUT`, `DELETE` by path |
| `handle_proxy` | Answer a request to a proxy | fetch on a miss, cache, keep serving |
| `handle_group` | Answer a request to a group | the first member that has the path |

`formats.py` has the signature of each and what it may rely on.

## What is expected of a format

- **Its own clients decide.** Unit tests are under
  `backend/tests/repositories/<name>/`, with a remote that is a stand-in
  (`tests/repositories/fake_remote.py`): no unit test reaches a network. But a format
  is done when its real clients are: a module `backend/tests/test_<name>_client.py`,
  marked `docker`, runs each client the format is for, in the client's own image,
  against a stack built from the working tree. Publishing, installing from an empty
  cache, through a proxy of the public registry and through a group, and whatever
  the client does that no document says.
- **What the server derives, it does not store.** Maven's `maven-metadata.xml` and
  checksums, npm's package document and PyPI's pages are written for each request
  from the files that are there, so they are right after a delete and after two
  uploads at the same moment.
- **Deleting goes through the format**, so that a repository is left as its own
  client would leave it.
- **A group protects the names that are published here** against a package of the
  same name on a public registry: where the format's clients choose by name, a
  hosted member that holds a name answers for it alone.
- **A proxy of a public registry in a test is not left alone after one failure**
  (`"auto_block": false`): the internet is slow now and then.
- **Nothing a remote or a client sends becomes a command.** A name goes into a
  snippet a person copies only if it is `plain`.
