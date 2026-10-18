# MCP: the Ops and Admin Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent whose token may run the registry makes, changes and deletes repositories, clears a proxy's cache, rebuilds an index, deletes content, and administers users, their tokens and roles, through `/mcp`; an agent whose token may not is never shown those tools.

**Architecture:** Three new tool modules beside 14a's: `mcp/operations.py` (repositories, and deleting content) and `mcp/administration.py` (users, tokens, roles), each tool calling its REST route function with the caller's principal. `mcp/tools.py` gains the annotations of tools that change things (`WRITE`, `CHANGE`, `DESTRUCTIVE`), the gates `holding(permission)` and `may_somewhere(action)`, and the REST API's words for a body it would refuse; the server stops telling a hidden tool's schema. A first task gives each format its public remotes, served at `GET /api/v1/formats`, which `create_repository` and the web form both use.

**Tech Stack:** Python 3.13, FastAPI, the MCP Python SDK 2.3.0, pydantic, pytest with the SDK's client; Next.js, React, TanStack Query and Vitest for the form.

**Spec:** [docs/superpowers/specs/2026-10-18-mcp-design.md](../specs/2026-10-18-mcp-design.md): section 6.2, E1, E3, and the row of plan 14b in section 12; the rulings of 14a's final review in its ledger (the SDK's `get_tool_input_schema`).

## Decisions this plan settles

Task 7 writes these into the spec, as "Settled while building plan 14b".

| # | Decision | Reason |
| --- | --- | --- |
| N1 | Each format says the public repository a proxy of it is made with where no remote is given (`Format.public_remotes`, by the protocol of its settings, `""` for none; `Format.public_remote(format_config)`), and `GET /api/v1/formats` gives them, with each format's types, to whoever is signed in. The web form takes them from there (in place of the form's own table). | One place says what a new proxy is given: the form and `create_repository` cannot differ (6.2). |
| N2 | A tool that changes is shown to whoever holds its REST route's permission (`holding`); `delete_component` and `delete_path`, whose permission is a repository's, to whoever may delete in some repository by their permissions, narrowed by their token's scopes, or by what is public (`may_somewhere`). Each call is still checked against its repository. | E1 for a permission that is not one string; a tool shown to someone who may delete only elsewhere is refused there, as the REST route refuses. |
| N3 | `Server._tool_input_schema` gives no schema of a tool the caller is not shown. | The SDK reads it to check a call's `Mcp-Param` headers before the call is made (the ruling of 14a's review). |
| N4 | What a tool is given that the REST route's body would refuse is refused in the same words: `validation_error`, a line for each field. | The routes are called with bodies made in the tool; their models' errors are the API's (8.1). |
| N5 | `update_repository` and `update_role` change only what is given: the rest is what there is, and a proxy's stored secret is kept unless a secret is given (the REST API's `PUT` takes them whole). `update_user`'s fields left out, or null, are not changed: an email is not cleared through MCP. | An agent that sends what it means to change does not undo the rest by leaving it out. |
| N6 | `create_user` makes a user who must change their password when they first sign in, always. | 6.2: no tool sets a password a person did not choose (D4 of the identity-access spec). |
| N7 | `delete_path` deletes a file at the path, or else everything under the folder, a thousand files at a time until there is none, each round committed; `No such file or folder.` where there is neither. `delete_component` takes a component's id, or its name and version as `package_details` does. | The REST API has a route for each; an agent names a path, as it does to `browse`. |
| N8 | `revoke_token` revokes API tokens; an OAuth approval is revoked by plan 14c's tools and screens. | There are no approvals before 14c. |

## Global Constraints

- **Each tool authorizes as the REST route beside it** (spec 6): it calls the route's function with the caller's principal.
- **A caller is shown, and may call, only the tools it could use** (E1); a tool that changes things is annotated so (E3): `WRITE`, `CHANGE` or `DESTRUCTIVE`.
- **Users, tokens and roles are named by their names** (E2), never by ids.
- **No tool makes a token, sets a password a person did not choose, or changes the server's settings** (spec 2, 6.2).
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, with `MEGOOARTI_TEST_DATABASE_URL` set to your test database; `pnpm` commands in `frontend/`; `git` commands in the repository root.

## Review Focus

What could hurt a person using this most, and which test of this plan pins it.

1. **An agent that would lock everyone out:** deleting or disabling itself, or the built-in roles, is refused in the REST API's words. Task 6: `test_a_user_is_deleted_but_not_oneself`, `test_a_user_is_changed_only_in_what_is_given`, `test_a_role_is_made_changed_in_what_is_given_and_deleted`.
2. **A partial change that wipes the rest:** blocking a proxy keeps its remote and its stored secret; renaming a user keeps their status. Tasks 4 and 6: `test_what_is_not_given_to_a_change_stays_as_it_is_the_secret_too`, `test_a_user_is_changed_only_in_what_is_given`.
3. **A token that may only read, calling a write tool by its name:** it is no tool of theirs. Task 4: `test_an_operation_a_caller_may_not_do_is_no_tool_of_theirs`.
4. **A delete shown to whoever may delete somewhere, called elsewhere:** refused for that repository. Task 5: `test_a_delete_where_the_caller_may_not_delete_is_refused`.
5. **A proxy of a format with no public repository, made without a remote:** refused, saying what to give. Task 4: `test_a_proxy_is_made_of_its_formats_public_repository_unless_one_is_given`.

---

### Task 1: Each format's public remotes, at `GET /api/v1/formats`

**Files:**
- Create: `backend/src/megooarti/repositories/formats_api.py`
- Modify: `backend/src/megooarti/repositories/formats.py`, `maven/format.py`, `npm/format.py`, `pypi/format.py`, `docker/format.py`, `apt/format.py`, `apk/format.py`, `nuget/format.py` (under `backend/src/megooarti/repositories/`), `backend/src/megooarti/main.py`, `docs/adding-a-format.md`, `frontend/openapi.json` and `frontend/src/lib/api/schema.d.ts` (both written by commands)
- Test: `backend/tests/repositories/test_formats_api.py`

**Interfaces:**
- Consumes: `formats.format_names()`, `get_format(name)`; `pagination.Page`, `PageParams`, `page`; `require_caller`.
- Produces: `Format.public_remotes: Mapping[str, str]` (by protocol, `""` for a format without one) and `Format.public_remote(format_config) -> str | None`; `GET /api/v1/formats` answering `Page[FormatOut]` with `name`, `types`, `public_remotes`; the frontend type `Schemas["FormatOut"]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/repositories/test_formats_api.py`:

```python
"""The formats this server has, and the public repository each gives a new proxy:
what the web form and an agent make repositories with (MCP spec 6.2)."""

import pytest

from megooarti.repositories.formats import format_names, get_format
from tests.accounts import PASSWORD, basic

NUGET = "https://api.nuget.org/v3/index.json"
CHOCOLATEY = "https://community.chocolatey.org/api/v2/"


async def test_every_format_is_listed_with_its_types_and_public_remotes(client, make_user):
    await make_user("dev")

    answer = await client.get("/api/v1/formats", headers=basic("dev", PASSWORD))

    assert answer.status_code == 200, answer.text
    listed = {item["name"]: item for item in answer.json()["items"]}
    assert sorted(listed) == sorted(format_names())
    assert listed["maven"]["public_remotes"] == {"": "https://repo1.maven.org/maven2"}
    assert listed["nuget"]["public_remotes"] == {"": NUGET, "v3": NUGET, "v2": CHOCOLATEY}
    assert listed["raw"]["public_remotes"] == {}
    assert listed["yum"]["public_remotes"] == {}
    assert listed["docker"]["types"] == ["group", "hosted", "proxy"]


async def test_the_formats_are_not_told_to_whoever_is_not_signed_in(client):
    assert (await client.get("/api/v1/formats")).status_code == 401


@pytest.mark.parametrize(
    ("name", "config", "remote"),
    [
        ("maven", {}, "https://repo1.maven.org/maven2"),
        ("npm", {}, "https://registry.npmjs.org"),
        ("pypi", {}, "https://pypi.org"),
        ("docker", {}, "https://registry-1.docker.io"),
        ("apt", {"suite": "stable"}, "http://deb.debian.org/debian"),
        ("apk", {}, "https://dl-cdn.alpinelinux.org/alpine"),
        ("nuget", {}, NUGET),
        ("nuget", {"protocol": "v3"}, NUGET),
        ("nuget", {"protocol": "v2"}, CHOCOLATEY),
        ("yum", {}, None),
        ("raw", {}, None),
    ],
)
def test_a_proxy_with_these_settings_is_given_its_formats_public_remote(name, config, remote):
    handler = get_format(name)
    assert handler is not None

    assert handler.public_remote(config) == remote
```

- [ ] **Step 2: Run it to verify it fails**

Run (in `backend/`): `uv run pytest -q tests/repositories/test_formats_api.py`
Expected: 13 failed: `GET /api/v1/formats` is `404`, and `AttributeError: 'NuGetFormat' object has no attribute 'public_remote'` (and of every format).

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/repositories/formats.py`:

```diff
@@ -6,9 +6,10 @@ they work through the repository context they are handed.
 """
 
 import re
-from collections.abc import Awaitable, Callable, Collection, Sequence
+from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
 from dataclasses import dataclass
 from datetime import datetime
+from types import MappingProxyType
 from typing import TYPE_CHECKING, Any
 from urllib.parse import quote
 
@@ -127,6 +128,15 @@ class Format:
     # The kind of key a hosted repository of this format signs its indexes with:
     # `openpgp`, or None for a format that signs nothing.
     signs: str | None = None
+    # The public repository a proxy of this format is made with where no remote is given,
+    # by the protocol of its `format_config` ("" for a format without one). None where
+    # there is no one public repository of the format.
+    public_remotes: Mapping[str, str] = MappingProxyType({})
+
+    def public_remote(self, format_config: Mapping[str, Any]) -> str | None:
+        """The public repository a proxy with these settings is made with, if there is one."""
+        protocol = str(format_config.get("protocol", ""))
+        return self.public_remotes.get(protocol, self.public_remotes.get(""))
 
     def validate_name(self, name: str) -> None:
         """Refuse a repository name this format cannot be used under. The generic format: none.
```

Change `backend/src/megooarti/repositories/maven/format.py`:

```diff
@@ -15,6 +15,7 @@ from collections.abc import Callable, Iterable, Sequence
 from concurrent.futures import ThreadPoolExecutor
 from contextlib import suppress
 from datetime import datetime
+from types import MappingProxyType
 from typing import Any
 from xml.sax.saxutils import escape
 
@@ -392,6 +393,7 @@ def _kind(files: Sequence[str]) -> str:
 
 class MavenFormat(Format):
     name = "maven"
+    public_remotes = MappingProxyType({"": "https://repo1.maven.org/maven2"})
 
     def validate_config(
         self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
```

Change `backend/src/megooarti/repositories/npm/format.py`:

```diff
@@ -21,6 +21,7 @@ import asyncio
 import weakref
 from collections.abc import Callable, Sequence
 from concurrent.futures import ThreadPoolExecutor
+from types import MappingProxyType
 from typing import Any
 from urllib.parse import quote
 
@@ -727,6 +728,7 @@ async def _group_search(context: RepositoryContext, request: Request) -> Respons
 
 class NpmFormat(Format):
     name = "npm"
+    public_remotes = MappingProxyType({"": "https://registry.npmjs.org"})
 
     async def upload(self, context: RepositoryContext, form: UploadForm) -> list[str]:
         """Publish a package tarball as `npm publish` would. Its `package.json` says what it is."""
```

Change `backend/src/megooarti/repositories/pypi/format.py`:

```diff
@@ -23,6 +23,7 @@ import asyncio
 import hashlib
 from collections.abc import AsyncIterator, Callable, Sequence
 from concurrent.futures import ThreadPoolExecutor
+from types import MappingProxyType
 from typing import Any
 
 from packaging.version import InvalidVersion, Version
@@ -424,6 +425,7 @@ def _pep440_key(text: str) -> tuple:
 
 class PypiFormat(Format):
     name = "pypi"
+    public_remotes = MappingProxyType({"": "https://pypi.org"})
 
     def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
         """Its name and version, and the summary and keywords its upload declared."""
```

Change `backend/src/megooarti/repositories/docker/format.py`:

```diff
@@ -33,6 +33,7 @@ import json
 import re
 from collections.abc import Sequence
 from datetime import datetime, timedelta
+from types import MappingProxyType
 from typing import Any
 from urllib.parse import quote, urljoin, urlsplit
 
@@ -747,6 +748,7 @@ async def _grouped_tags(
 
 class DockerFormat(Format):
     name = FORMAT
+    public_remotes = MappingProxyType({"": "https://registry-1.docker.io"})
     served_at = "registry"
     remote_signs_in = True
     unlisted_namespaces = frozenset({names.MANIFESTS})
```

Change `backend/src/megooarti/repositories/apt/format.py`:

```diff
@@ -18,6 +18,7 @@ import asyncio
 import hashlib
 from collections.abc import Sequence
 from contextlib import aclosing
+from types import MappingProxyType
 from typing import Any
 from urllib.parse import urlsplit
 
@@ -287,6 +288,7 @@ def setup_of(address: str, repository: Repository) -> list[Usage]:
 
 class AptFormat(Format):
     name = "apt"
+    public_remotes = MappingProxyType({"": "http://deb.debian.org/debian"})
     types = frozenset({"hosted", "proxy", "group"})
     derives_indexes = True
     signs = signing.OPENPGP
```

Change `backend/src/megooarti/repositories/apk/format.py`:

```diff
@@ -19,6 +19,7 @@ import hashlib
 from collections import defaultdict
 from collections.abc import Sequence
 from contextlib import aclosing
+from types import MappingProxyType
 from typing import Any
 from urllib.parse import urlsplit, urlunsplit
 
@@ -281,6 +282,7 @@ def setup_of(address: str, repository: Repository) -> list[Usage]:
 
 class ApkFormat(Format):
     name = "apk"
+    public_remotes = MappingProxyType({"": "https://dl-cdn.alpinelinux.org/alpine"})
     types = frozenset({"hosted", "proxy", "group"})
     derives_indexes = True
     signs = signing.RSA
```

Change `backend/src/megooarti/repositories/nuget/format.py`:

```diff
@@ -20,6 +20,7 @@ import xml.sax.saxutils
 from collections.abc import Sequence
 from contextlib import aclosing
 from dataclasses import replace
+from types import MappingProxyType
 from typing import Any
 
 from starlette.requests import Request
@@ -487,6 +488,15 @@ async def describe_fetched(
 
 class NuGetFormat(Format):
     name = "nuget"
+    # nuget.org's V3 feed (a proxy's protocol is V3 unless it is said), and for V2
+    # Chocolatey's community feed.
+    public_remotes = MappingProxyType(
+        {
+            "": "https://api.nuget.org/v3/index.json",
+            "v3": "https://api.nuget.org/v3/index.json",
+            "v2": "https://community.chocolatey.org/api/v2/",
+        }
+    )
     types = frozenset({"hosted", "proxy", "group"})
     derives_indexes = True
 
```

Create `backend/src/megooarti/repositories/formats_api.py`:

```python
"""The formats this server has: what the web form, and an agent, make repositories of."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from megooarti.pagination import Page, PageParams, page
from megooarti.repositories.formats import format_names, get_format
from megooarti.security.authentication import Principal, require_caller

router = APIRouter(prefix="/formats", tags=["repositories"])


class FormatOut(BaseModel):
    name: str
    types: list[str]  # of "hosted", "proxy" and "group"
    # The public repository a new proxy is given where no remote is said, by the
    # protocol of its settings ("" for a format without one): none, where there is no one.
    public_remotes: dict[str, str]


@router.get("", response_model=Page[FormatOut])
async def list_formats(
    params: PageParams = Depends(), _: Principal = Depends(require_caller)
) -> dict:
    """Every format, in name order."""
    every = []
    for name in sorted(format_names()):
        handler = get_format(name)
        if handler is not None:
            every.append(
                FormatOut(
                    name=name,
                    types=sorted(handler.types),
                    public_remotes=dict(handler.public_remotes),
                )
            )
    return page(every[params.offset : params.offset + params.limit], len(every), params)
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -25,6 +25,7 @@ from megooarti.repositories.apk import format as _apk_format  # noqa: F401  (reg
 from megooarti.repositories.apt import format as _apt_format  # noqa: F401  (registers it)
 from megooarti.repositories.content_api import router as content_api_router
 from megooarti.repositories.docker.routes import router as registry_router  # registers the format
+from megooarti.repositories.formats_api import router as formats_router
 from megooarti.repositories.maven import format as _maven_format  # noqa: F401  (registers it)
 from megooarti.repositories.npm import format as _npm_format  # noqa: F401  (registers it)
 from megooarti.repositories.nuget import format as _nuget_format  # noqa: F401  (registers it)
@@ -153,6 +154,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.include_router(repositories_router, prefix=API_PREFIX)
     app.include_router(content_api_router, prefix=API_PREFIX)
     app.include_router(search_router, prefix=API_PREFIX)
+    app.include_router(formats_router, prefix=API_PREFIX)
     app.include_router(content_router)  # /repository/..., outside the JSON API
     app.include_router(registry_router)  # /v2/..., the container registry API
     app.state.mcp = McpServer()
```

Change `docs/adding-a-format.md`:

```diff
@@ -67,6 +67,8 @@ raises.
 | `default_deployment_policy` | The policy of a hosted repository that was given none | `allow_redeploy` |
 | `describe_component` | Which component (namespace, name, version) a stored file belongs to, from its path and what was recorded about it at upload, or none | the file, in its folder |
 | `search_text` | The words a component is found by | namespace, name and version |
+| `public_remotes` | The public repository a proxy is made with where no remote is given, by the protocol of its settings (`""` for a format without one), as `GET /api/v1/formats` gives them to the web form and agents | none |
+| `public_remote` | Which of them a proxy with given settings is made with | the protocol's, else `""`'s |
 | `ordered_versions` | A package's versions from the oldest to the newest, as the format's clients order them, or none where they have no order (Docker's tags): what an agent is told is the newest | numbers read as numbers: 1.10 after 1.9 |
 | `is_prerelease` | Whether a client takes a version only when it is asked for: a prerelease, a snapshot | none is |
 | `delete_asset` | Delete a file as the format's own client would, with what goes with it; refuse one the format keeps itself | removes the file |
```

Change `frontend/openapi.json`:

```diff
@@ -502,6 +502,35 @@
         "title": "FolderDeleted",
         "type": "object"
       },
+      "FormatOut": {
+        "properties": {
+          "name": {
+            "title": "Name",
+            "type": "string"
+          },
+          "public_remotes": {
+            "additionalProperties": {
+              "type": "string"
+            },
+            "title": "Public Remotes",
+            "type": "object"
+          },
+          "types": {
+            "items": {
+              "type": "string"
+            },
+            "title": "Types",
+            "type": "array"
+          }
+        },
+        "required": [
+          "name",
+          "types",
+          "public_remotes"
+        ],
+        "title": "FormatOut",
+        "type": "object"
+      },
       "GroupSettings": {
         "properties": {
           "members": {
@@ -736,6 +765,37 @@
         "title": "Page[ComponentView]",
         "type": "object"
       },
+      "Page_FormatOut_": {
+        "properties": {
+          "items": {
+            "items": {
+              "$ref": "#/components/schemas/FormatOut"
+            },
+            "title": "Items",
+            "type": "array"
+          },
+          "limit": {
+            "title": "Limit",
+            "type": "integer"
+          },
+          "offset": {
+            "title": "Offset",
+            "type": "integer"
+          },
+          "total": {
+            "title": "Total",
+            "type": "integer"
+          }
+        },
+        "required": [
+          "items",
+          "total",
+          "limit",
+          "offset"
+        ],
+        "title": "Page[FormatOut]",
+        "type": "object"
+      },
       "Page_RepositoryOut_": {
         "properties": {
           "items": {
@@ -3156,6 +3216,63 @@
         ]
       }
     },
+    "/api/v1/formats": {
+      "get": {
+        "description": "Every format, in name order.",
+        "operationId": "list_formats_api_v1_formats_get",
+        "parameters": [
+          {
+            "in": "query",
+            "name": "limit",
+            "required": false,
+            "schema": {
+              "default": 50,
+              "maximum": 200,
+              "minimum": 1,
+              "title": "Limit",
+              "type": "integer"
+            }
+          },
+          {
+            "in": "query",
+            "name": "offset",
+            "required": false,
+            "schema": {
+              "default": 0,
+              "minimum": 0,
+              "title": "Offset",
+              "type": "integer"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Page_FormatOut_"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "List Formats",
+        "tags": [
+          "repositories"
+        ]
+      }
+    },
     "/api/v1/me/password": {
       "put": {
         "operationId": "change_password_api_v1_me_password_put",
```

Change `frontend/src/lib/api/schema.d.ts`:

```diff
@@ -245,6 +245,26 @@ export interface paths {
         patch?: never;
         trace?: never;
     };
+    "/api/v1/formats": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /**
+         * List Formats
+         * @description Every format, in name order.
+         */
+        get: operations["list_formats_api_v1_formats_get"];
+        put?: never;
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/me/password": {
         parameters: {
             query?: never;
@@ -870,6 +890,17 @@ export interface components {
             /** Skipped */
             skipped: number;
         };
+        /** FormatOut */
+        FormatOut: {
+            /** Name */
+            name: string;
+            /** Public Remotes */
+            public_remotes: {
+                [key: string]: string;
+            };
+            /** Types */
+            types: string[];
+        };
         /** GroupSettings */
         GroupSettings: {
             /**
@@ -960,6 +991,17 @@ export interface components {
             /** Total */
             total: number;
         };
+        /** Page[FormatOut] */
+        Page_FormatOut_: {
+            /** Items */
+            items: components["schemas"]["FormatOut"][];
+            /** Limit */
+            limit: number;
+            /** Offset */
+            offset: number;
+            /** Total */
+            total: number;
+        };
         /** Page[RepositoryOut] */
         Page_RepositoryOut_: {
             /** Items */
@@ -2083,6 +2125,38 @@ export interface operations {
             };
         };
     };
+    list_formats_api_v1_formats_get: {
+        parameters: {
+            query?: {
+                limit?: number;
+                offset?: number;
+            };
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Page_FormatOut_"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
     change_password_api_v1_me_password_put: {
         parameters: {
             query?: never;
```

Then write the API's description and its types for the frontend:

Run (in `backend/`): `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`; then (in `frontend/`): `pnpm gen:api`

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/repositories/test_formats_api.py tests/test_documents.py tests/test_route_guards.py tests/test_openapi_snapshot.py`
Expected: 165 passed.

- [ ] **Step 5: Commit**

```bash
git add backend docs/adding-a-format.md frontend/openapi.json frontend/src/lib/api/schema.d.ts
git commit -m "feat: each format's public remotes, at GET /api/v1/formats"
```

---

### Task 2: The form's public remotes are the server's

**Files:**
- Modify: `frontend/src/lib/api/types.ts`, `frontend/src/lib/repository-form.ts`, `frontend/src/lib/administration.ts`, `frontend/src/screens/repository-settings.tsx`
- Test: `frontend/src/lib/repository-form.test.ts`, `frontend/src/screens/administration.test.tsx`

**Interfaces:**
- Consumes: Task 1's `GET /formats` and `Schemas["FormatOut"]`; the form's `Draft`, `EMPTY`; `administration.ts`'s `every`.
- Produces: `FormatOut`; `PublicRemotes`; `publicRemotesOf(formats) -> PublicRemotes`; `defaultRemoteOf(draft, remotes)` and `withDefaultRemote(held, change, remotes)` (each now takes the server's table); `useFormats(enabled)`.

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/lib/repository-form.test.ts`:

```diff
@@ -20,6 +20,7 @@ import {
   moved,
   policyOf,
   problemsOf,
+  publicRemotesOf,
   takesRemoteKeys,
   updateBody,
   withDefaultRemote,
@@ -518,6 +519,26 @@ describe("the addresses of a repository's settings", () => {
 
 describe("the remote a proxy is made with", () => {
   const making = (change: Partial<Draft>): Draft => ({ ...EMPTY, ...change });
+  // As the server gives them (GET /formats).
+  const REMOTES = publicRemotesOf([
+    { name: "maven", types: [], public_remotes: { "": "https://repo1.maven.org/maven2" } },
+    { name: "npm", types: [], public_remotes: { "": "https://registry.npmjs.org" } },
+    { name: "pypi", types: [], public_remotes: { "": "https://pypi.org" } },
+    { name: "docker", types: [], public_remotes: { "": "https://registry-1.docker.io" } },
+    { name: "apt", types: [], public_remotes: { "": "http://deb.debian.org/debian" } },
+    { name: "apk", types: [], public_remotes: { "": "https://dl-cdn.alpinelinux.org/alpine" } },
+    {
+      name: "nuget",
+      types: [],
+      public_remotes: {
+        "": "https://api.nuget.org/v3/index.json",
+        v3: "https://api.nuget.org/v3/index.json",
+        v2: "https://community.chocolatey.org/api/v2/",
+      },
+    },
+    { name: "yum", types: [], public_remotes: {} },
+    { name: "raw", types: [], public_remotes: {} },
+  ]);
 
   test.each([
     ["maven", "v3", "https://repo1.maven.org/maven2"],
@@ -531,14 +552,14 @@ describe("the remote a proxy is made with", () => {
     ["yum", "v3", ""],
     ["raw", "v3", ""],
   ])("of %s (%s) is its public one, or none where there is no one", (format, protocol, remote) => {
-    expect(defaultRemoteOf(making({ format, type: "proxy", protocol }))).toBe(remote);
-    expect(defaultRemoteOf(making({ format, type: "hosted", protocol }))).toBe("");
+    expect(defaultRemoteOf(making({ format, type: "proxy", protocol }), REMOTES)).toBe(remote);
+    expect(defaultRemoteOf(making({ format, type: "hosted", protocol }), REMOTES)).toBe("");
   });
 
   test("is given as a proxy is chosen, and follows the format, the type and the protocol", () => {
     let held = making({});
     const change = (one: Partial<Draft>) => {
-      held = { ...held, ...withDefaultRemote(held, one) };
+      held = { ...held, ...withDefaultRemote(held, one, REMOTES) };
       return held.remoteUrl;
     };
 
@@ -559,9 +580,13 @@ describe("the remote a proxy is made with", () => {
       { type: "hosted" as const },
       { type: "proxy" as const },
     ]) {
-      held = { ...held, ...withDefaultRemote(held, one) };
+      held = { ...held, ...withDefaultRemote(held, one, REMOTES) };
       expect(held.remoteUrl).toBe("https://mirror.example.org/maven2");
     }
-    expect(withDefaultRemote(held, { remoteUrl: "" })).toEqual({ remoteUrl: "" });
+    expect(withDefaultRemote(held, { remoteUrl: "" }, REMOTES)).toEqual({ remoteUrl: "" });
+  });
+
+  test("is none while the server has not said what its formats' are", () => {
+    expect(defaultRemoteOf(making({ format: "maven", type: "proxy" }), {})).toBe("");
   });
 });
```

Change `frontend/src/screens/administration.test.tsx`:

```diff
@@ -14,6 +14,35 @@ import { NewRepositoryScreen, RepositorySettingsScreen } from "./repository-sett
 import { SystemScreen } from "./system";
 
 const page = (items: unknown[], total = items.length) => ({ items, total, limit: 50, offset: 0 });
+// The public repositories a new proxy is given, as the server says (GET /formats).
+const FORMATS = [
+  {
+    name: "maven",
+    types: ["group", "hosted", "proxy"],
+    public_remotes: { "": "https://repo1.maven.org/maven2" },
+  },
+  {
+    name: "npm",
+    types: ["group", "hosted", "proxy"],
+    public_remotes: { "": "https://registry.npmjs.org" },
+  },
+  { name: "pypi", types: ["group", "hosted", "proxy"], public_remotes: { "": "https://pypi.org" } },
+  {
+    name: "apt",
+    types: ["group", "hosted", "proxy"],
+    public_remotes: { "": "http://deb.debian.org/debian" },
+  },
+  {
+    name: "nuget",
+    types: ["group", "hosted", "proxy"],
+    public_remotes: {
+      "": "https://api.nuget.org/v3/index.json",
+      v3: "https://api.nuget.org/v3/index.json",
+      v2: "https://community.chocolatey.org/api/v2/",
+    },
+  },
+  { name: "yum", types: ["group", "hosted", "proxy"], public_remotes: {} },
+];
 const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
 const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
 const notices = () => screen.getByRole("region", { name: "Notifications" });
@@ -175,6 +204,7 @@ describe("a new repository (R2)", () => {
     const api = mockApi({
       "GET /repositories": { json: page([ALL, CENTRAL, NPM, RELEASES]) },
       "GET /blob-stores": { json: page(STORES) },
+      "GET /formats": { json: page(FORMATS) },
       "POST /repositories": (call) => ({
         status: 201,
         json: repository((call.body as { name: string }).name),
@@ -340,6 +370,24 @@ describe("a new repository (R2)", () => {
     });
   });
 
+  test("a proxy's public remote is the one the server says", async () => {
+    const user = userEvent.setup();
+    const { calls } = fresh({
+      "GET /formats": {
+        json: page([
+          { name: "maven", types: [], public_remotes: { "": "https://maven.internal/central" } },
+        ]),
+      },
+    });
+    await waitFor(() => expect(calls.some((call) => call.path.startsWith("/formats"))).toBe(true));
+
+    await user.click(screen.getByRole("radio", { name: "Proxy" }));
+
+    await waitFor(() =>
+      expect(screen.getByLabelText("Remote address")).toHaveValue("https://maven.internal/central"),
+    );
+  });
+
   test("a remote that was typed is not given another when the format changes", async () => {
     const user = userEvent.setup();
     fresh();
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/lib/repository-form.test.ts src/screens/administration.test.tsx`
Expected: `repository-form.test.ts` does not load (`publicRemotesOf` is not exported), and `a proxy's public remote is the one the server says` fails: 1 failed, 79 passed.

- [ ] **Step 3: Write the code**

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -41,6 +41,8 @@ export type SigningKeyOut = Schemas["SigningKeyOut"];
 export type SigningKeyGenerate = Schemas["SigningKeyGenerate"];
 export type SigningKeyImport = Schemas["SigningKeyImport"];
 export type BlobStoreOut = Schemas["BlobStoreOut"];
+/** A format the server has: its types, and the public repository a new proxy is given. */
+export type FormatOut = Schemas["FormatOut"];
 export type BlobStoreCreate = Schemas["BlobStoreCreate"];
 /** What is running: version, schema, runtime, database. */
 export type Information = Schemas["Information"];
```

Change `frontend/src/lib/repository-form.ts`:

```diff
@@ -5,7 +5,7 @@
  * type. This module says which parts a combination has, what a form starts with, what
  * is wrong with it before the server is asked, and the body that is sent.
  */
-import type { RepositoryCreate, RepositoryOut, RepositoryUpdate } from "@/lib/api/types";
+import type { FormatOut, RepositoryCreate, RepositoryOut, RepositoryUpdate } from "@/lib/api/types";
 import { isAddressable } from "@/lib/paths";
 
 /** The formats the server has. Each can be hosted, a proxy or a group. */
@@ -178,41 +178,42 @@ export function hasSigningKey(repository: { format: string; type: string }): boo
   return repository.type !== "proxy" && SIGNED.has(repository.format);
 }
 
-/** Whether a combination has a NuGet proxy's settings: its protocol and its symbol server. */
-// The public repository a proxy of each format is made with unless another is typed. YUM
-// has none (each distribution, version and architecture has its own), nor has raw.
-const PUBLIC_REMOTES: Readonly<Record<string, string>> = {
-  maven: "https://repo1.maven.org/maven2",
-  npm: "https://registry.npmjs.org",
-  pypi: "https://pypi.org",
-  docker: "https://registry-1.docker.io",
-  apt: "http://deb.debian.org/debian",
-  apk: "https://dl-cdn.alpinelinux.org/alpine",
-};
-// NuGet's, by protocol: nuget.org's V3 feed, and Chocolatey's community feed for V2.
-const PUBLIC_NUGET_REMOTES: Readonly<Record<string, string>> = {
-  v3: "https://api.nuget.org/v3/index.json",
-  v2: "https://community.chocolatey.org/api/v2/",
-};
+/**
+ * The public repository a new proxy is given where no remote is typed, by format and by the
+ * protocol of its settings ("" for a format without one), as the server says (GET /formats).
+ */
+export type PublicRemotes = Readonly<Record<string, Readonly<Record<string, string>>>>;
+
+export function publicRemotesOf(formats: readonly FormatOut[]): PublicRemotes {
+  return Object.fromEntries(formats.map((format) => [format.name, format.public_remotes]));
+}
 
 /** The public remote a proxy of the form's format (and protocol) is given; none for
  * another type, or a format without one. */
-export function defaultRemoteOf(draft: Pick<Draft, "format" | "type" | "protocol">): string {
+export function defaultRemoteOf(
+  draft: Pick<Draft, "format" | "type" | "protocol">,
+  remotes: PublicRemotes,
+): string {
   if (draft.type !== "proxy") return "";
-  const remotes = draft.format === "nuget" ? PUBLIC_NUGET_REMOTES : PUBLIC_REMOTES;
-  return (draft.format === "nuget" ? remotes[draft.protocol] : remotes[draft.format]) ?? "";
+  const ofFormat = remotes[draft.format] ?? {};
+  return ofFormat[draft.protocol] ?? ofFormat[""] ?? "";
 }
 
 /** A change to a form for a new repository, with the remote that goes with it: the public
  * one of the format, type and protocol it leads to, while the remote is none or the one the
  * form gave. A remote that was typed is kept. */
-export function withDefaultRemote(held: Draft, change: Partial<Draft>): Partial<Draft> {
+export function withDefaultRemote(
+  held: Draft,
+  change: Partial<Draft>,
+  remotes: PublicRemotes,
+): Partial<Draft> {
   if ("remoteUrl" in change) return change;
-  if (held.remoteUrl !== "" && held.remoteUrl !== defaultRemoteOf(held)) return change;
-  const remoteUrl = defaultRemoteOf({ ...held, ...change });
+  if (held.remoteUrl !== "" && held.remoteUrl !== defaultRemoteOf(held, remotes)) return change;
+  const remoteUrl = defaultRemoteOf({ ...held, ...change }, remotes);
   return remoteUrl === held.remoteUrl ? change : { ...change, remoteUrl };
 }
 
+/** Whether a combination has a NuGet proxy's settings: its protocol and its symbol server. */
 export function isNuGetProxy(draft: { format: string; type: string }): boolean {
   return draft.format === "nuget" && draft.type === "proxy";
 }
```

Change `frontend/src/lib/administration.ts`:

```diff
@@ -10,6 +10,7 @@ import { api } from "@/lib/api/client";
 import type {
   BlobStoreCreate,
   BlobStoreOut,
+  FormatOut,
   IndexRebuilt,
   Information,
   Page,
@@ -57,6 +58,16 @@ function afterRepositoryChange(client: QueryClient): Promise<void> {
 
 // --- Repositories ---------------------------------------------------------------------------
 
+/** The formats the server has, and the public repository each gives a new proxy. */
+export function useFormats(enabled = true) {
+  return useQuery({
+    queryKey: ["formats"],
+    queryFn: () => every<FormatOut>("/formats"),
+    enabled,
+    staleTime: Infinity, // they change with the server's version only
+  });
+}
+
 export function useManagedRepositories(page: number) {
   return useQuery({
     queryKey: [REPOSITORIES, "list", page],
```

Change `frontend/src/screens/repository-settings.tsx`:

```diff
@@ -21,6 +21,7 @@ import {
   useCreateRepository,
   useDeleteRepository,
   useEveryBlobStore,
+  useFormats,
   useEveryManagedRepository,
   useInvalidateCache,
   useManagedRepository,
@@ -59,6 +60,7 @@ import {
   TYPES,
   updateBody,
   VERSION_POLICIES,
+  publicRemotesOf,
   withDefaultRemote,
   type Draft,
   type RepositoryType,
@@ -126,8 +128,13 @@ function RepositoryForm({
   const creating = repository === null;
   const [draft, setDraft] = useState<Draft>(() => (repository ? draftOf(repository) : EMPTY));
   // A new proxy is given its format's public remote, until another is typed.
+  const formats = useFormats(creating);
+  const remotes = publicRemotesOf(formats.data ?? []);
   const set = (change: Partial<Draft>) =>
-    setDraft((held) => ({ ...held, ...(creating ? withDefaultRemote(held, change) : change) }));
+    setDraft((held) => ({
+      ...held,
+      ...(creating ? withDefaultRemote(held, change, remotes) : change),
+    }));
   const { form, tried, attempt } = useAttempts(error);
   const storesReadable = may("admin:blobstores:read");
   const stores = useEveryBlobStore(creating && storesReadable);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/lib/repository-form.test.ts src/screens/administration.test.tsx && pnpm lint && pnpm typecheck`
Expected: 165 passed; `All matched files use Prettier code style!`; the types check.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): a new proxy's public remote is the one the server says"
```

---

### Task 3: What tools that change things share

**Files:**
- Modify: `backend/src/megooarti/mcp/tools.py`, `backend/src/megooarti/mcp/server.py`
- Test: `backend/tests/mcp/test_gates.py`

**Interfaces:**
- Consumes: 14a's `tools.tool`, `Tool`, `TOOLS`, `caller`, `said`, `READ`; `Server._shown`; `tests.repositories.conftest.someone`.
- Produces: `tools.WRITE`, `CHANGE`, `DESTRUCTIVE` (annotations); `tools.holding(permission) -> Callable[[Principal], bool]`; `tools.may_somewhere(action) -> Callable[[Principal], bool]`; `tools.refused(error: ValidationError) -> ApiError`; `Server._tool_input_schema(name)` giving None for a tool not shown.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/mcp/test_gates.py`:

```python
"""What tools that change things share (MCP spec E1, E3, 8.1): who is shown them, what
they say of themselves, and a refusal of what they were given."""

import pytest
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request

from megooarti.mcp import tools
from megooarti.mcp.server import Server
from tests.mcp.conftest import refusal
from tests.repositories.conftest import someone


@pytest.mark.parametrize(
    ("patterns", "scopes", "shown"),
    [
        (["*"], None, True),
        (["repository"], None, True),
        (["repository:maven"], None, True),
        (["repository:*:releases:delete"], None, True),
        (["repository:maven:releases:*"], None, True),
        (["repository:maven:releases:read", "admin:users:write"], None, False),
        (["*"], ["repository:*:*:read"], False),  # the token narrows it
        (["*"], ["repository:npm:private:delete"], True),
        ([], None, False),
    ],
)
def test_a_tool_of_contents_is_shown_to_whoever_may_do_it_to_some_repository(
    patterns, scopes, shown
):
    principal = someone(*patterns)
    if scopes is not None:
        principal = type(principal)(principal.user, "token", principal.patterns, frozenset(scopes))

    assert tools.may_somewhere("delete")(principal) is shown


def test_a_tool_of_administration_is_shown_to_whoever_holds_its_permission():
    gate = tools.holding("admin:users:write")

    assert gate(someone("admin:users")) is True
    assert gate(someone("admin:users:read")) is False


def test_what_tools_that_change_things_say_of_themselves():
    assert tools.WRITE == ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
    )
    assert tools.CHANGE == ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    assert tools.DESTRUCTIVE == ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    )


@pytest.fixture
def hidden(app, monkeypatch):
    """A tool for those who may read users, and one that is given what it cannot take."""
    monkeypatch.setattr(tools, "TOOLS", list(tools.TOOLS))

    @tools.tool(shown_to=tools.holding("admin:users:read"))
    async def list_everyone(name: str) -> str:
        """Only for those who may read users."""
        return name

    class Named(BaseModel):
        name: str = Field(pattern=r"^[a-z]+$")

    @tools.tool()
    async def take_a_name(name: str) -> str:
        """Takes a name of letters only, as the REST API's body would."""
        return Named(name=name).name

    app.state.mcp = Server()
    return app.state.mcp


def test_a_hidden_tools_schema_is_not_told_to_whoever_may_not_use_it(hidden):
    request = Request({"type": "http", "headers": []})

    tools.enter(tools.Caller(someone("repository:*:*:read"), request))
    unseen = hidden._tool_input_schema("list_everyone")
    tools.enter(tools.Caller(someone("admin:users:read"), request))
    seen = hidden._tool_input_schema("list_everyone")

    assert unseen is None
    assert seen is not None and "name" in seen["properties"]


async def test_what_the_rest_apis_body_would_refuse_is_refused_in_its_words(
    agent, make_user, make_token, hidden
):
    token = await make_token(await make_user("dev"))

    async with agent(token) as client:
        refused = await client.call_tool("take_a_name", {"name": "Not Letters"})

    said = refusal(refused)
    assert (
        "validation_error: The request is not valid.\n- name: String should match pattern" in said
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/mcp/test_gates.py`
Expected: 11 failed, 2 errors: `AttributeError: module 'megooarti.mcp.tools' has no attribute 'may_somewhere'` (and `holding`, `WRITE`).

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/mcp/tools.py`:

```diff
@@ -12,6 +12,7 @@ from typing import Any
 import structlog
 from mcp.server.mcpserver.exceptions import ToolError
 from mcp.types import ToolAnnotations
+from pydantic import ValidationError
 from sqlalchemy.ext.asyncio import AsyncSession
 from starlette.requests import Request
 
@@ -20,11 +21,23 @@ from megooarti.security.authentication import Principal
 
 log = structlog.get_logger(__name__)
 
-# What a tool that only reads says of itself (E3): it changes nothing, and asks nothing
+# What a tool says of itself (E3). One that only reads changes nothing, and asks nothing
 # of the world outside this server.
 READ = ToolAnnotations(
     read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
 )
+# One that makes something: made again, it is refused, or there are two.
+WRITE = ToolAnnotations(
+    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
+)
+# One that changes something to what it is given: given it again, nothing more changes.
+CHANGE = ToolAnnotations(
+    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
+)
+# One that deletes, or takes away: a client asks the person first.
+DESTRUCTIVE = ToolAnnotations(
+    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
+)
 
 
 @dataclass(frozen=True)
@@ -61,6 +74,34 @@ def anyone(principal: Principal) -> bool:
     return True
 
 
+def holding(permission: str) -> Callable[[Principal], bool]:
+    """Shown to whoever holds `permission`, as the REST route it stands beside requires."""
+    return lambda principal: principal.allows(permission)
+
+
+def _could(pattern: str, action: str) -> bool:
+    """Whether a pattern grants `action` on the content of some repository."""
+    wanted = ("repository", None, None, action)  # None: whatever its format and its name
+    return all(
+        part == "*" or want is None or part == want
+        for part, want in zip(pattern.split(":"), wanted, strict=False)
+    )
+
+
+def may_somewhere(action: str) -> Callable[[Principal], bool]:
+    """Shown to whoever may do `action` to the content of some repository: by their
+    permissions, narrowed by their token's scopes, or by what is public."""
+
+    def shown(principal: Principal) -> bool:
+        if any(_could(pattern, action) for pattern in principal.public):
+            return True
+        if principal.is_anonymous or not any(_could(p, action) for p in principal.patterns):
+            return False
+        return principal.scopes is None or any(_could(s, action) for s in principal.scopes)
+
+    return shown
+
+
 @dataclass(frozen=True)
 class Tool:
     function: Callable[..., Awaitable[Any]]
@@ -74,6 +115,15 @@ class Tool:
 TOOLS: list[Tool] = []
 
 
+def refused(error: ValidationError) -> ApiError:
+    """What the tool was given, refused as the REST API refuses a body it cannot take."""
+    details = [
+        {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
+        for item in error.errors()
+    ]
+    return ApiError(422, "validation_error", "The request is not valid.", details)
+
+
 def said(error: ApiError) -> str:
     """A REST error as an agent reads it: its code, its message, and each field's."""
     lines = [f"{error.code}: {error.message}"]
@@ -99,6 +149,9 @@ def tool(
             except ApiError as error:
                 outcome = error.code
                 raise ToolError(said(error)) from None
+            except ValidationError as error:
+                outcome = "validation_error"
+                raise ToolError(said(refused(error))) from None
             except ToolError:
                 outcome = "refused"
                 raise
```

Change `backend/src/megooarti/mcp/server.py`:

```diff
@@ -56,6 +56,11 @@ class Server(MCPServer):
         shown_to = self._shown_to.get(name)
         return shown_to is not None and shown_to(tools.caller().principal)
 
+    def _tool_input_schema(self, name: str) -> dict[str, Any] | None:
+        # The SDK reads it to check a call's `Mcp-Param` headers before the call is made:
+        # a tool the caller is not shown has, for them, no schema to check against.
+        return super()._tool_input_schema(name) if self._shown(name) else None
+
     async def list_tools(self) -> list[Tool]:
         return [listed for listed in await super().list_tools() if self._shown(listed.name)]
 
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/mcp`
Expected: 65 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(mcp): what tools that change things say of themselves, who is shown them, and a body refused in the API's words"
```

---

### Task 4: Running repositories

**Files:**
- Create: `backend/src/megooarti/mcp/operations.py`
- Modify: `backend/src/megooarti/mcp/server.py`
- Test: `backend/tests/mcp/test_operations.py`

**Interfaces:**
- Consumes: Task 1's `Format.public_remote`; Task 3's `WRITE`, `CHANGE`, `DESTRUCTIVE`, `holding`; `repositories.api`'s `create_repository`, `update_repository`, `delete_repository`, `invalidate_cache`, `rebuild_index` and its models `RepositoryCreate`, `RepositoryUpdate`, `RepositoryOut`, `HostedIn`, `ProxyIn`, `NegativeCache`, `RemoteAuthIn`, `GroupSettings`, `IndexRebuilt`; `service.get_repository`, `describe`.
- Produces: the tools `create_repository`, `update_repository`, `delete_repository`, `invalidate_proxy_cache`, `rebuild_search_index`; `operations.ProxySettings`, `Done`, `Name`, `WRITE_REPOSITORIES`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/mcp/test_operations.py`:

```python
"""Running repositories through MCP (spec 6.2): making, changing and deleting them,
clearing a proxy's cache, and going through an index again; shown only to whoever may
change repositories."""

import pytest

from tests.accounts import PASSWORD, basic
from tests.mcp.conftest import refusal, structured

OPERATIONS = {
    "create_repository",
    "update_repository",
    "delete_repository",
    "invalidate_proxy_cache",
    "rebuild_search_index",
}
SECRET = "the-remote-password"


@pytest.fixture
async def administrator(make_user):
    return await make_user("root", roles=["admin"])


@pytest.fixture
async def token(administrator, make_token):
    return await make_token(administrator)


async def test_the_operations_are_shown_only_to_whoever_may_change_repositories(
    agent, administrator, make_user, make_token
):
    plain = await make_token(await make_user("dev"))
    reading = await make_token(administrator, "reads", scopes=["admin:*:read", "repository:*"])
    writing = await make_token(administrator, "writes")

    shown = {}
    for name, token in (("plain", plain), ("reading", reading), ("writing", writing)):
        async with agent(token) as client:
            shown[name] = {listed.name for listed in (await client.list_tools()).tools}

    assert shown["plain"] & OPERATIONS == set()
    assert shown["reading"] & OPERATIONS == set()
    assert shown["writing"] >= OPERATIONS


async def test_what_each_operation_says_of_itself(agent, token):
    async with agent(token) as client:
        hints = {
            listed.name: listed.annotations
            for listed in (await client.list_tools()).tools
            if listed.name in OPERATIONS
        }

    assert hints["delete_repository"].destructive_hint is True
    assert hints["create_repository"].idempotent_hint is False
    assert all(not hint.read_only_hint for hint in hints.values())
    assert all(hints[name].idempotent_hint for name in OPERATIONS - {"create_repository"})


async def test_a_proxy_is_made_of_its_formats_public_repository_unless_one_is_given(agent, token):
    async with agent(token) as client:
        central = structured(
            await client.call_tool(
                "create_repository", {"name": "central", "format": "maven", "type": "proxy"}
            )
        )
        choco = structured(
            await client.call_tool(
                "create_repository",
                {
                    "name": "choco",
                    "format": "nuget",
                    "type": "proxy",
                    "format_config": {"protocol": "v2"},
                },
            )
        )
        own = structured(
            await client.call_tool(
                "create_repository",
                {
                    "name": "mirror",
                    "format": "npm",
                    "type": "proxy",
                    "proxy": {"remote_url": "https://npm.example.org/", "blocked": True},
                },
            )
        )
        yum = await client.call_tool(
            "create_repository", {"name": "rocky", "format": "yum", "type": "proxy"}
        )

    assert central["proxy"]["remote_url"] == "https://repo1.maven.org/maven2"
    # As the server keeps a remote: without the slash at its end.
    assert choco["proxy"]["remote_url"] == "https://community.chocolatey.org/api/v2"
    assert (own["proxy"]["remote_url"], own["proxy"]["blocked"]) == (
        "https://npm.example.org",
        True,
    )
    assert refusal(yum).endswith(
        "- proxy.remote_url: This format has no public repository: give the remote's."
    )


async def test_hosted_repositories_and_groups_are_made_as_the_rest_api_makes_them(
    agent, token, client
):
    async with agent(token) as agent_client:
        hosted = structured(
            await agent_client.call_tool(
                "create_repository", {"name": "releases", "format": "maven", "type": "hosted"}
            )
        )
        group = structured(
            await agent_client.call_tool(
                "create_repository",
                {
                    "name": "maven-public",
                    "format": "maven",
                    "type": "group",
                    "members": ["releases"],
                },
            )
        )
        again = await agent_client.call_tool(
            "create_repository", {"name": "releases", "format": "maven", "type": "hosted"}
        )
        wrong = await agent_client.call_tool(
            "create_repository", {"name": "x", "format": "maven", "type": "mirror"}
        )

    assert hosted["hosted"]["deployment_policy"] == "disable_redeploy"  # releases, Maven's own
    assert group["group"]["members"] == ["releases"]
    rest = await client.get("/api/v1/repositories/maven-public", headers=basic("root", PASSWORD))
    assert rest.json() == group
    assert "conflict" in refusal(again)
    assert "type" in refusal(wrong)


@pytest.fixture
async def proxied(client, administrator):
    """`central`, a Maven proxy that signs in to its remote, and `releases`, hosted."""
    root = basic("root", PASSWORD)
    for made in [
        {
            "name": "central",
            "format": "maven",
            "type": "proxy",
            "proxy": {
                "remote_url": "http://remote.test/maven2",
                "remote_auth": {"type": "basic", "username": "robot", "secret": SECRET},
            },
        },
        {"name": "releases", "format": "maven", "type": "hosted"},
    ]:
        assert (
            await client.post("/api/v1/repositories", json=made, headers=root)
        ).status_code == 201


async def test_what_is_not_given_to_a_change_stays_as_it_is_the_secret_too(
    agent, token, proxied, sessionmaker
):
    async with agent(token) as client:
        blocked = structured(
            await client.call_tool(
                "update_repository", {"name": "central", "proxy": {"blocked": True}}
            )
        )
        offline = structured(
            await client.call_tool("update_repository", {"name": "releases", "online": False})
        )
        missing = await client.call_tool("update_repository", {"name": "nowhere", "online": True})

    assert blocked["proxy"]["blocked"] is True
    assert blocked["proxy"]["remote_url"] == "http://remote.test/maven2"
    assert blocked["proxy"]["remote_auth"] == {
        "type": "basic",
        "username": "robot",
        "has_secret": True,
    }
    assert offline["online"] is False
    assert offline["hosted"]["deployment_policy"] == "disable_redeploy"
    assert refusal(missing).endswith("not_found: No such repository.")


async def test_a_groups_members_are_changed_all_at_once_in_their_order(agent, token, proxied):
    async with agent(token) as client:
        made = structured(
            await client.call_tool(
                "create_repository",
                {"name": "all", "format": "maven", "type": "group", "members": ["releases"]},
            )
        )
        changed = structured(
            await client.call_tool(
                "update_repository", {"name": "all", "members": ["central", "releases"]}
            )
        )

    assert made["group"]["members"] == ["releases"]
    assert changed["group"]["members"] == ["central", "releases"]


async def test_a_proxys_cache_is_cleared_an_index_gone_through_and_a_repository_deleted(
    agent, token, proxied, client
):
    async with agent(token) as agent_client:
        cleared = structured(
            await agent_client.call_tool("invalidate_proxy_cache", {"name": "central"})
        )
        rebuilt = structured(
            await agent_client.call_tool("rebuild_search_index", {"name": "releases"})
        )
        deleted = structured(
            await agent_client.call_tool("delete_repository", {"name": "releases"})
        )
        again = await agent_client.call_tool("delete_repository", {"name": "releases"})

    assert cleared == {"repository": "central", "done": "invalidated"}
    assert rebuilt == {"files": 0, "moved": 0, "components": 0, "removed": 0}
    assert deleted == {"repository": "releases", "done": "deleted"}
    assert refusal(again).endswith("not_found: No such repository.")
    gone = await client.get("/api/v1/repositories/releases", headers=basic("root", PASSWORD))
    assert gone.status_code == 404


async def test_an_operation_a_caller_may_not_do_is_no_tool_of_theirs(agent, make_user, make_token):
    token = await make_token(await make_user("dev"))

    async with agent(token) as client:
        refused = await client.call_tool(
            "create_repository", {"name": "mine", "format": "raw", "type": "hosted"}
        )

    assert refusal(refused) == "Unknown tool: create_repository"
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/mcp/test_operations.py`
Expected: 7 failed, 1 passed: each operation is answered `Unknown tool: create_repository` (or its name), which `structured` refuses; the test that a caller who may not is told just that passes already.

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/mcp/operations.py`:

```python
"""Running repositories (spec 6.2): making, changing and deleting them, clearing a proxy's
cache, and going through a repository's index again. Each calls the REST route beside it,
with its permission: `admin:repositories:write`."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from megooarti.errors import ApiError
from megooarti.mcp.tools import (
    CHANGE,
    DESTRUCTIVE,
    WRITE,
    caller,
    database,
    holding,
    tool,
)
from megooarti.repositories import api as repositories_api
from megooarti.repositories import service
from megooarti.repositories.api import (
    GroupSettings,
    HostedIn,
    IndexRebuilt,
    NegativeCache,
    ProxyIn,
    RemoteAuthIn,
    RepositoryCreate,
    RepositoryOut,
    RepositoryUpdate,
)
from megooarti.repositories.formats import get_format

WRITE_REPOSITORIES = "admin:repositories:write"
Name = Annotated[str, Field(max_length=64)]


class ProxySettings(BaseModel):
    """A proxy's settings, as the REST API takes them; its remote, where none is given, is
    its format's public repository."""

    remote_url: str | None = Field(default=None, min_length=1, max_length=2048)
    content_max_age_minutes: int = Field(default=1440, ge=-1)
    metadata_max_age_minutes: int = Field(default=1440, ge=-1)
    negative_cache: NegativeCache = NegativeCache()
    remote_auth: RemoteAuthIn = RemoteAuthIn()
    blocked: bool = False
    auto_block: bool = True


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _shown(view: Any) -> RepositoryOut:
    return RepositoryOut.model_validate(view, from_attributes=True)


@tool(annotations=WRITE, shown_to=holding(WRITE_REPOSITORIES))
async def create_repository(
    name: Name,
    format: Annotated[str, Field(max_length=32, description="maven, npm, pypi, nuget, …")],
    type: Literal["hosted", "proxy", "group"],
    online: bool = True,
    blob_store: Annotated[str | None, Field(max_length=64)] = None,
    hosted: HostedIn | None = None,
    proxy: ProxySettings | None = None,
    members: list[str] | None = None,
    format_config: dict[str, Any] | None = None,
) -> RepositoryOut:
    """Make a repository: hosted (packages are pushed to it), a proxy of a remote (which it
    fetches from, and keeps), or a group of others (`members`, in the order they are
    asked). A proxy whose `proxy.remote_url` is not given proxies its format's public
    repository (Maven Central, the npm registry, PyPI, Docker Hub, Debian, Alpine,
    nuget.org). `format_config` is the format's own: an APT repository's `suite`, a
    NuGet proxy's `protocol`. Gives its settings."""
    config = format_config or {}
    if type == "proxy":
        given = proxy or ProxySettings()
        remote = given.remote_url
        if remote is None:
            handler = get_format(format)
            remote = None if handler is None else handler.public_remote(config)
        if remote is None:
            raise _invalid(
                "proxy.remote_url", "This format has no public repository: give the remote's."
            )
        proxy_in: ProxyIn | None = ProxyIn(**{**given.model_dump(), "remote_url": remote})
    else:
        proxy_in = None
    body = RepositoryCreate(
        name=name,
        format=format,
        type=type,
        online=online,
        blob_store=blob_store,
        hosted=hosted,
        proxy=proxy_in,
        group=GroupSettings(members=members or []) if type == "group" else None,
        format_config=config,
    )
    principal, request = caller().principal, caller().request
    async with database() as db:
        made = await repositories_api.create_repository(body, request, principal, db)
    return _shown(made)


def _merged(held: dict[str, Any] | None, given: dict[str, Any] | None) -> dict[str, Any] | None:
    """Settings as they are, with what was given in their place, one level down too."""
    if given is None:
        return held
    merged = dict(held or {})
    for key, value in given.items():
        inner = merged.get(key)
        merged[key] = (
            {**inner, **value} if isinstance(inner, dict) and isinstance(value, dict) else value
        )
    return merged


@tool(annotations=CHANGE, shown_to=holding(WRITE_REPOSITORIES))
async def update_repository(
    name: Name,
    online: bool | None = None,
    members: list[str] | None = None,
    hosted: dict[str, Any] | None = None,
    proxy: dict[str, Any] | None = None,
    format_config: dict[str, Any] | None = None,
) -> RepositoryOut:
    """Change a repository: take it online or offline, give a group its `members` (all of
    them, in the order they are asked), or change some of its settings, given as
    `repository_details` shows them (`proxy: {"blocked": true}`, `hosted:
    {"deployment_policy": "disable_redeploy"}`): what is not given stays as it is. A
    proxy's stored secret is kept unless `proxy.remote_auth.secret` is given. Its name,
    format, type and blob store do not change. Gives its settings."""
    principal, request = caller().principal, caller().request
    async with database() as db:
        held = await service.get_repository(db, name)
        if held is None:
            raise ApiError(404, "not_found", "No such repository.")
        current = _shown(await service.describe(db, held))
        now = current.model_dump(mode="json")
        current_proxy = now["proxy"]
        if current_proxy is not None:
            # A secret is never shown: one that is not given is the one stored.
            auth = current_proxy["remote_auth"]
            current_proxy["remote_auth"] = {"type": auth["type"], "username": auth["username"]}
        body = RepositoryUpdate(
            online=current.online if online is None else online,
            hosted=_merged(now["hosted"], hosted),
            proxy=_merged(current_proxy, proxy),
            group=GroupSettings(members=members) if members is not None else current.group,
            format_config=_merged(now["format_config"], format_config) or {},
        )
        changed = await repositories_api.update_repository(name, body, request, principal, db)
    return _shown(changed)


class Done(BaseModel):
    repository: str
    done: str  # what was done


@tool(annotations=DESTRUCTIVE, shown_to=holding(WRITE_REPOSITORIES))
async def delete_repository(name: Name) -> Done:
    """Delete a repository and everything in it. It cannot be undone. A group that has it
    as a member must be changed first."""
    async with database() as db:
        await repositories_api.delete_repository(name, caller().principal, db)
    return Done(repository=name, done="deleted")


@tool(annotations=CHANGE, shown_to=holding(WRITE_REPOSITORIES))
async def invalidate_proxy_cache(name: Name) -> Done:
    """Make a proxy ask its remote again: what it keeps is not trusted until it is. Its
    files stay; it is not blocked any more for its failures."""
    async with database() as db:
        await repositories_api.invalidate_cache(name, caller().principal, db)
    return Done(repository=name, done="invalidated")


@tool(annotations=CHANGE, shown_to=holding(WRITE_REPOSITORIES))
async def rebuild_search_index(name: Name) -> IndexRebuilt:
    """Go through a repository again: every file to its package, every package the words it
    is found by. It repairs what search and browsing say of it; repeated, it changes
    nothing more."""
    principal, request = caller().principal, caller().request
    async with database() as db:
        return await repositories_api.rebuild_index(name, request, principal, db)
```

Change `backend/src/megooarti/mcp/server.py`:

```diff
@@ -9,7 +9,13 @@ from mcp.server.mcpserver.exceptions import ToolError
 from mcp.types import Tool
 
 from megooarti import __version__
-from megooarti.mcp import packages, repositories, system, tools  # noqa: F401  (register tools)
+from megooarti.mcp import (  # noqa: F401  (they register their tools)
+    operations,
+    packages,
+    repositories,
+    system,
+    tools,
+)
 
 # A session manager is made for each request (see `endpoint`): its start and stop are
 # not news.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/mcp`
Expected: 73 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(mcp): make, change and delete repositories, clear a proxy's cache, rebuild an index"
```

---

### Task 5: Deleting content

**Files:**
- Modify: `backend/src/megooarti/mcp/packages.py`, `backend/src/megooarti/mcp/operations.py`
- Test: `backend/tests/mcp/test_deletes.py`

**Interfaces:**
- Consumes: Task 3's `DESTRUCTIVE`, `may_somewhere`; Task 4's `operations.Name`; 14a's `packages._search`, `_one_package`, `_invalid`; `content_api.get_component`, `delete_component`, `delete_asset`, `delete_folder`.
- Produces: `packages.component_named(db, repository, namespace, name, version) -> uuid.UUID` (which `package_details` now uses); the tools `delete_component` and `delete_path`; `operations.Deleted`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/mcp/test_deletes.py`:

```python
"""Deleting content through MCP (spec 6.2): a version of a package, a file, a folder;
shown to whoever may delete in some repository, refused where they may not."""

import pytest

from megooarti.repositories import service
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.mcp.conftest import refusal, structured
from tests.repositories.maven.conftest import create

DELETES = {"delete_component", "delete_path"}


@pytest.fixture
async def content(client, db, make_user):
    """`files` (raw) with `top.txt`, `docs/a.txt`, `docs/b.txt` and `docs/sub/c.txt`;
    `releases` (Maven) with com.acme:app 1.0 and 2.0. Gives the administrator."""
    administrator = await make_user("root", roles=["admin"])
    await service.create_repository(
        db,
        name="files",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=None,
        proxy=None,
        group=None,
        format_config={},
    )
    await create(db, "releases")
    root = basic("root", PASSWORD)
    for path in ["top.txt", "docs/a.txt", "docs/b.txt", "docs/sub/c.txt"]:
        assert (
            await client.put(f"/repository/files/{path}", content=b"x", headers=root)
        ).is_success
    for version in ("1.0", "2.0"):
        stem = f"/repository/releases/com/acme/app/{version}/app-{version}"
        assert (await client.put(f"{stem}.jar", content=b"PK", headers=root)).is_success
        assert (await client.put(f"{stem}.pom", content=b"<project/>", headers=root)).is_success
    return administrator


@pytest.fixture
async def token(content, make_token):
    return await make_token(content)


async def test_the_deletes_are_shown_to_whoever_may_delete_in_some_repository(
    agent, content, make_user, make_token, db
):
    await roles.create_role(db, "files-deleters", "", ["repository:raw:files:delete"], [])
    await db.commit()
    deleter = await make_token(await make_user("dana", roles=["files-deleters"]))
    reader = await make_token(content, "reads", scopes=["repository:*:*:read"])

    async with agent(deleter) as client:
        theirs = {listed.name for listed in (await client.list_tools()).tools}
    async with agent(reader) as client:
        readers = {listed.name for listed in (await client.list_tools()).tools}

    assert theirs >= DELETES
    assert readers & DELETES == set()


async def test_a_file_and_a_folder_with_all_under_it_are_deleted(agent, token):
    async with agent(token) as client:
        file = structured(
            await client.call_tool("delete_path", {"repository": "files", "path": "top.txt"})
        )
        folder = structured(
            await client.call_tool("delete_path", {"repository": "files", "path": "docs"})
        )
        missing = await client.call_tool("delete_path", {"repository": "files", "path": "docs"})
        left = structured(await client.call_tool("browse", {"repository": "files"}))

    assert file == {"repository": "files", "deleted": 1, "skipped": 0}
    assert folder == {"repository": "files", "deleted": 3, "skipped": 0}
    assert refusal(missing).endswith("not_found: No such file or folder.")
    assert left["items"] == []


async def test_a_version_of_a_package_is_deleted_by_its_name_and_the_others_stay(agent, token):
    async with agent(token) as client:
        deleted = structured(
            await client.call_tool(
                "delete_component",
                {
                    "repository": "releases",
                    "namespace": "com.acme",
                    "name": "app",
                    "version": "1.0",
                },
            )
        )
        versions = structured(
            await client.call_tool(
                "package_versions", {"format": "maven", "namespace": "com.acme", "name": "app"}
            )
        )
        again = await client.call_tool(
            "delete_component",
            {"repository": "releases", "namespace": "com.acme", "name": "app", "version": "1.0"},
        )

    assert deleted == {"repository": "releases", "deleted": 2, "skipped": 0}
    assert [one["version"] for one in versions["versions"]["items"]] == ["2.0"]
    assert refusal(again).endswith("not_found: No such component.")


async def test_a_delete_where_the_caller_may_not_delete_is_refused(
    agent, content, token, make_user, make_token, db
):
    await roles.create_role(db, "files-deleters", "", ["repository:raw:files:delete"], [])
    await roles.create_role(db, "maven-readers", "", ["repository:maven:releases:browse"], [])
    await db.commit()
    dana = await make_token(await make_user("dana", roles=["files-deleters", "maven-readers"]))

    async with agent(dana) as client:
        refused = await client.call_tool(
            "delete_path", {"repository": "releases", "path": "com/acme/app/1.0/app-1.0.jar"}
        )
    async with agent(token) as client:
        outside = await client.call_tool(
            "delete_path", {"repository": "files", "path": "docs/../../etc"}
        )

    assert refusal(refused).endswith("forbidden: You do not have permission to do this.")
    assert refusal(outside).endswith(
        "invalid_path: The path is not valid: it has an empty, '.' or '..' segment."
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/mcp/test_deletes.py`
Expected: 4 failed: no delete is shown (`assert {'browse', …} >= {'delete_component', 'delete_path'}`), and each call is `Unknown tool`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/mcp/packages.py`:

```diff
@@ -295,6 +295,30 @@ class PackageDetails(BaseModel):
     truncated: bool
 
 
+async def component_named(
+    db: AsyncSession, repository: str, namespace: str | None, name: str, version: str
+) -> uuid.UUID:
+    """The id of the one version of one package that these name in a repository: found
+    by the search, among any number. Raises 422 where they name none or several, 404."""
+    if not name or not version or "*" in name + version:
+        raise _invalid(
+            "component_id", "Give `component_id`, or `name` and `version` (without `*`)."
+        )
+    found, _ = await _search(
+        db,
+        repository=repository,
+        namespace=namespace or "",
+        name=name,
+        version=version,
+        limit=200,
+        offset=0,
+    )
+    matching = _one_package([one for one in found if one.version == version], name, namespace)
+    if not matching:
+        raise ApiError(404, "not_found", "No such component.")
+    return matching[0].id
+
+
 @tool()
 async def package_details(
     repository: RepositoryName,
@@ -315,25 +339,7 @@ async def package_details(
         if members is not None:
             raise _not_browsable(members, "Look in")
         if component_id is None:
-            if not name or not version or "*" in name + version:
-                raise _invalid(
-                    "component_id", "Give `component_id`, or `name` and `version` (without `*`)."
-                )
-            found, _ = await _search(
-                db,
-                repository=repository,
-                namespace=namespace or "",
-                name=name,
-                version=version,
-                limit=200,
-                offset=0,
-            )
-            matching = _one_package(
-                [one for one in found if one.version == version], name, namespace
-            )
-            if not matching:
-                raise ApiError(404, "not_found", "No such component.")
-            component_id = matching[0].id
+            component_id = await component_named(db, repository, namespace, name, version)
         detail = await content_api.get_component(repository, component_id, request, principal, db)
         held = await service.get_repository(db, repository)
         paths = [entry.path for entry in detail.files if entry.kind == "file"]
```

Change `backend/src/megooarti/mcp/operations.py`:

```diff
@@ -1,12 +1,15 @@
 """Running repositories (spec 6.2): making, changing and deleting them, clearing a proxy's
-cache, and going through a repository's index again. Each calls the REST route beside it,
-with its permission: `admin:repositories:write`."""
+cache, going through a repository's index again, and deleting what is in one. Each calls
+the REST route beside it, with its permission: `admin:repositories:write`, or `delete` on
+the repository whose content it deletes."""
 
+import uuid
 from typing import Annotated, Any, Literal
 
 from pydantic import BaseModel, Field
 
 from megooarti.errors import ApiError
+from megooarti.mcp.packages import component_named
 from megooarti.mcp.tools import (
     CHANGE,
     DESTRUCTIVE,
@@ -14,10 +17,11 @@ from megooarti.mcp.tools import (
     caller,
     database,
     holding,
+    may_somewhere,
     tool,
 )
 from megooarti.repositories import api as repositories_api
-from megooarti.repositories import service
+from megooarti.repositories import content_api, service
 from megooarti.repositories.api import (
     GroupSettings,
     HostedIn,
@@ -188,3 +192,59 @@ async def rebuild_search_index(name: Name) -> IndexRebuilt:
     principal, request = caller().principal, caller().request
     async with database() as db:
         return await repositories_api.rebuild_index(name, request, principal, db)
+
+
+# --- Deleting content -----------------------------------------------------------------
+
+
+class Deleted(BaseModel):
+    repository: str
+    deleted: int  # files
+    skipped: int  # files the format keeps itself, which go with what they describe
+
+
+@tool(annotations=DESTRUCTIVE, shown_to=may_somewhere("delete"))
+async def delete_component(
+    repository: Name,
+    component_id: uuid.UUID | None = None,
+    namespace: Annotated[str | None, Field(max_length=256)] = None,
+    name: Annotated[str, Field(max_length=256)] = "",
+    version: Annotated[str, Field(max_length=256)] = "",
+) -> Deleted:
+    """Delete one version of a package from a repository: every file of it, each as the
+    format's own client would delete it. Give `component_id` as `search_packages` gave
+    it, or `name` and `version` (and `namespace` where the format has them). It cannot be
+    undone; a proxy fetches it again when it is next asked for."""
+    principal, request = caller().principal, caller().request
+    async with database() as db:
+        if component_id is None:
+            component_id = await component_named(db, repository, namespace, name, version)
+        held = await content_api.get_component(repository, component_id, request, principal, db)
+        files = [entry for entry in held.files if entry.kind == "file"]
+        await content_api.delete_component(repository, component_id, request, principal, db)
+    return Deleted(repository=repository, deleted=len(files), skipped=0)
+
+
+@tool(annotations=DESTRUCTIVE, shown_to=may_somewhere("delete"))
+async def delete_path(
+    repository: Name, path: Annotated[str, Field(min_length=1, max_length=1024)]
+) -> Deleted:
+    """Delete a file, or a folder and everything under it, from a repository, each file as
+    the format's own client would. Files the format keeps itself (an index, a checksum)
+    are skipped: they go with what they describe. It cannot be undone."""
+    principal, request = caller().principal, caller().request
+    async with database() as db:
+        try:
+            await content_api.delete_asset(repository, path, request, principal, db)
+            return Deleted(repository=repository, deleted=1, skipped=0)
+        except ApiError as error:
+            if error.code != "not_found" or error.message != "No such file.":
+                raise
+        deleted = skipped = 0
+        after: str | None = ""
+        while after is not None:
+            done = await content_api.delete_folder(repository, path, request, after, principal, db)
+            deleted, skipped, after = deleted + done.deleted, skipped + done.skipped, done.next
+    if deleted == skipped == 0:
+        raise ApiError(404, "not_found", "No such file or folder.")
+    return Deleted(repository=repository, deleted=deleted, skipped=skipped)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/mcp`
Expected: 77 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(mcp): delete a version of a package, a file or a folder"
```

---

### Task 6: Administering users, tokens and roles

**Files:**
- Create: `backend/src/megooarti/mcp/administration.py`
- Modify: `backend/src/megooarti/mcp/server.py`
- Test: `backend/tests/mcp/test_administration.py`

**Interfaces:**
- Consumes: Task 3's annotations and `holding`; 14a's `results.Limit`, `Cursor`, `Page`, `offset_of`, `page_of`; `security.api.users`' `list_users`, `get_user`, `create_user`, `update_user`, `delete_user`, `list_user_tokens`, `revoke_user_token`, `UserCreate`, `UserUpdate`, `UserOut`; `security.api.roles`' `list_roles`, `get_role`, `create_role`, `update_role`, `delete_role`, `RoleCreate`, `RoleContent`, `RoleOut`; `security.api.schemas.TokenInfo`; `users.get_user_by_username`, `tokens.list_tokens`.
- Produces: the tools `list_users`, `user_details`, `create_user`, `update_user`, `delete_user`, `revoke_token`, `list_roles`, `create_role`, `update_role`, `delete_role`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/mcp/test_administration.py`:

```python
"""Administering accounts through MCP (spec 6.2): users, their tokens, and roles, each
shown only to whoever holds its permission, each named as people name it."""

import pytest

from megooarti.security import roles
from tests.mcp.conftest import refusal, structured

READING = {"list_users", "user_details", "list_roles"}
WRITING = {
    "create_user",
    "update_user",
    "delete_user",
    "revoke_token",
    "create_role",
    "update_role",
    "delete_role",
}
MCP = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


@pytest.fixture
async def administrator(make_user):
    return await make_user("root", roles=["admin"])


@pytest.fixture
async def token(administrator, make_token):
    return await make_token(administrator)


async def test_each_tool_is_shown_to_whoever_holds_its_permission(
    agent, administrator, make_user, make_token, db
):
    await roles.create_role(db, "user-readers", "", ["admin:users:read"], [])
    await db.commit()
    reader = await make_token(await make_user("dana", roles=["user-readers"]))
    everything = await make_token(administrator)

    async with agent(reader) as client:
        theirs = {listed.name for listed in (await client.list_tools()).tools}
    async with agent(everything) as client:
        ours = {listed.name for listed in (await client.list_tools()).tools}

    assert theirs & (READING | WRITING) == {"list_users", "user_details"}
    assert ours >= READING | WRITING


async def test_a_user_is_made_with_a_password_they_must_change_and_listed(agent, token):
    async with agent(token) as client:
        made = structured(
            await client.call_tool(
                "create_user",
                {
                    "username": "dev",
                    "display_name": "Dev",
                    "password": "a password of the right length",
                    "email": "dev@example.org",
                    "roles": ["admin"],
                },
            )
        )
        listed = structured(await client.call_tool("list_users", {}))
        wrong = await client.call_tool(
            "create_user", {"username": "no spaces", "display_name": "X", "password": "x" * 20}
        )

    assert (made["username"], made["must_change_password"], made["roles"]) == (
        "dev",
        True,
        ["admin"],
    )
    assert [user["username"] for user in listed["items"]] == ["admin", "anonymous", "dev", "root"]
    assert "username" in refusal(wrong)


async def test_a_user_is_changed_only_in_what_is_given(agent, token, make_user):
    await make_user("dev")

    async with agent(token) as client:
        changed = structured(
            await client.call_tool("update_user", {"username": "dev", "status": "disabled"})
        )
        renamed = structured(
            await client.call_tool("update_user", {"username": "dev", "display_name": "D. Ev"})
        )
        themselves = await client.call_tool(
            "update_user", {"username": "root", "status": "disabled"}
        )

    assert changed["status"] == "disabled"
    assert (renamed["status"], renamed["display_name"]) == ("disabled", "D. Ev")
    assert refusal(themselves).endswith("self_protected: You cannot disable your own account.")


async def test_a_users_tokens_are_shown_by_name_never_their_values_and_revoked(
    agent, token, make_user, make_token, client
):
    dev = await make_user("dev")
    theirs = await make_token(dev, "laptop")

    async with agent(token) as agent_client:
        details = structured(await agent_client.call_tool("user_details", {"username": "dev"}))
        revoked = structured(
            await agent_client.call_tool("revoke_token", {"username": "dev", "token": "laptop"})
        )
        missing = await agent_client.call_tool(
            "revoke_token", {"username": "dev", "token": "laptop"}
        )

    assert [one["name"] for one in details["tokens"]] == ["laptop"]
    assert theirs.startswith(details["tokens"][0]["display_prefix"])
    assert theirs not in str(details)
    assert revoked == {"deleted": "laptop"}
    assert refusal(missing).endswith("not_found: No such token.")
    after = await client.post(
        "/mcp", json=LIST_TOOLS, headers=MCP | {"Authorization": f"Bearer {theirs}"}
    )
    assert after.status_code == 401


async def test_who_may_read_users_but_not_tokens_is_not_shown_tokens(
    agent, administrator, make_user, make_token
):
    await make_user("dev")
    scoped = await make_token(administrator, "users-only", scopes=["admin:users:read"])

    async with agent(scoped) as client:
        details = structured(await client.call_tool("user_details", {"username": "dev"}))

    assert details["tokens"] is None


async def test_a_user_is_deleted_but_not_oneself(agent, token, make_user):
    await make_user("dev")

    async with agent(token) as client:
        gone = structured(await client.call_tool("delete_user", {"username": "dev"}))
        again = await client.call_tool("delete_user", {"username": "dev"})
        themselves = await client.call_tool("delete_user", {"username": "root"})

    assert gone == {"deleted": "dev"}
    assert refusal(again).endswith("not_found: No such user.")
    assert refusal(themselves).endswith("self_protected: You cannot delete your own account.")


async def test_a_role_is_made_changed_in_what_is_given_and_deleted(agent, token):
    async with agent(token) as client:
        made = structured(
            await client.call_tool(
                "create_role",
                {
                    "name": "maven-readers",
                    "description": "Read Maven",
                    "permissions": ["repository:maven:*:read"],
                },
            )
        )
        changed = structured(
            await client.call_tool(
                "update_role",
                {"name": "maven-readers", "permissions": ["repository:maven:*:browse"]},
            )
        )
        listed = structured(await client.call_tool("list_roles", {}))
        gone = structured(await client.call_tool("delete_role", {"name": "maven-readers"}))
        builtin = await client.call_tool("delete_role", {"name": "admin"})

    assert made["permissions"] == ["repository:maven:*:read"]
    assert (changed["description"], changed["permissions"]) == (
        "Read Maven",
        ["repository:maven:*:browse"],
    )
    assert "maven-readers" in [role["name"] for role in listed["items"]]
    assert gone == {"deleted": "maven-readers"}
    assert refusal(builtin).endswith("builtin_protected: Built-in roles cannot be deleted.")
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/mcp/test_administration.py`
Expected: 7 failed: each call is answered `Unknown tool: list_users` (or its name).

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/mcp/administration.py`:

```python
"""Administering accounts (spec 6.2): users, their API tokens, and roles. Each calls the
REST route beside it, with its permission, and names a user by their user name, a token
by its name and a role by its name (E2). No tool makes a token or sets a password but
one its user must change at their first sign-in (D4 of the identity-access spec)."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.mcp.results import Cursor, Limit, Page, offset_of, page_of
from megooarti.mcp.tools import CHANGE, DESTRUCTIVE, READ, WRITE, caller, database, holding, tool
from megooarti.pagination import PageParams
from megooarti.security import tokens, users
from megooarti.security.api import roles as roles_api
from megooarti.security.api import users as users_api
from megooarti.security.api.roles import RoleContent, RoleCreate, RoleOut
from megooarti.security.api.schemas import TokenInfo
from megooarti.security.api.users import UserCreate, UserOut, UserUpdate

Username = Annotated[str, Field(max_length=64)]
RoleName = Annotated[str, Field(max_length=64)]


async def _user_id(db: AsyncSession, username: str) -> uuid.UUID:
    found = await users.get_user_by_username(db, username)
    if found is None:
        raise ApiError(404, "not_found", "No such user.")
    return found.id


def _user(view: object) -> UserOut:
    return UserOut.model_validate(view, from_attributes=True)


def _role(view: object) -> RoleOut:
    return RoleOut.model_validate(view, from_attributes=True)


# --- Users ----------------------------------------------------------------------------


@tool(annotations=READ, shown_to=holding("admin:users:read"))
async def list_users(limit: Limit = 50, cursor: Cursor = None) -> Page[UserOut]:
    """The users, by user name: each one's name, email, status (active or disabled),
    roles, and when they last signed in."""
    offset = offset_of(cursor)
    async with database() as db:
        listed = await users_api.list_users(
            PageParams(limit=limit, offset=offset), caller().principal, db
        )
    items = [_user(one) for one in listed["items"]]
    return page_of(items, listed["total"], offset, limit)


class UserDetails(BaseModel):
    user: UserOut
    # Their API tokens: names, first characters, scopes, expiry, last use; never a value.
    # Null to those who may not read tokens.
    tokens: list[TokenInfo] | None


@tool(annotations=READ, shown_to=holding("admin:users:read"))
async def user_details(username: Username) -> UserDetails:
    """One user: their account and roles, and, to those who may read tokens, their API
    tokens (never a token's value)."""
    principal = caller().principal
    async with database() as db:
        user_id = await _user_id(db, username)
        view = await users_api.get_user(user_id, principal, db)
        held = None
        if principal.allows("admin:tokens:read"):
            listed = await users_api.list_user_tokens(
                user_id, PageParams(limit=200, offset=0), principal, db
            )
            held = [TokenInfo.model_validate(one, from_attributes=True) for one in listed["items"]]
    return UserDetails(user=_user(view), tokens=held)


@tool(annotations=WRITE, shown_to=holding("admin:users:write"))
async def create_user(
    username: Annotated[str, Field(pattern=r"^[A-Za-z0-9._@-]{1,64}$")],
    display_name: Annotated[str, Field(min_length=1, max_length=128)],
    password: Annotated[str, Field(max_length=1024)],
    email: Annotated[str | None, Field(max_length=254)] = None,
    roles: list[str] | None = None,
) -> UserOut:
    """Make a user with these roles. The password is one they must change when they first
    sign in: give it to them by a way of your own."""
    body = UserCreate(
        username=username,
        display_name=display_name,
        email=email,
        password=password,
        roles=roles or [],
        must_change_password=True,
    )
    async with database() as db:
        return _user(await users_api.create_user(body, caller().principal, db))


@tool(annotations=CHANGE, shown_to=holding("admin:users:write"))
async def update_user(
    username: Username,
    display_name: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    email: Annotated[str | None, Field(max_length=254)] = None,
    status: Literal["active", "disabled"] | None = None,
    roles: list[str] | None = None,
) -> UserOut:
    """Change a user: their name, email, status (`disabled` stops them signing in, and
    their tokens working), or roles (all of them: what they hold is replaced). What is
    not given stays as it is. You cannot disable yourself."""
    given = {
        "display_name": display_name,
        "email": email,
        "status": status,
        "roles": roles,
    }
    body = UserUpdate(**{name: value for name, value in given.items() if value is not None})
    async with database() as db:
        user_id = await _user_id(db, username)
        return _user(await users_api.update_user(user_id, body, caller().principal, db))


class Gone(BaseModel):
    deleted: str  # what is gone: the user, the token or the role, by its name


@tool(annotations=DESTRUCTIVE, shown_to=holding("admin:users:write"))
async def delete_user(username: Username) -> Gone:
    """Delete a user, with their tokens. It cannot be undone; disabling them (with
    `update_user`) can be. You cannot delete yourself, nor the last administrator."""
    async with database() as db:
        user_id = await _user_id(db, username)
        await users_api.delete_user(user_id, caller().principal, db)
    return Gone(deleted=username)


@tool(annotations=DESTRUCTIVE, shown_to=holding("admin:tokens:write"))
async def revoke_token(username: Username, token: Annotated[str, Field(max_length=100)]) -> Gone:
    """Revoke a user's API token, by its name as `user_details` shows it: whatever signed in
    with it is refused from then on."""
    async with database() as db:
        user_id = await _user_id(db, username)
        listed, _ = await tokens.list_tokens(db, user_id, 200, 0)
        found = next((one for one in listed if one.name == token), None)
        if found is None:
            raise ApiError(404, "not_found", "No such token.")
        await users_api.revoke_user_token(user_id, found.id, caller().principal, db)
    return Gone(deleted=token)


# --- Roles ----------------------------------------------------------------------------


@tool(annotations=READ, shown_to=holding("admin:roles:read"))
async def list_roles(limit: Limit = 50, cursor: Cursor = None) -> Page[RoleOut]:
    """The roles: each one's permissions (patterns such as `repository:maven:releases:read`,
    `admin:users:write`, `*`) and the roles it holds."""
    offset = offset_of(cursor)
    async with database() as db:
        listed = await roles_api.list_roles(
            PageParams(limit=limit, offset=offset), caller().principal, db
        )
    items = [_role(one) for one in listed["items"]]
    return page_of(items, listed["total"], offset, limit)


@tool(annotations=WRITE, shown_to=holding("admin:roles:write"))
async def create_role(
    name: RoleName,
    description: Annotated[str, Field(max_length=255)] = "",
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
) -> RoleOut:
    """Make a role of permissions (`repository:<format>:<repository>:<action>`, where the
    action is browse, read, add, edit or delete; `admin:<area>:read` or `write`; `*` for
    any one part) and of other roles it holds."""
    body = RoleCreate(
        name=name, description=description, permissions=permissions or [], roles=roles or []
    )
    async with database() as db:
        return _role(await roles_api.create_role(body, caller().principal, db))


@tool(annotations=CHANGE, shown_to=holding("admin:roles:write"))
async def update_role(
    name: RoleName,
    description: Annotated[str | None, Field(max_length=255)] = None,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
) -> RoleOut:
    """Change a role: its description, its permissions (all of them: they are replaced) or
    the roles it holds. What is not given stays as it is. A change that would leave no
    administrator is refused."""
    principal = caller().principal
    async with database() as db:
        current = _role(await roles_api.get_role(name, principal, db))
        body = RoleContent(
            description=current.description if description is None else description,
            permissions=current.permissions if permissions is None else permissions,
            roles=current.roles if roles is None else roles,
        )
        return _role(await roles_api.update_role(name, body, principal, db))


@tool(annotations=DESTRUCTIVE, shown_to=holding("admin:roles:write"))
async def delete_role(name: RoleName) -> Gone:
    """Delete a role; whoever held it no longer has what it gave. The built-in roles stay."""
    async with database() as db:
        await roles_api.delete_role(name, caller().principal, db)
    return Gone(deleted=name)
```

Change `backend/src/megooarti/mcp/server.py`:

```diff
@@ -10,6 +10,7 @@ from mcp.types import Tool
 
 from megooarti import __version__
 from megooarti.mcp import (  # noqa: F401  (they register their tools)
+    administration,
     operations,
     packages,
     repositories,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/mcp`
Expected: 84 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(mcp): administer users, their tokens and roles, each by its name"
```

---

### Task 7: The guide, and what the plan settled

**Files:**
- Modify: `docs/mcp.md`, `docs/superpowers/specs/2026-10-18-mcp-design.md`

**Interfaces:**
- Consumes: everything above, as it is.
- Produces: the guide's table of the tools that change things, with their permissions; the spec's "Settled while building plan 14b".

- [ ] **Step 1: Write the guide and the spec's rows**

Change `docs/mcp.md`:

```diff
@@ -18,7 +18,8 @@ signs in to `/mcp`: not a password, not the web UI's session, and not anonymous
 Give an agent a token of its own, with the scopes it needs, and an expiry. For an agent
 that only reads, `repository:*:*:browse` and `repository:*:*:read`. The token's
 scopes narrow what the agent may do, and what it is shown: a tool it could not use is
-not listed to it.
+not listed to it. An agent that runs the registry needs a token of someone who may, with
+the `admin:` permissions of what it is to do.
 
 ## Connecting a client
 
@@ -77,6 +78,31 @@ yet.
 | `whoami` | Who the agent acts as, what they may do, and the token's scopes and expiry |
 | `system_status` | The version, and whether the server is ready |
 
+Tools that change things are shown only to an agent whose token may use them, and say
+so of themselves: a client asks you before an agent deletes anything.
+
+| Tool | What it does | Permission |
+| --- | --- | --- |
+| `create_repository` | Makes a hosted repository, a proxy or a group. A proxy given no remote proxies its format's public repository | `admin:repositories:write` |
+| `update_repository` | Takes a repository online or offline, gives a group its members, or changes some of its settings; what is not given stays as it is, a proxy's secret too | `admin:repositories:write` |
+| `delete_repository` | Deletes a repository and what is in it | `admin:repositories:write` |
+| `invalidate_proxy_cache` | Makes a proxy ask its remote again | `admin:repositories:write` |
+| `rebuild_search_index` | Goes through a repository's files and packages again | `admin:repositories:write` |
+| `delete_component` | Deletes a version of a package, each file as its format's client would | `delete` on the repository |
+| `delete_path` | Deletes a file, or a folder and all under it | `delete` on the repository |
+| `list_users`, `user_details` | The users, and one user's roles and tokens (never a token's value) | `admin:users:read`, and `admin:tokens:read` for the tokens |
+| `create_user` | Makes a user, with a password they must change when they first sign in | `admin:users:write` |
+| `update_user` | Changes a user's name, email, status or roles | `admin:users:write` |
+| `delete_user` | Deletes a user and their tokens | `admin:users:write` |
+| `revoke_token` | Revokes a user's API token, by its name | `admin:tokens:write` |
+| `list_roles` | The roles, with their permissions | `admin:roles:read` |
+| `create_role`, `update_role` | Makes or changes a role; what is not given to a change stays as it is | `admin:roles:write` |
+| `delete_role` | Deletes a role | `admin:roles:write` |
+
+No tool makes an API token, changes a password of one's own, or changes the server's
+settings (anonymous access, the base URL): those are for a person, in the web UI or the
+REST API. Users, tokens and roles are named by their names, as the web UI shows them.
+
 Each tool answers as the REST API does for the same caller: a list leaves out what the
 caller may not browse. Those who may read repositories' settings also get, from
 `list_repositories` and `repository_details`, a proxy's remote, its settings (never a
```

Change `docs/superpowers/specs/2026-10-18-mcp-design.md`:

```diff
@@ -238,6 +238,19 @@ Each plan ends with something an agent uses: 14a with a token and the read tools
 | M13 | A group named to `search_packages` or `package_details` is refused with `not_browsable`, naming the members the caller may browse; `package_versions` gives those members' versions. | The search route leaves groups out, so a group's search found nothing and said nothing; agents are given groups' addresses by the setup snippets. |
 | M14 | APT's prerelease is a `~` in the upstream version only; Maven's a qualifier after a separator or a number (`2.0M1`, `1.0rc1`), and a snapshot in any case. | A backport's revision (`1~bpo12+1`, docker-ce's `~ubuntu`) made every release a prerelease. |
 
+### Settled while building plan 14b
+
+| # | What | Why |
+| --- | --- | --- |
+| N1 | Each format says the public repository a proxy of it is made with where no remote is given (`Format.public_remotes`, by the protocol of its settings, `""` for none; `Format.public_remote(format_config)`), and `GET /api/v1/formats` gives them, with each format's types, to whoever is signed in. The web form takes them from there (in place of the form's own table). | One place says what a new proxy is given: the form and `create_repository` cannot differ (6.2). |
+| N2 | A tool that changes is shown to whoever holds its REST route's permission (`holding`); `delete_component` and `delete_path`, whose permission is a repository's, to whoever may delete in some repository by their permissions, narrowed by their token's scopes, or by what is public (`may_somewhere`). Each call is still checked against its repository. | E1 for a permission that is not one string; a tool shown to someone who may delete only elsewhere is refused there, as the REST route refuses. |
+| N3 | `Server._tool_input_schema` gives no schema of a tool the caller is not shown. | The SDK reads it to check a call's `Mcp-Param` headers before the call is made (the ruling of 14a's review). |
+| N4 | What a tool is given that the REST route's body would refuse is refused in the same words: `validation_error`, a line for each field. | The routes are called with bodies made in the tool; their models' errors are the API's (8.1). |
+| N5 | `update_repository` and `update_role` change only what is given: the rest is what there is, and a proxy's stored secret is kept unless a secret is given (the REST API's `PUT` takes them whole). `update_user`'s fields left out, or null, are not changed: an email is not cleared through MCP. | An agent that sends what it means to change does not undo the rest by leaving it out. |
+| N6 | `create_user` makes a user who must change their password when they first sign in, always. | 6.2: no tool sets a password a person did not choose (D4 of the identity-access spec). |
+| N7 | `delete_path` deletes a file at the path, or else everything under the folder, a thousand files at a time until there is none, each round committed; `No such file or folder.` where there is neither. `delete_component` takes a component's id, or its name and version as `package_details` does. | The REST API has a route for each; an agent names a path, as it does to `browse`. |
+| N8 | `revoke_token` revokes API tokens; an OAuth approval is revoked by plan 14c's tools and screens. | There are no approvals before 14c. |
+
 ## 13. Requirements
 
 | BRD | Where |
```

- [ ] **Step 2: Run every test**

Run (in `backend/`): `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`; then (in `frontend/`): `pnpm vitest run`
Expected: `413 files already formatted`, `All checks passed!`, 4039 passed, 2 skipped, 111 deselected; then 861 passed.

- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs: the MCP tools that run the registry, and their permissions; what plan 14b settled"
```
