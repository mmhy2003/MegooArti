# External Identity: Sign-in Sources and External Users Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An administrator keeps sign-in sources in an order, turns them and MegooArti's own users on and off (the built-in `admin` always signs in), and sets a default role every signed-in user has; a person of a source signs in with its password, is made a user at the first sign-in and brought up to date at each, their groups giving them roles; the web UI's Authentication screen does all of it, and a user's page says where they sign in.

**Architecture:** `security/sources.py` holds what every kind of source shares: a registry of kinds (`Kind`, `KINDS`) that plans 15b (OIDC), 15d (LDAP) and 15e (header) fill, the order sources are asked in, their sealed secrets, and `provision`, which makes or refreshes the user an identity is. Migration `0010` adds `auth_sources`, `users.source_id` and `external_id`, and `user_roles.granted_by`. `authenticate_password` (and with it HTTP Basic) asks a user's own source, or, for a name nobody has, each enabled source in order; `users.can_act` refuses the users of a source that is off, and ours while our own sign-in is off. `build_principal` adds the default role. `security/api/sources.py` serves `/api/v1/auth-sources`; `settings_api.py` serves the sign-in settings; the web UI gains `/admin/authentication`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy and Alembic, `secrets_box`; Next.js, React, TanStack Query, Vitest.

**Spec:** [docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md](../specs/2026-10-19-identity-audit-selectors-design.md): section 4, E1 to E5, sections 11 and 12, and the row of plan 15a in section 13.

## Decisions this plan settles

Task 4 writes these into the spec, as "Settled while building plan 15a".

| # | Decision | Reason |
| --- | --- | --- |
| S1 | Whether MegooArti's own users sign in is a setting, `local_sign_in` (on unless set), beside `default_role`. Both are read at `GET /api/v1/settings/sign-in` and changed at `PUT /api/v1/settings/local-sign-in` and `PUT /api/v1/settings/default-role`, under `admin:security`; `GET /api/v1/settings` is unchanged. | 4.1 makes the local source no row. Whoever keeps sign-in may not be given the base URL with it, nor need it. |
| S2 | While it is off, a user of ours other than the built-in `admin` is refused as a disabled user is: sign-in, session, Basic, API tokens, OAuth. It is turned off only while `admin` is active, has a password and holds full access (`409 last_administrator`); the check of who remains counts `admin` alone then. | E1, and 4.2's "refused as a disabled user is". Nobody can lock everyone out. |
| S3 | A user's source is `users.source_id` (the spec's `source`), with `external_id`; one user per `(source_id, external_id)`. Deleting a source disables its users and ends their sessions before the key is set null; their `external_id` stays, so they are a deleted source's users, not ours, and have no password. | 4.1, 4.3. A user of a deleted source must not become one of ours by the key's going. |
| S4 | A kind of source is a `sources.Kind` (`checked`, `password`, `test`, its `secrets`, `in_browser`, `takes_passwords`) registered in `sources.KINDS`. This plan registers none: a source can be made once 15b or 15d brings its kind, and until then `kind` is refused with what there is. The tests register kinds of their own. | Section 13: LDAP and OIDC are their own plans; what they share is here. |
| S5 | A source answers a name and a password with who they are, `unknown` (the next source is asked) or `refused` (nobody else is). A user of a source is asked of their own source alone, with their identity there, and is refused if it says another. | E3: the first that knows the name decides; a wrong password is not tried against every directory. |
| S6 | A user's name is what the source says, in lower case, a character a name may not hold made `-`. Where another user has it: `name@source` (the source's name made so too), then `-2`, `-3`. `__token__` and names shaped as a token are never given. The name is brought up to date at each sign-in, as the rest is. | 4.2, and names that the users' API and HTTP Basic take. |
| S7 | Groups are matched whatever their case. A mapped role that does not exist gives nothing; the mapping's roles are checked when it is saved (`422`). | Directories differ in case; section 11. |
| S8 | Each held role records who gave it (`granted_by`: `admin` or `source`). Roles an administrator sets on a user keep a source's role the source's, so the groups still decide it at the next sign-in. | E4. |
| S9 | The default role is added to the permissions of every signed-in principal (session, password, token, OAuth), not to a visitor's. Deleting the role clears the setting. | 4.1. A setting that names nothing would say what no one has. |
| S10 | A user of a source has no password here: setting one is refused, by an administrator or by them, with `409 external_user`. | E2. |
| S11 | `POST /api/v1/auth-sources/{id}/test` takes a name and a password, or nothing, needs `admin:security:write` (it reaches out), and says whether the source answered, who it says they are and the roles the mapping would give. Nobody is made or signed in by it. | 4.3, 14: a source is tested before it is enabled. |
| S12 | `GET /api/v1/auth/sources` lists the enabled sources of a kind signed in to in the browser, by id, name and kind only, paged. | 4.3. It is open: the sign-in screen asks it before anyone signs in. |
| S13 | A source's name is 1 to 64 letters, digits, spaces, `.`, `_` and `-`, beginning with a letter or a digit; not `local`; unique whatever its case. A source is made off, and last. `PUT` replaces all but its kind; a secret left out keeps the stored one. | Shown on the sign-in screen and in `name@source`; 14's "tested before it is enabled"; E5. |
| S14 | A source that cannot be asked answers `503 source_unavailable`, naming it, and is not counted as a failed sign-in. | Section 11. A directory that is down must not lock its users out for 15 minutes. |
| S15 | The Authentication screen lists the sources, turns them on and off, moves, tests and deletes them; the form that makes or edits one comes with its kind, in 15b (OIDC) and 15d (LDAP), whose settings it shows. | A source's settings are its kind's; this plan has no kind to show. |

## Global Constraints

- **The built-in `admin` always signs in with a password of MegooArti's own**, whatever sources are on or off (E1).
- **A user belongs to one source**, known there by an identity of its own; a user of a source has no password here (E2).
- **A password is checked against the user's own source; a name nobody has is asked of each enabled source in order, the first that knows it deciding** (E3). HTTP Basic follows the same rule.
- **Roles a group mapping gives are replaced at each sign-in; roles an administrator gives are kept** (E4).
- **Every secret of a source is sealed with `secrets_box.seal`, and shown to nobody again** (E5).
- **Sign-in through a source answers as a local one does**: `401 Invalid credentials.`, throttled alike; a source that cannot be reached answers `503 source_unavailable`, naming it (section 11).
- **The new permissions are `admin:security:read` and `admin:security:write`.** Every new list is paged.
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, with `MEGOOARTI_TEST_DATABASE_URL` set to your test database; `pnpm` commands in `frontend/`; `git` commands in the repository root.

## Review Focus

What could hurt a person using this most, and which test of this plan pins it.

1. **Everyone locked out by a source misconfigured, or by turning our own users off:** `admin` still signs in, and our own users cannot be turned off unless `admin` holds full access. Task 1: `test_with_our_own_sign_in_off_only_the_built_in_admin_signs_in`, `test_our_own_sign_in_stays_on_while_the_built_in_admin_has_no_full_access`.
2. **Somebody signing in as another person whose name they share** (one of ours and a directory's, or two directories'): a name that is somebody's is asked of their own source alone. Task 2: `test_a_name_one_of_our_own_has_is_checked_by_us_alone`, `test_a_user_of_a_source_is_asked_of_their_own_source_alone`.
3. **A wrong password tried against every directory in turn:** the first source that knows the name decides. Task 2: `test_a_name_nobody_has_is_asked_of_each_source_in_order_and_the_first_who_knows_decides`.
4. **The sessions and API tokens of a source's users working on after it is turned off or deleted:** refused as a disabled user's are. Task 2: `test_a_source_turned_off_signs_nobody_in_and_refuses_its_users`; Task 3: `test_deleting_a_source_disables_and_keeps_its_users`.
5. **A directory that is down locking its users out for 15 minutes:** it answers `503`, and no failure is counted. Task 2: `test_a_source_that_does_not_answer_is_named_and_counts_no_failure`.

---

### Task 1: The records, the default role, and our own users turned off

**Files:**
- Create: `backend/src/megooarti/migrations/versions/0010_add_sign_in_sources.py`
- Modify: `backend/src/megooarti/security/models.py`, `backend/src/megooarti/system/settings_store.py`, `backend/src/megooarti/security/users.py`, `backend/src/megooarti/security/roles.py`, `backend/src/megooarti/security/guards.py`, `backend/src/megooarti/security/authentication.py`, `backend/src/megooarti/system/settings_api.py`, `frontend/openapi.json` (written by a command), `docs/administration.md`
- Test: `backend/tests/security/test_sign_in_settings.py`; modify `backend/tests/test_settings_store.py`

**Interfaces:**
- Consumes: `settings_store.get_setting`, `set_setting`; `roles.get_role`, `effective_patterns`; `guards.ensure_administrator_remains`; the fixtures `admin_client`, `other_client`, `make_user`, `make_token`, `sessionmaker`; `tests.accounts`.
- Produces:
  - Models: `AuthSource` (`id`, `kind`, `name`, `enabled`, `position`, `settings`, `group_mapping`, `created_at`, `updated_at`); `User.source_id`, `User.external_id`; `UserRole.granted_by` (`"admin"` or `"source"`).
  - Settings `default_role` (None) and `local_sign_in` (`{"enabled": True}`).
  - `users.signed_in_patterns(db, user) -> frozenset[str]`, `users.is_builtin_admin(user) -> bool`, `users.can_act(db, user) -> bool`.
  - `GET /api/v1/settings/sign-in`, `PUT /api/v1/settings/default-role` (`{"default_role": str | None}`), `PUT /api/v1/settings/local-sign-in` (`{"enabled": bool}`), each answering `SignInSettings` (`{"default_role", "local_sign_in": {"enabled"}}`).

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/test_settings_store.py`:

```diff
@@ -6,7 +6,9 @@ from megooarti.system.settings_store import DEFAULTS, get_setting, set_setting
 async def test_defaults_apply_when_nothing_is_stored(db):
     assert await get_setting(db, "base_url") is None
     assert await get_setting(db, "anonymous_access") == {"enabled": False}
-    assert set(DEFAULTS) == {"base_url", "anonymous_access"}
+    assert await get_setting(db, "default_role") is None
+    assert await get_setting(db, "local_sign_in") == {"enabled": True}
+    assert set(DEFAULTS) == {"base_url", "anonymous_access", "default_role", "local_sign_in"}
 
 
 async def test_a_stored_value_replaces_the_default(db):
```

Create `backend/tests/security/test_sign_in_settings.py`:

```python
"""How people sign in besides the sources (spec 4.1): the default role, and MegooArti's own
users' sign-in, which can be turned off for everyone but the built-in `admin` (E1)."""

from megooarti.security import roles, users
from tests.accounts import PASSWORD, basic, bearer, error_code, sign_in

SIGN_IN = "/api/v1/settings/sign-in"
DEFAULT_ROLE = "/api/v1/settings/default-role"
LOCAL = "/api/v1/settings/local-sign-in"
SESSION = "/api/v1/auth/session"
LOGIN = "/api/v1/auth/login"


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def admin_can_sign_in(sessionmaker) -> None:
    """Give the built-in `admin` the password the tests sign in with."""
    async with sessionmaker() as db:
        admin = await users.get_user_by_username(db, "admin")
        await users.set_password(db, admin, PASSWORD, must_change_password=False)
        await db.commit()


async def test_reading_and_changing_need_the_security_permissions(client, make_user, sessionmaker):
    await make_role(sessionmaker, "settings-only", "admin:settings")
    await make_role(sessionmaker, "security-reader", "admin:security:read")
    await make_user("sam", roles=["settings-only"])
    await make_user("rita", roles=["security-reader"])

    nobody = await client.get(SIGN_IN)
    sam = await client.get(SIGN_IN, headers=basic("sam", PASSWORD))
    rita = await client.get(SIGN_IN, headers=basic("rita", PASSWORD))
    rita_writes = await client.put(
        DEFAULT_ROLE, json={"default_role": None}, headers=basic("rita", PASSWORD)
    )

    assert (nobody.status_code, sam.status_code, rita.status_code) == (401, 403, 200)
    assert rita_writes.status_code == 403


async def test_by_default_there_is_no_default_role_and_our_own_users_sign_in(admin_client):
    said = await admin_client.get(SIGN_IN)

    assert said.json() == {"default_role": None, "local_sign_in": {"enabled": True}}


async def test_the_default_role_is_every_signed_in_users_and_kept_on_none(
    admin_client, other_client, make_user, sessionmaker, make_token
):
    await make_role(sessionmaker, "readers", "repository:*:*:read")
    dana = await make_user("dana")
    token = await make_token(dana)

    set_to = await admin_client.put(DEFAULT_ROLE, json={"default_role": "readers"})
    session = await sign_in(other_client, "dana")
    by_password = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    by_token = await other_client.get(SESSION, headers=bearer(token))
    held = (await admin_client.get(f"/api/v1/users/{dana.id}")).json()["roles"]

    assert set_to.json()["default_role"] == "readers"
    assert "repository:*:*:read" in session["permissions"]
    assert "repository:*:*:read" in by_password.json()["permissions"]
    assert "repository:*:*:read" in by_token.json()["permissions"]
    assert held == []


async def test_the_default_role_is_not_a_visitors(admin_client, other_client, sessionmaker):
    await make_role(sessionmaker, "uploaders", "repository:*:*:add")
    await admin_client.put(DEFAULT_ROLE, json={"default_role": "uploaders"})
    await admin_client.put("/api/v1/settings/anonymous-access", json={"enabled": True})

    visitor = (await other_client.get(SESSION)).json()

    assert visitor["method"] == "anonymous"
    assert "repository:*:*:add" not in visitor["permissions"]


async def test_a_default_role_that_is_not_there_is_refused_and_null_clears_it(
    admin_client, sessionmaker
):
    await make_role(sessionmaker, "readers", "repository:*:*:read")
    await admin_client.put(DEFAULT_ROLE, json={"default_role": "readers"})

    unknown = await admin_client.put(DEFAULT_ROLE, json={"default_role": "nobody-has-it"})
    cleared = await admin_client.put(DEFAULT_ROLE, json={"default_role": None})

    assert (unknown.status_code, error_code(unknown)) == (422, "validation_error")
    assert unknown.json()["error"]["details"][0]["field"] == "default_role"
    assert cleared.json()["default_role"] is None


async def test_deleting_the_default_role_leaves_no_default_role(admin_client, sessionmaker):
    await make_role(sessionmaker, "readers", "repository:*:*:read")
    await admin_client.put(DEFAULT_ROLE, json={"default_role": "readers"})

    deleted = await admin_client.delete("/api/v1/roles/readers")

    assert deleted.status_code == 204
    assert (await admin_client.get(SIGN_IN)).json()["default_role"] is None


async def test_with_our_own_sign_in_off_only_the_built_in_admin_signs_in(
    admin_client, other_client, make_user, make_token, sessionmaker
):
    await admin_can_sign_in(sessionmaker)
    dana = await make_user("dana")
    token = await make_token(dana)

    off = await admin_client.put(LOCAL, json={"enabled": False})
    dana_signs_in = await other_client.post(LOGIN, json={"username": "dana", "password": PASSWORD})
    dana_by_basic = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    dana_by_token = await other_client.get(SESSION, headers=bearer(token))
    admin = await other_client.post(LOGIN, json={"username": "admin", "password": PASSWORD})

    assert off.json()["local_sign_in"] == {"enabled": False}
    assert (dana_signs_in.status_code, error_code(dana_signs_in)) == (401, "unauthorized")
    assert dana_by_basic.status_code == 401
    assert dana_by_token.status_code == 401
    assert admin.status_code == 200


async def test_the_session_of_one_of_our_own_ends_when_our_sign_in_is_turned_off(
    admin_client, other_client, make_user, sessionmaker
):
    await admin_can_sign_in(sessionmaker)
    await sign_in(admin_client, "admin")  # `root` is one of our own too
    await make_user("dana")
    await sign_in(other_client, "dana")

    await admin_client.put(LOCAL, json={"enabled": False})
    after = (await other_client.get(SESSION)).json()
    await admin_client.put(LOCAL, json={"enabled": True})
    back = (await other_client.get(SESSION)).json()

    assert after["authenticated"] is False
    assert back["user"]["username"] == "dana"


async def test_our_own_sign_in_stays_on_while_the_built_in_admin_has_no_full_access(
    admin_client, sessionmaker
):
    async with sessionmaker() as db:
        admin = await users.get_user_by_username(db, "admin")
        await users.set_roles(db, admin, [])
        await db.commit()

    refused = await admin_client.put(LOCAL, json={"enabled": False})

    assert (refused.status_code, error_code(refused)) == (409, "last_administrator")
    assert (await admin_client.get(SIGN_IN)).json()["local_sign_in"] == {"enabled": True}
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/test_settings_store.py tests/security/test_sign_in_settings.py`
Expected: 9 failed, 1 passed: `KeyError: 'default_role'` among the settings' defaults, and `/api/v1/settings/sign-in`, `/default-role` and `/local-sign-in` are not there (`404`). The test that a visitor has no default role passes already: there is none.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/security/models.py`:

```diff
@@ -18,6 +18,8 @@ from megooarti.db.base import Base
 
 class User(Base):
     __tablename__ = "users"
+    # One user for each identity a source has: a name taken by two is two users (E2).
+    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
 
     id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
     username: Mapped[str] = mapped_column(String(64), unique=True)
@@ -32,6 +34,34 @@ class User(Base):
         DateTime(timezone=True), default=utcnow, onupdate=utcnow
     )
     last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    # Where the user signs in: None for MegooArti's own users, else a sign-in source, and
+    # who they are there (an OIDC subject, an LDAP DN, a header's name). E2.
+    source_id: Mapped[uuid.UUID | None] = mapped_column(
+        ForeignKey("auth_sources.id", ondelete="SET NULL"), index=True
+    )
+    external_id: Mapped[str | None] = mapped_column(String(512))
+
+
+class AuthSource(Base):
+    """Somewhere people sign in from besides MegooArti's own users: a directory (LDAP),
+    an identity provider (OIDC), or a reverse proxy that says who they are (spec 4.1)."""
+
+    __tablename__ = "auth_sources"
+
+    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
+    kind: Mapped[str] = mapped_column(String(16))
+    name: Mapped[str] = mapped_column(String(64), unique=True)
+    enabled: Mapped[bool] = mapped_column(default=False)
+    # Where it is asked, after MegooArti's own users: the lowest first.
+    position: Mapped[int]
+    # What its kind needs to reach it; its secrets sealed (E5).
+    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
+    # [{"group": ..., "roles": [...]}]: the roles a member of a group is given (E4).
+    group_mapping: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
+    updated_at: Mapped[datetime] = mapped_column(
+        DateTime(timezone=True), default=utcnow, onupdate=utcnow
+    )
 
 
 class Role(Base):
@@ -74,6 +104,9 @@ class UserRole(Base):
     role_id: Mapped[uuid.UUID] = mapped_column(
         ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
     )
+    # Who gave it: an administrator ("admin"), or a source's group mapping ("source"),
+    # which takes back at the next sign-in what the groups no longer give (E4).
+    granted_by: Mapped[str] = mapped_column(String(8), default="admin", server_default="admin")
 
 
 class UserSession(Base):
```

Create `backend/src/megooarti/migrations/versions/0010_add_sign_in_sources.py`:

```python
"""add sign-in sources, the source a user signs in from, and who gave a user a role

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("group_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sources")),
        sa.UniqueConstraint("name", name=op.f("uq_auth_sources_name")),
    )
    op.add_column("users", sa.Column("source_id", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("external_id", sa.String(length=512), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_source_id_auth_sources"),
        "users",
        "auth_sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_users_source_id"), "users", ["source_id"])
    op.create_unique_constraint(op.f("uq_users_source_id"), "users", ["source_id", "external_id"])
    # Every role held until now was given by an administrator.
    op.add_column(
        "user_roles",
        sa.Column("granted_by", sa.String(length=8), nullable=False, server_default="admin"),
    )


def downgrade() -> None:
    op.drop_column("user_roles", "granted_by")
    op.drop_constraint(op.f("uq_users_source_id"), "users", type_="unique")
    op.drop_index(op.f("ix_users_source_id"), table_name="users")
    op.drop_constraint(op.f("fk_users_source_id_auth_sources"), "users", type_="foreignkey")
    op.drop_column("users", "external_id")
    op.drop_column("users", "source_id")
    op.drop_table("auth_sources")
```

Change `backend/src/megooarti/system/settings_store.py`:

```diff
@@ -9,6 +9,10 @@ from megooarti.system.models import SystemSetting
 DEFAULTS: dict[str, Any] = {
     "base_url": None,
     "anonymous_access": {"enabled": False},
+    # The role every signed-in user has besides their own, by its name (spec 4.1).
+    "default_role": None,
+    # Whether MegooArti's own users sign in: off, only the built-in `admin` does (E1).
+    "local_sign_in": {"enabled": True},
 }
 
 
```

Change `backend/src/megooarti/security/users.py`:

```diff
@@ -12,10 +12,11 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.errors import ApiError
 from megooarti.security.keys import TOKEN_PREFIX
-from megooarti.security.models import Role, User, UserRole
+from megooarti.security.models import AuthSource, Role, User, UserRole
 from megooarti.security.passwords import hash_password, password_problem
-from megooarti.security.roles import effective_patterns, roles_named
+from megooarti.security.roles import effective_patterns, get_role, roles_named
 from megooarti.security.sessions import delete_user_sessions
+from megooarti.system.settings_store import get_setting
 
 # The name Python's packaging tools send with an API token (`__token__` and the token
 # as HTTP Basic credentials). It stands for whoever owns the token, so nobody has it.
@@ -62,6 +63,37 @@ async def user_patterns(db: AsyncSession, user: User) -> frozenset[str]:
     return await effective_patterns(db, list(role_ids))
 
 
+async def signed_in_patterns(db: AsyncSession, user: User) -> frozenset[str]:
+    """What a signed-in user may do: what their roles give, and what the default role
+    gives, which every signed-in user has without its being kept on any (spec 4.1)."""
+    role_ids = list(await db.scalars(select(UserRole.role_id).where(UserRole.user_id == user.id)))
+    default = await get_setting(db, "default_role")
+    role = None if default is None else await get_role(db, default)
+    if role is not None:
+        role_ids.append(role.id)
+    return await effective_patterns(db, role_ids)
+
+
+def is_builtin_admin(user: User) -> bool:
+    """The built-in administrator, who signs in with a password of MegooArti's own
+    whatever sources are on or off (E1)."""
+    return user.builtin and user.username == "admin"
+
+
+async def can_act(db: AsyncSession, user: User) -> bool:
+    """Whether a user may be anybody now: active, and signing in where sign-in is on. A
+    user of a source that is off, or one of ours while our own sign-in is off, is refused
+    as a disabled user is (spec 4.1, 4.2)."""
+    if user.status != "active":
+        return False
+    if user.source_id is not None:
+        source = await db.get(AuthSource, user.source_id)
+        return source is not None and source.enabled
+    if user.external_id is not None:
+        return False  # their source was deleted
+    return is_builtin_admin(user) or (await get_setting(db, "local_sign_in"))["enabled"]
+
+
 async def describe(db: AsyncSession, user: User) -> UserView:
     names = await db.scalars(
         select(Role.name)
```

Change `backend/src/megooarti/security/roles.py`:

```diff
@@ -9,6 +9,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.errors import ApiError
 from megooarti.security.models import Role, RoleMember, RolePermission
+from megooarti.system.settings_store import get_setting, set_setting
 
 
 @dataclass(frozen=True)
@@ -136,5 +137,7 @@ async def update_role(
 async def delete_role(db: AsyncSession, role: Role) -> None:
     if role.builtin:
         raise ApiError(409, "builtin_protected", "Built-in roles cannot be deleted.")
+    if await get_setting(db, "default_role") == role.name:
+        await set_setting(db, "default_role", None)  # it gives nobody anything any more
     await db.delete(role)
     await db.flush()
```

Change `backend/src/megooarti/security/guards.py`:

```diff
@@ -6,6 +6,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 from megooarti.errors import ApiError
 from megooarti.security.models import RoleMember, RolePermission, User, UserRole
 from megooarti.security.permissions import FULL_ACCESS
+from megooarti.system.settings_store import get_setting
 
 # Arbitrary constant, distinct from the migration lock key.
 ADMINISTRATOR_LOCK_KEY = 0x4D45474F50
@@ -30,12 +31,16 @@ async def ensure_administrator_remains(db: AsyncSession) -> None:
     granting = granting.union(
         select(RoleMember.role_id).join(granting, RoleMember.member_role_id == granting.c.id)
     )
+    # Who signs in with a password of ours: while our own sign-in is off, `admin` alone (E1).
+    signs_in = [User.password_hash.is_not(None), User.source_id.is_(None)]
+    if not (await get_setting(db, "local_sign_in"))["enabled"]:
+        signs_in += [User.builtin.is_(True), User.username == "admin"]
     administrator = await db.scalar(
         select(User.id)
         .join(UserRole, UserRole.user_id == User.id)
         .where(
             User.status == "active",
-            User.password_hash.is_not(None),
+            *signs_in,
             UserRole.role_id.in_(select(granting.c.id)),
         )
         .limit(1)
```

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -110,7 +110,7 @@ async def build_principal(
     return Principal(
         user,
         method,
-        await users.user_patterns(db, user),
+        await users.signed_in_patterns(db, user),
         scopes,
         session,
         public,
@@ -179,7 +179,7 @@ async def authenticate_password(
         user = await users.get_user_by_username(db, username)
         stored = None if user is None else user.password_hash
         matched = await asyncio.to_thread(verify_password, stored, password)
-        if user is None or not matched or user.status != "active":
+        if user is None or not matched or not await users.can_act(db, user):
             return None
         if needs_rehash(user.password_hash):
             user.password_hash = await asyncio.to_thread(hash_password, password)
@@ -197,7 +197,7 @@ async def _authenticate_token(
         if token is None:
             return None
         user = await users.get_user(db, token.user_id)
-        if user is None or user.status != "active":
+        if user is None or not await users.can_act(db, user):
             return None
         if username is not None and user.username != users.normalise_username(username):
             return None
@@ -289,7 +289,7 @@ async def _from_registry_token(db: AsyncSession, request: Request, value: str) -
         user, patterns = anonymous
         return Principal(user, "anonymous", patterns, public=patterns)
     user = await users.get_user(db, claims.user_id)
-    if user is None or user.status != "active" or claims.method == "anonymous":
+    if user is None or not await users.can_act(db, user) or claims.method == "anonymous":
         raise refused
     if (claims.method == "token") != (claims.token_id is not None):
         raise refused
@@ -353,7 +353,7 @@ async def resolve_principal(
         )
         if record is not None:
             user = await users.get_user(db, record.user_id)
-            if user is not None and user.status == "active":
+            if user is not None and await users.can_act(db, user):
                 sessions.touch(record, now)
                 return await build_principal(db, user, "session", session=record)
 
@@ -505,7 +505,7 @@ async def _agent(request: Request, db: AsyncSession, value: str) -> Principal:
         return await build_principal(db, user, "token", token=token)
     grant = await oauth.find_access(db, value, utcnow())
     user = None if grant is None else await users.get_user(db, grant.user_id)
-    if grant is None or user is None or user.status != "active":
+    if grant is None or user is None or not await users.can_act(db, user):
         # Counted against the address, as a token that is not one is.
         return await _checked(db, request, None, _no_match)
     principal = await build_principal(db, user, "token")
```

Change `backend/src/megooarti/system/settings_api.py`:

```diff
@@ -4,11 +4,14 @@ from urllib.parse import urlsplit
 
 import structlog
 from fastapi import APIRouter, Depends
-from pydantic import BaseModel, field_validator
+from pydantic import BaseModel, Field, field_validator
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.db.session import get_session
+from megooarti.errors import ApiError
 from megooarti.security.authentication import Principal, require
+from megooarti.security.guards import ensure_administrator_remains
+from megooarti.security.roles import get_role
 from megooarti.system.settings_store import get_setting, set_setting
 
 log = structlog.get_logger(__name__)
@@ -25,6 +28,22 @@ class SettingsOut(BaseModel):
     anonymous_access: AnonymousAccess
 
 
+class LocalSignIn(BaseModel):
+    enabled: bool
+
+
+class DefaultRole(BaseModel):
+    default_role: str | None = Field(max_length=64)
+
+
+class SignInSettings(BaseModel):
+    """How people sign in, besides the sources (spec 4.1): the role every signed-in user
+    has, and whether MegooArti's own users sign in."""
+
+    default_role: str | None
+    local_sign_in: LocalSignIn
+
+
 class BaseUrl(BaseModel):
     base_url: str | None
 
@@ -52,6 +71,13 @@ async def _current(db: AsyncSession) -> SettingsOut:
     )
 
 
+async def _sign_in(db: AsyncSession) -> SignInSettings:
+    return SignInSettings(
+        default_role=await get_setting(db, "default_role"),
+        local_sign_in=LocalSignIn(**await get_setting(db, "local_sign_in")),
+    )
+
+
 @router.get("", response_model=SettingsOut)
 async def read_settings(
     _: Principal = Depends(require("admin:settings:read")),
@@ -89,3 +115,51 @@ async def set_anonymous_access(
         by=principal.user.username,
     )
     return result
+
+
+@router.get("/sign-in", response_model=SignInSettings)
+async def read_sign_in_settings(
+    _: Principal = Depends(require("admin:security:read")),
+    db: AsyncSession = Depends(get_session),
+) -> SignInSettings:
+    return await _sign_in(db)
+
+
+@router.put("/default-role", response_model=SignInSettings)
+async def set_default_role(
+    body: DefaultRole,
+    principal: Principal = Depends(require("admin:security:write")),
+    db: AsyncSession = Depends(get_session),
+) -> SignInSettings:
+    """The role every signed-in user has, besides their own; null for none."""
+    if body.default_role is not None and await get_role(db, body.default_role) is None:
+        details = [{"field": "default_role", "message": f"Unknown role: {body.default_role}"}]
+        raise ApiError(422, "validation_error", "The request is not valid.", details)
+    await set_setting(db, "default_role", body.default_role)
+    result = await _sign_in(db)
+    await db.commit()
+    log.info(
+        "setting_changed",
+        setting="default_role",
+        role=body.default_role,
+        by=principal.user.username,
+    )
+    return result
+
+
+@router.put("/local-sign-in", response_model=SignInSettings)
+async def set_local_sign_in(
+    body: LocalSignIn,
+    principal: Principal = Depends(require("admin:security:write")),
+    db: AsyncSession = Depends(get_session),
+) -> SignInSettings:
+    """Whether MegooArti's own users sign in. Off, the built-in `admin` still does (E1),
+    and must then hold full access: else nobody who signs in would."""
+    await set_setting(db, "local_sign_in", {"enabled": body.enabled})
+    await ensure_administrator_remains(db)
+    result = await _sign_in(db)
+    await db.commit()
+    log.info(
+        "setting_changed", setting="local_sign_in", enabled=body.enabled, by=principal.user.username
+    )
+    return result
```

Change `frontend/openapi.json`:

```diff
@@ -502,6 +502,27 @@
         "title": "Database",
         "type": "object"
       },
+      "DefaultRole": {
+        "properties": {
+          "default_role": {
+            "anyOf": [
+              {
+                "maxLength": 64,
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Default Role"
+          }
+        },
+        "required": [
+          "default_role"
+        ],
+        "title": "DefaultRole",
+        "type": "object"
+      },
       "Entry": {
         "properties": {
           "component": {
@@ -802,6 +823,19 @@
         "title": "Listing",
         "type": "object"
       },
+      "LocalSignIn": {
+        "properties": {
+          "enabled": {
+            "title": "Enabled",
+            "type": "boolean"
+          }
+        },
+        "required": [
+          "enabled"
+        ],
+        "title": "LocalSignIn",
+        "type": "object"
+      },
       "LoginRequest": {
         "properties": {
           "password": {
@@ -2000,6 +2034,31 @@
         "title": "SettingsOut",
         "type": "object"
       },
+      "SignInSettings": {
+        "description": "How people sign in, besides the sources (spec 4.1): the role every signed-in user\nhas, and whether MegooArti's own users sign in.",
+        "properties": {
+          "default_role": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Default Role"
+          },
+          "local_sign_in": {
+            "$ref": "#/components/schemas/LocalSignIn"
+          }
+        },
+        "required": [
+          "default_role",
+          "local_sign_in"
+        ],
+        "title": "SignInSettings",
+        "type": "object"
+      },
       "SigningKeyGenerate": {
         "properties": {
           "algorithm": {
@@ -4801,6 +4860,121 @@
         ]
       }
     },
+    "/api/v1/settings/default-role": {
+      "put": {
+        "description": "The role every signed-in user has, besides their own; null for none.",
+        "operationId": "set_default_role_api_v1_settings_default_role_put",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/DefaultRole"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SignInSettings"
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
+        "summary": "Set Default Role",
+        "tags": [
+          "settings"
+        ]
+      }
+    },
+    "/api/v1/settings/local-sign-in": {
+      "put": {
+        "description": "Whether MegooArti's own users sign in. Off, the built-in `admin` still does (E1),\nand must then hold full access: else nobody who signs in would.",
+        "operationId": "set_local_sign_in_api_v1_settings_local_sign_in_put",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/LocalSignIn"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SignInSettings"
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
+        "summary": "Set Local Sign In",
+        "tags": [
+          "settings"
+        ]
+      }
+    },
+    "/api/v1/settings/sign-in": {
+      "get": {
+        "operationId": "read_sign_in_settings_api_v1_settings_sign_in_get",
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SignInSettings"
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
+        "summary": "Read Sign In Settings",
+        "tags": [
+          "settings"
+        ]
+      }
+    },
     "/api/v1/status/live": {
       "get": {
         "description": "The process is running and can answer HTTP requests.",
```

Change `docs/administration.md`:

```diff
@@ -55,6 +55,7 @@ area's name alone gives both.
 | `admin:repositories` | Making, changing and deleting repositories, having a proxy check its remote again, rebuilding an index, and the keys repositories sign with |
 | `admin:blobstores` | The blob stores |
 | `admin:settings` | The base URL and anonymous access; to read, also what is running (`/api/v1/system/information`) |
+| `admin:security` | How people sign in: the sign-in sources and their order, the default role, and whether MegooArti's own users sign in |
 
 What a repository holds is not given by these, but by `repository:` permissions:
 see [Repositories](repositories.md). Whoever may change roles, or the roles a user
```

Then write the API's description: (in `backend/`) `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`. The guide's new row is what `tests/test_documents.py` asks for every area a permission names.

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/test_settings_store.py tests/security tests/test_migrations.py tests/test_openapi_snapshot.py tests/test_documents.py`
Expected: 443 passed.

- [ ] **Step 5: Commit**

```bash
git add backend frontend/openapi.json docs/administration.md
git commit -m "feat(security): sign-in sources' records, a default role every signed-in user has, and our own users turned off for all but admin"
```

---

### Task 2: Signing in through a source

**Files:**
- Create: `backend/src/megooarti/security/sources.py`
- Modify: `backend/src/megooarti/security/users.py`, `backend/src/megooarti/security/authentication.py`
- Test: `backend/tests/security/directory.py` (kinds of source for the tests), `backend/tests/security/test_source_sign_in.py`; modify `backend/tests/security/conftest.py`

**Interfaces:**
- Consumes: Task 1's models, `users.can_act`; `secrets_box.seal`, `unseal`; `sessions.delete_user_sessions`; `users.normalise_username`, `looks_like_token`, `TOKEN_USERNAME`.
- Produces:
  - `sources.Identity(external_id, username, display_name="", email=None, groups=frozenset())`; `UNKNOWN`, `REFUSED`; `Tested(ok, message, identity=None)`; `SourceUnavailable`.
  - `sources.Kind` (class attributes `name`, `secrets`, `in_browser`, `takes_passwords`; methods `checked(settings) -> dict`, `async password(settings, name, password, known) -> Identity | "unknown" | "refused"`, `async test(settings, name, password) -> Tested`); `KINDS: dict[str, Kind]`; `register(kind)`.
  - `sources.invalid(field, message) -> ApiError`, `unavailable(source) -> ApiError`, `in_order(db)`, `get_source(db, id)`, `kept_settings(settings, kind, sent, current)`, `shown_settings(kind, stored) -> (dict, list[str])`, `opened_settings(settings, kind, stored)`, `check_mapping(db, mapping)`, `next_position(db)`, `reorder(db, ids)`, `users_of(db, source) -> int`, `delete_source(db, source)`, `mapped_role_names(source, groups) -> list[str]`, `provision(db, source, identity) -> User`, `password_sign_in(db, settings, name, password, user) -> User | None`.
  - `users.is_external(user)`; `users.set_roles` keeping a source's roles the source's; `users.set_password` refusing a user of a source with `409 external_user`.
  - For tests: `tests.security.directory` (`SECRET`, `Directory`, `Portal`, `person`) and the fixtures `kinds`, `add_source`, `change_source`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/directory.py`:

```python
"""Kinds of sign-in source for the tests, until LDAP (15d) and OIDC (15b) bring real ones.

`Directory` is a directory written in its own settings: the people it knows, by name,
with their password, identity and groups. It takes passwords as LDAP does, and answers
only when its `secret` is the one it was given, so that a test sees the secret unsealed.
`Portal` is signed in to in the browser, as OIDC is.
"""

from typing import Any

from megooarti.security import sources

SECRET = "the directory's bind password"


class Directory(sources.Kind):
    name = "directory"
    secrets = ("secret",)
    takes_passwords = True

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        people = settings.get("people", {})
        if not isinstance(people, dict):
            raise sources.invalid("settings.people", "Must be an object of people by name.")
        return {
            "people": people,
            "down": bool(settings.get("down")),
            "secret": settings.get("secret"),
        }

    def _identity(self, name: str, person: dict[str, Any]) -> sources.Identity:
        return sources.Identity(
            external_id=person.get("id", f"uid={name},ou=people"),
            username=person.get("username", name),
            display_name=person.get("display_name", name.title()),
            email=person.get("email"),
            groups=frozenset(person.get("groups", [])),
        )

    async def password(self, settings, name, password, known):
        if settings["down"] or settings.get("secret") != SECRET:
            raise sources.SourceUnavailable("the directory did not answer")
        for found, person in settings["people"].items():
            identity = self._identity(found, person)
            if (known is not None and identity.external_id == known) or (
                known is None and found.casefold() == name.casefold()
            ):
                return identity if person["password"] == password else sources.REFUSED
        return sources.UNKNOWN

    async def test(self, settings, name, password):
        if settings["down"] or settings.get("secret") != SECRET:
            raise sources.SourceUnavailable("the directory did not answer")
        if name is None:
            return sources.Tested(True, "The directory answered.")
        person = settings["people"].get(name)
        if person is None or person["password"] != password:
            return sources.Tested(False, f"The directory does not know {name} by that password.")
        return sources.Tested(True, f"{name} signed in.", self._identity(name, person))


class Portal(sources.Kind):
    name = "portal"
    in_browser = True

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {"issuer": str(settings.get("issuer", ""))}


def person(password: str, *groups: str, **more: Any) -> dict[str, Any]:
    return {"password": password, "groups": list(groups), **more}
```

Change `backend/tests/security/conftest.py`:

```diff
@@ -1,8 +1,11 @@
 from datetime import UTC, datetime
+from typing import Any
 
 import pytest
 
-from megooarti.security.models import User
+from megooarti.security import sources
+from megooarti.security.models import AuthSource, User
+from tests.security.directory import SECRET, Directory, Portal
 
 NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
 
@@ -13,3 +16,61 @@ async def dana(db) -> User:
     db.add(user)
     await db.flush()
     return user
+
+
+@pytest.fixture
+def kinds(monkeypatch) -> dict[str, sources.Kind]:
+    """The kinds of source of the tests, in place of whatever the server has."""
+    registered = {kind.name: kind for kind in (Directory(), Portal())}
+    monkeypatch.setattr(sources, "KINDS", registered)
+    return registered
+
+
+@pytest.fixture
+def add_source(sessionmaker, settings, kinds):
+    """Keep a source of a test kind, enabled and asked after those before it."""
+
+    async def add(
+        name: str,
+        people: dict[str, Any] | None = None,
+        *,
+        kind: str = "directory",
+        mapping: list[dict[str, Any]] | None = None,
+        enabled: bool = True,
+        **more: Any,
+    ) -> AuthSource:
+        sent = {"people": people or {}, "secret": SECRET, **more} if kind == "directory" else more
+        async with sessionmaker() as db:
+            source = AuthSource(
+                kind=kind,
+                name=name,
+                enabled=enabled,
+                position=await sources.next_position(db),
+                settings=sources.kept_settings(settings, kinds[kind], sent, None),
+                group_mapping=mapping or [],
+            )
+            db.add(source)
+            await db.commit()
+            return source
+
+    return add
+
+
+@pytest.fixture
+def change_source(sessionmaker, settings, kinds):
+    """Change what a test source says or how it is set, as a directory changes."""
+
+    async def change(source: AuthSource, **changes: Any) -> None:
+        async with sessionmaker() as db:
+            stored = await db.get(AuthSource, source.id)
+            for name in ("enabled", "position", "group_mapping"):
+                if name in changes:
+                    setattr(stored, name, changes.pop(name))
+            if changes:
+                kind = kinds[stored.kind]
+                sent = {**stored.settings, **changes}
+                sent.pop("secret", None)  # the stored one is kept
+                stored.settings = sources.kept_settings(settings, kind, sent, stored.settings)
+            await db.commit()
+
+    return change
```

Create `backend/tests/security/test_source_sign_in.py`:

```python
"""Signing in through a source (spec 4.2, E2-E4): the user made at the first sign-in and
brought up to date at each, the order sources are asked in, and a source turned off."""

from sqlalchemy import select

from megooarti.security import roles, users
from megooarti.security.models import User, UserRole
from tests.accounts import PASSWORD, basic, bearer, error_code, sign_in
from tests.security.directory import person

LOGIN = "/api/v1/auth/login"
SESSION = "/api/v1/auth/session"
DEVELOPERS = [{"group": "developers", "roles": ["developers"]}]


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def stored(sessionmaker, username: str) -> tuple[User | None, dict[str, str]]:
    """The user of this name, and the roles they hold, each with who gave it."""
    async with sessionmaker() as db:
        user = await users.get_user_by_username(db, username)
        if user is None:
            return None, {}
        held = await db.execute(
            select(roles.Role.name, UserRole.granted_by)
            .join(UserRole, UserRole.role_id == roles.Role.id)
            .where(UserRole.user_id == user.id)
        )
        return user, {name: by for name, by in held}


async def login(client, username: str, password: str):
    return await client.post(LOGIN, json={"username": username, "password": password})


async def test_the_first_sign_in_makes_the_user_with_the_roles_of_their_groups(
    client, add_source, sessionmaker
):
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    corp = await add_source(
        "Corp",
        {
            "Carol": person(
                "carols secret",
                "Developers",
                display_name="Carol Danvers",
                email="carol@corp.example",
            )
        },
        mapping=DEVELOPERS,
    )

    signed_in = await login(client, "Carol", "carols secret")
    carol, held = await stored(sessionmaker, "carol")

    assert signed_in.status_code == 200, signed_in.text
    assert "repository:*:*:read" in signed_in.json()["permissions"]
    assert (carol.source_id, carol.external_id) == (corp.id, "uid=Carol,ou=people")
    assert (carol.display_name, carol.email, carol.password_hash) == (
        "Carol Danvers",
        "carol@corp.example",
        None,
    )
    assert carol.last_login_at is not None
    assert held == {"developers": "source"}  # groups are matched whatever their case


async def test_each_sign_in_brings_the_user_up_to_date_and_keeps_an_administrators_roles(
    admin_client, other_client, add_source, change_source, sessionmaker
):
    await make_role(sessionmaker, "developers", "repository:*:*:read")
    await make_role(sessionmaker, "auditors", "admin:users:read")
    corp = await add_source("corp", {"carol": person("pw", "developers")}, mapping=DEVELOPERS)
    await login(other_client, "carol", "pw")
    carol, _ = await stored(sessionmaker, "carol")
    await admin_client.patch(
        f"/api/v1/users/{carol.id}", json={"roles": ["developers", "auditors"]}
    )

    await change_source(
        corp, people={"carol": person("pw", display_name="Carol D.", email="cd@corp.example")}
    )
    again = await login(other_client, "carol", "pw")
    carol, held = await stored(sessionmaker, "carol")

    assert again.status_code == 200
    assert (carol.display_name, carol.email) == ("Carol D.", "cd@corp.example")
    # Her groups no longer give `developers`; `auditors` was an administrator's to give.
    assert held == {"auditors": "admin"}


async def test_a_name_one_of_our_own_has_is_checked_by_us_alone(
    client, make_user, add_source, sessionmaker
):
    await make_user("dana")
    await add_source("Corp HQ", {"dana": person("directory pw")})
    await add_source("corp-hq", {"dana": person("other directory pw")})

    first = await login(client, "dana", PASSWORD)  # the local dana is asked, and only her
    by_directory = await login(client, "dana", "directory pw")
    as_herself = await login(client, "dana@corp-hq", "directory pw")

    assert first.json()["user"]["username"] == "dana"
    assert by_directory.status_code == 401
    assert as_herself.status_code == 401  # nobody has the name yet: no source knows it so


async def test_a_directory_user_whose_name_is_taken_gets_name_at_source(
    client, make_user, add_source, sessionmaker
):
    corp = await add_source("Corp HQ", {"erin": person("pw", id="uid=erin")})
    await login(client, "erin", "pw")
    # A user of our own is given the name the directory's erin had, who is renamed so.
    erin, _ = await stored(sessionmaker, "erin")
    async with sessionmaker() as db:
        found = await db.get(User, erin.id)
        found.username = "erin.old"
        await db.commit()
    await make_user("erin")

    again = await login(client, "erin.old", "pw")
    renamed, _ = await stored(sessionmaker, "erin@corp-hq")

    assert again.status_code == 200
    assert (renamed.id, renamed.source_id) == (erin.id, corp.id)
    assert again.json()["user"]["username"] == "erin@corp-hq"


async def test_a_name_nobody_has_is_asked_of_each_source_in_order_and_the_first_who_knows_decides(
    client, add_source, change_source, sessionmaker
):
    first = await add_source("first", {"frank": person("first pw")})
    second = await add_source("second", {"frank": person("second pw"), "gina": person("g")})

    gina = await login(client, "gina", "g")  # the first does not know her: the second does
    wrong_at_first = await login(client, "frank", "second pw")
    await change_source(first, position=2)
    by_second = await login(client, "frank", "second pw")
    frank, _ = await stored(sessionmaker, "frank")

    assert gina.status_code == 200
    assert (wrong_at_first.status_code, error_code(wrong_at_first)) == (401, "unauthorized")
    assert by_second.status_code == 200
    assert frank.source_id == second.id


async def test_a_user_of_a_source_is_asked_of_their_own_source_alone(
    client, add_source, sessionmaker
):
    await add_source("first", {"hal": person("first pw", id="uid=hal,first")})
    await add_source("second", {"hal": person("second pw", id="uid=hal,second")})
    await login(client, "hal", "first pw")

    by_the_other = await login(client, "hal", "second pw")

    assert by_the_other.status_code == 401


async def test_a_user_of_a_source_signs_in_with_basic_and_makes_api_tokens(
    client, other_client, add_source
):
    await add_source("corp", {"ivy": person("ivy pw")})

    by_basic = await other_client.get(SESSION, headers=basic("ivy", "ivy pw"))
    await sign_in(client, "ivy", "ivy pw")
    made = await client.post("/api/v1/me/tokens", json={"name": "ci"})
    by_token = await other_client.get(SESSION, headers=bearer(made.json()["token"]))

    assert by_basic.json()["user"]["username"] == "ivy"
    assert made.status_code == 201
    assert by_token.json()["user"]["username"] == "ivy"


async def test_a_source_turned_off_signs_nobody_in_and_refuses_its_users(
    client, other_client, add_source, change_source
):
    corp = await add_source("corp", {"jo": person("jo pw")})
    await sign_in(client, "jo", "jo pw")
    token = (await client.post("/api/v1/me/tokens", json={"name": "ci"})).json()["token"]
    await add_source("off", {"kim": person("kim pw")}, enabled=False)

    await change_source(corp, enabled=False)
    session = (await client.get(SESSION)).json()
    by_token = await other_client.get(SESSION, headers=bearer(token))
    jo = await login(other_client, "jo", "jo pw")
    kim = await login(other_client, "kim", "kim pw")
    await change_source(corp, enabled=True)
    back = (await client.get(SESSION)).json()

    assert session["authenticated"] is False
    assert (by_token.status_code, jo.status_code, kim.status_code) == (401, 401, 401)
    assert back["user"]["username"] == "jo"


async def test_a_user_an_administrator_disabled_is_refused_whatever_the_directory_says(
    admin_client, other_client, add_source, sessionmaker
):
    await add_source("corp", {"lee": person("lee pw")})
    await login(other_client, "lee", "lee pw")
    lee, _ = await stored(sessionmaker, "lee")
    await admin_client.patch(f"/api/v1/users/{lee.id}", json={"status": "disabled"})

    again = await login(other_client, "lee", "lee pw")

    assert again.status_code == 401


async def test_a_source_that_does_not_answer_is_named_and_counts_no_failure(client, add_source):
    await add_source("corp", {"max": person("pw")}, down=True)

    answers = [await login(client, "max", "pw") for _ in range(6)]

    assert {(answer.status_code, error_code(answer)) for answer in answers} == {
        (503, "source_unavailable")
    }
    assert "corp" in answers[0].json()["error"]["message"]


async def test_failed_sign_ins_through_a_source_are_limited_as_ours_are(client, add_source):
    await add_source("corp", {"ned": person("pw")})

    answers = [await login(client, "ned", "wrong") for _ in range(6)]

    assert [answer.status_code for answer in answers] == [401] * 5 + [429]


async def test_the_password_of_a_user_of_a_source_is_the_sources(
    admin_client, other_client, add_source, sessionmaker
):
    await add_source("corp", {"oli": person("oli pw")})
    await sign_in(other_client, "oli", "oli pw")
    oli, _ = await stored(sessionmaker, "oli")

    by_admin = await admin_client.put(
        f"/api/v1/users/{oli.id}/password", json={"password": "a new long password"}
    )
    by_oli = await other_client.put(
        "/api/v1/me/password",
        json={"current_password": "oli pw", "new_password": "a new long password"},
    )

    assert (by_admin.status_code, error_code(by_admin)) == (409, "external_user")
    assert (by_oli.status_code, error_code(by_oli)) == (409, "external_user")


async def test_a_name_a_source_gives_that_is_nobodys_is_given_another(
    client, add_source, sessionmaker
):
    await add_source("corp", {"pat": person("pw", username="__token__", id="uid=pat")})

    signed_in = await login(client, "pat", "pw")

    assert signed_in.json()["user"]["username"] == "__token__@corp"
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/security/test_source_sign_in.py`
Expected: The tests of `tests/security` do not load: `ImportError: cannot import name 'sources' from 'megooarti.security'`.

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/security/sources.py`:

```python
"""Sign-in sources: where people sign in from besides MegooArti's own users (spec 4).

Each kind of source (LDAP, OIDC, a trusted header) is a `Kind`, registered by the module
that brings it. Here is what every kind shares: the order sources are asked in, their
secrets, and the users they make at a first sign-in and bring up to date at each (E2-E5).
"""

import itertools
import re
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import structlog
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.secrets_box import seal, unseal
from megooarti.security.models import AuthSource, Role, User, UserRole
from megooarti.security.sessions import delete_user_sessions
from megooarti.security.users import TOKEN_USERNAME, looks_like_token, normalise_username

log = structlog.get_logger(__name__)

# What a user's name may hold, as the users' API says (`[A-Za-z0-9._@-]`, lower case here).
_NOT_IN_A_NAME = re.compile(r"[^a-z0-9._@-]+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
_NAME_LENGTH = 64


@dataclass(frozen=True)
class Identity:
    """Who a source says somebody is."""

    external_id: str  # what the source knows them by, for good: an OIDC subject, an LDAP DN
    username: str  # the name they sign in with there
    display_name: str = ""
    email: str | None = None
    groups: frozenset[str] = frozenset()


# What a source answers a name and a password with, when it is not who they are.
Unknown = Literal["unknown"]  # nobody of that name there: the next source is asked
Refused = Literal["refused"]  # somebody of that name, and not that password: nobody else is
UNKNOWN: Unknown = "unknown"
REFUSED: Refused = "refused"


@dataclass(frozen=True)
class Tested:
    """What testing a source found: whether it answered, and who it said someone is."""

    ok: bool
    message: str
    identity: Identity | None = None


class SourceUnavailable(Exception):
    """A source could not be asked: it did not answer, or answered nothing it should."""


class Kind:
    """A kind of source. A module that brings one subclasses this and `register`s it."""

    name: ClassVar[str]
    # The settings that are secrets: sealed when kept, and shown to nobody again (E5).
    secrets: ClassVar[tuple[str, ...]] = ()
    # People sign in to it in the browser, sent there by the sign-in screen (OIDC).
    in_browser: ClassVar[bool] = False
    # It checks a name and a password, when somebody signs in with them here (E3).
    takes_passwords: ClassVar[bool] = False

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        """The settings as they are kept, its secrets as they were sent: left out when
        none was. Raises `invalid(...)` for what is wrong with them."""
        raise NotImplementedError

    async def password(
        self, settings: dict[str, Any], name: str, password: str, known: str | None
    ) -> Identity | Unknown | Refused:
        """Who `name` is, if `password` is theirs. `known` is the identity a user of this
        source has already, when the name is theirs. Raises SourceUnavailable."""
        return UNKNOWN

    async def test(
        self, settings: dict[str, Any], name: str | None, password: str | None
    ) -> Tested:
        """Whether the source answers, and, given a name, who it says they are."""
        raise NotImplementedError


KINDS: dict[str, Kind] = {}


def register(kind: Kind) -> Kind:
    KINDS[kind.name] = kind
    return kind


def invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def unavailable(source: AuthSource) -> ApiError:
    return ApiError(
        503, "source_unavailable", f"The sign-in source {source.name} cannot be reached."
    )


# --- The records ----------------------------------------------------------------------


async def in_order(db: AsyncSession) -> list[AuthSource]:
    return list(await db.scalars(select(AuthSource).order_by(AuthSource.position)))


async def get_source(db: AsyncSession, source_id: uuid.UUID) -> AuthSource | None:
    return await db.get(AuthSource, source_id)


def kept_settings(
    settings: Settings, kind: Kind, sent: dict[str, Any], current: dict[str, Any] | None
) -> dict[str, Any]:
    """The settings to keep: checked by the kind, a secret sealed, or the stored one kept
    where none was sent."""
    values = kind.checked(sent)
    for name in kind.secrets:
        given = values.get(name)
        if given:
            values[name] = str(seal(settings, given))
        elif current is not None and current.get(name):
            values[name] = current[name]
        else:
            values.pop(name, None)
    return values


def shown_settings(kind: Kind | None, stored: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The settings without their secrets, and the names of the secrets that are set."""
    secrets = () if kind is None else kind.secrets
    shown = {name: value for name, value in stored.items() if name not in secrets}
    return shown, sorted(name for name in secrets if stored.get(name))


def opened_settings(settings: Settings, kind: Kind, stored: dict[str, Any]) -> dict[str, Any]:
    """The settings as the kind uses them: its secrets unsealed."""
    opened = dict(stored)
    for name in kind.secrets:
        if opened.get(name):
            opened[name] = unseal(settings, opened[name])
    return opened


async def check_mapping(db: AsyncSession, mapping: list[dict[str, Any]]) -> None:
    """Every role a group is given must be one there is (spec 11)."""
    names = sorted({role for entry in mapping for role in entry["roles"]})
    if not names:
        return
    found = set(await db.scalars(select(Role.name).where(Role.name.in_(names))))
    missing = [name for name in names if name not in found]
    if missing:
        raise invalid("group_mapping", f"Unknown role: {', '.join(missing)}")


async def next_position(db: AsyncSession) -> int:
    last = await db.scalar(select(func.max(AuthSource.position)))
    return 0 if last is None else last + 1


async def reorder(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    """Put the sources in this order: every one of them, once."""
    every = {source.id: source for source in await in_order(db)}
    if len(ids) != len(set(ids)) or set(ids) != set(every):
        raise invalid("ids", "Give every source once, in the order they are to be asked.")
    for position, source_id in enumerate(ids):
        every[source_id].position = position
    await db.flush()


async def users_of(db: AsyncSession, source: AuthSource) -> int:
    return await db.scalar(select(func.count()).where(User.source_id == source.id)) or 0


async def delete_source(db: AsyncSession, source: AuthSource) -> None:
    """Delete a source. Its users are disabled, and kept with what they own (spec 4.3)."""
    held = list(await db.scalars(select(User.id).where(User.source_id == source.id)))
    if held:
        await db.execute(update(User).where(User.id.in_(held)).values(status="disabled"))
        for user_id in held:
            await delete_user_sessions(db, user_id)
    await db.delete(source)
    await db.flush()


# --- Users of a source ----------------------------------------------------------------


def _usable(name: str) -> str:
    """A name as a user's name may be: lower case, and nothing a name may not hold."""
    return _NOT_IN_A_NAME.sub("-", normalise_username(name)).strip("-")[:_NAME_LENGTH] or "user"


def _names(wanted: str, source: AuthSource):
    """The names a user of this source may be given, the one they have there first."""
    base = _usable(wanted)
    yield base
    suffix = "@" + _usable(source.name)
    yield base[: _NAME_LENGTH - len(suffix)] + suffix
    for number in itertools.count(2):
        more = f"{suffix}-{number}"
        yield base[: _NAME_LENGTH - len(more)] + more


async def _free_name(
    db: AsyncSession, wanted: str, source: AuthSource, own: uuid.UUID | None
) -> str:
    """Their name there, unless another user has it: then `name@source` (spec 4.2)."""
    for name in _names(wanted, source):
        if name == TOKEN_USERNAME or looks_like_token(name):
            continue  # nobody's name, whatever a source says
        holder = await db.scalar(select(User.id).where(User.username == name))
        if holder is None or holder == own:
            return name
    raise AssertionError("unreachable")  # pragma: no cover


def mapped_role_names(source: AuthSource, groups: frozenset[str]) -> list[str]:
    """The roles a source's group mapping gives a member of these groups."""
    member = {group.casefold() for group in groups}
    return sorted(
        {
            role
            for entry in source.group_mapping
            if entry["group"].casefold() in member
            for role in entry["roles"]
        }
    )


async def _map_roles(
    db: AsyncSession, user: User, source: AuthSource, groups: frozenset[str]
) -> None:
    """Give the roles the groups give, and take back those they no longer do. Roles an
    administrator gave are theirs, and kept (E4)."""
    names = mapped_role_names(source, groups)
    wanted = set(await db.scalars(select(Role.id).where(Role.name.in_(names)))) if names else set()
    rows = await db.execute(
        select(UserRole.role_id, UserRole.granted_by).where(UserRole.user_id == user.id)
    )
    held = {role_id: by for role_id, by in rows}
    gone = [role_id for role_id, by in held.items() if by == "source" and role_id not in wanted]
    if gone:
        await db.execute(
            delete(UserRole).where(UserRole.user_id == user.id, UserRole.role_id.in_(gone))
        )
    new = wanted - held.keys()
    if new:
        await db.execute(
            insert(UserRole),
            [{"user_id": user.id, "role_id": role_id, "granted_by": "source"} for role_id in new],
        )


async def provision(db: AsyncSession, source: AuthSource, identity: Identity) -> User:
    """The user this identity is: made at their first sign-in, and their name, details and
    mapped roles brought up to date at each (spec 4.2)."""
    user = await db.scalar(
        select(User).where(User.source_id == source.id, User.external_id == identity.external_id)
    )
    name = await _free_name(db, identity.username, source, None if user is None else user.id)
    display_name = (identity.display_name.strip() or identity.username)[:128]
    email = identity.email if identity.email and _EMAIL.fullmatch(identity.email) else None
    if user is None:
        user = User(
            username=name,
            display_name=display_name,
            email=email if email is None else email[:254],
            password_hash=None,
            status="active",
            must_change_password=False,
            builtin=False,
            source_id=source.id,
            external_id=identity.external_id,
        )
        db.add(user)
        log.info("user_provisioned", username=name, source=source.name)
    else:
        user.username, user.display_name = name, display_name
        user.email = email if email is None else email[:254]
    await db.flush()
    await _map_roles(db, user, source, identity.groups)
    return user


async def _ask(
    db: AsyncSession,
    settings: Settings,
    source: AuthSource,
    name: str,
    password: str,
    known: str | None,
) -> Identity | Unknown | Refused:
    kind = KINDS.get(source.kind)
    if kind is None or not kind.takes_passwords or not source.enabled:
        return UNKNOWN
    try:
        return await kind.password(
            opened_settings(settings, kind, source.settings), name, password, known
        )
    except SourceUnavailable as error:
        log.warning("source_unavailable", source=source.name, error=str(error))
        raise unavailable(source) from None


async def password_sign_in(
    db: AsyncSession, settings: Settings, name: str, password: str, user: User | None
) -> User | None:
    """The user a name and a password are, by the sources (E3): a user of a source is asked
    of their own source alone; a name nobody has, of each enabled source that takes
    passwords, in order, the first that knows the name deciding. None if none does."""
    if user is not None:
        source = None if user.source_id is None else await get_source(db, user.source_id)
        if source is None:
            return None
        answer = await _ask(db, settings, source, name, password, user.external_id)
        if not isinstance(answer, Identity) or answer.external_id != user.external_id:
            return None
        return await provision(db, source, answer)
    for source in await in_order(db):
        answer = await _ask(db, settings, source, name, password, None)
        if answer == REFUSED:
            return None
        if isinstance(answer, Identity):
            return await provision(db, source, answer)
    return None
```

Change `backend/src/megooarti/security/users.py`:

```diff
@@ -80,6 +80,11 @@ def is_builtin_admin(user: User) -> bool:
     return user.builtin and user.username == "admin"
 
 
+def is_external(user: User) -> bool:
+    """A user of a sign-in source, or of one that was deleted: their password is not ours."""
+    return user.source_id is not None or user.external_id is not None
+
+
 async def can_act(db: AsyncSession, user: User) -> bool:
     """Whether a user may be anybody now: active, and signing in where sign-in is on. A
     user of a source that is off, or one of ours while our own sign-in is off, is refused
@@ -129,11 +134,28 @@ def _check_password(password: str, username: str) -> None:
 
 
 async def set_roles(db: AsyncSession, user: User, role_names: Iterable[str]) -> None:
+    """Give the user these roles, as an administrator does. One a source's group mapping
+    gave stays the source's, to be taken back when the groups no longer give it (E4)."""
     chosen = await roles_named(db, role_names)
+    from_source = set(
+        await db.scalars(
+            select(UserRole.role_id).where(
+                UserRole.user_id == user.id, UserRole.granted_by == "source"
+            )
+        )
+    )
     await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
     if chosen:
         await db.execute(
-            insert(UserRole), [{"user_id": user.id, "role_id": role.id} for role in chosen]
+            insert(UserRole),
+            [
+                {
+                    "user_id": user.id,
+                    "role_id": role.id,
+                    "granted_by": "source" if role.id in from_source else "admin",
+                }
+                for role in chosen
+            ],
         )
 
 
@@ -193,6 +215,10 @@ async def set_password(
 ) -> None:
     if user.builtin and user.username == "anonymous":
         raise ApiError(409, "builtin_protected", "The anonymous user cannot have a password.")
+    if is_external(user):
+        raise ApiError(
+            409, "external_user", f"{user.username} signs in through a source, with its password."
+        )
     _check_password(password, user.username)
     user.password_hash = await asyncio.to_thread(hash_password, password)
     user.must_change_password = must_change_password
```

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -16,7 +16,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 from megooarti.clock import utcnow
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
-from megooarti.security import oauth, registry_tokens, sessions, throttle, tokens, users
+from megooarti.security import oauth, registry_tokens, sessions, sources, throttle, tokens, users
 from megooarti.security.keys import TOKEN_PREFIX
 from megooarti.security.models import ApiToken, User, UserSession
 from megooarti.security.passwords import hash_password, needs_rehash, verify_password
@@ -177,11 +177,19 @@ async def authenticate_password(
 
     async def attempt() -> User | None:
         user = await users.get_user_by_username(db, username)
-        stored = None if user is None else user.password_hash
-        matched = await asyncio.to_thread(verify_password, stored, password)
-        if user is None or not matched or not await users.can_act(db, user):
+        if user is None or users.is_external(user):
+            # A name nobody has here, or a user of a source: the sources decide (E3).
+            found = await sources.password_sign_in(
+                db, request.app.state.settings, username, password, user
+            )
+            if found is None and user is None:
+                # As long as a wrong password of somebody's takes.
+                await asyncio.to_thread(verify_password, None, password)
+            return found if found is not None and await users.can_act(db, found) else None
+        matched = await asyncio.to_thread(verify_password, user.password_hash, password)
+        if not matched or not await users.can_act(db, user):
             return None
-        if needs_rehash(user.password_hash):
+        if user.password_hash is not None and needs_rehash(user.password_hash):
             user.password_hash = await asyncio.to_thread(hash_password, password)
         return user
 
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/security tests/mcp`
Expected: 414 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(security): sign in through a source: the user made at the first sign-in and refreshed at each, groups to roles, sources asked in order"
```

---

### Task 3: The sources' API

**Files:**
- Create: `backend/src/megooarti/security/api/sources.py`
- Modify: `backend/src/megooarti/security/users.py`, `backend/src/megooarti/security/api/users.py`, `backend/src/megooarti/security/api/auth.py`, `backend/src/megooarti/main.py`, `frontend/openapi.json` (written by a command), `docs/administration.md`
- Test: `backend/tests/security/test_sources_api.py`; modify `backend/tests/test_route_guards.py`

**Interfaces:**
- Consumes: Task 2's `sources` and test kinds; `pagination.Page`, `PageParams`, `page`; `require`.
- Produces:
  - `GET`/`POST /api/v1/auth-sources`, `GET`/`PUT`/`DELETE /api/v1/auth-sources/{id}`, `PUT /api/v1/auth-sources/order` (`{"ids": [...]}`), `POST /api/v1/auth-sources/{id}/test` (`{"username"?, "password"?}` → `TestOut {ok, message, user}`); schemas `SourceOut` (`id`, `kind`, `name`, `enabled`, `position`, `settings`, `secrets`, `group_mapping`, `users`, `created_at`, `updated_at`), `SourceIn`, `SourceCreate`, `Mapping`, `TestOut`, `TestedUser`.
  - `GET /api/v1/auth/sources` (open): `Page[SignInSource]` (`id`, `name`, `kind`).
  - `UserOut.source` (the source's name) and `UserOut.external_id`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/test_sources_api.py`:

```python
"""The sign-in sources' API (spec 4.3): kept, shown without their secrets, ordered,
tested and deleted; and the list the sign-in screen shows before anyone signs in."""

import uuid

import pytest
from sqlalchemy import select

from megooarti.security import roles
from megooarti.security.models import AuthSource
from tests.accounts import PASSWORD, basic, error_code
from tests.security.directory import SECRET, person

SOURCES = "/api/v1/auth-sources"
LOGIN = "/api/v1/auth/login"


def directory(name: str = "corp", **more) -> dict:
    return {
        "kind": "directory",
        "name": name,
        "settings": {"people": {"ann": person("ann pw", "staff")}, "secret": SECRET},
        **more,
    }


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def test_sources_need_the_security_permissions(client, make_user, sessionmaker, kinds):
    await make_role(sessionmaker, "security-reader", "admin:security:read")
    await make_user("rita", roles=["security-reader"])
    as_rita = basic("rita", PASSWORD)

    nobody = await client.get(SOURCES)
    reads = await client.get(SOURCES, headers=as_rita)
    writes = await client.post(SOURCES, json=directory(), headers=as_rita)

    assert (nobody.status_code, reads.status_code, writes.status_code) == (401, 200, 403)


async def test_a_source_is_kept_off_and_last_with_its_secret_sealed_and_never_shown(
    admin_client, sessionmaker, kinds
):
    await make_role(sessionmaker, "staff", "repository:*:*:read")
    first = await admin_client.post(SOURCES, json=directory("first"))
    made = await admin_client.post(
        SOURCES,
        json=directory("second", group_mapping=[{"group": "staff", "roles": ["staff"]}]),
    )
    async with sessionmaker() as db:
        kept = await db.scalar(select(AuthSource).where(AuthSource.name == "second"))

    assert (first.status_code, made.status_code) == (201, 201)
    body = made.json()
    assert (body["kind"], body["enabled"], body["position"], body["users"]) == (
        "directory",
        False,
        1,
        0,
    )
    assert body["secrets"] == ["secret"]
    assert "secret" not in body["settings"]
    assert SECRET not in made.text
    assert kept.settings["secret"] != SECRET  # sealed
    assert body["group_mapping"] == [{"group": "staff", "roles": ["staff"]}]


async def test_a_change_without_the_secret_keeps_it(admin_client, kinds):
    made = (await admin_client.post(SOURCES, json=directory())).json()

    changed = await admin_client.put(
        f"{SOURCES}/{made['id']}",
        json={"name": "corp", "enabled": True, "settings": made["settings"], "group_mapping": []},
    )
    # The directory answers only with the secret it was given: it was kept, and unsealed.
    signed_in = await admin_client.post(f"{SOURCES}/{made['id']}/test", json={})

    assert changed.json()["secrets"] == ["secret"]
    assert changed.json()["enabled"] is True
    assert signed_in.json() == {"ok": True, "message": "The directory answered.", "user": None}


@pytest.mark.parametrize(
    ("sent", "field"),
    [
        ({"kind": "smoke-signals"}, "kind"),
        ({"name": "local"}, "name"),
        ({"name": "Local"}, "name"),
        ({"name": " leading space"}, "body.name"),
        ({"name": "x" * 65}, "body.name"),
        ({"settings": {"people": "everyone"}}, "settings.people"),
        ({"group_mapping": [{"group": "staff", "roles": ["no-such-role"]}]}, "group_mapping"),
        ({"group_mapping": [{"group": "", "roles": []}]}, "body.group_mapping.0.group"),
    ],
)
async def test_what_is_wrong_with_a_source_is_said_where_it_is(admin_client, kinds, sent, field):
    refused = await admin_client.post(SOURCES, json={**directory(), **sent})

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == field


async def test_two_sources_are_not_called_alike(admin_client, kinds):
    await admin_client.post(SOURCES, json=directory("Corp"))

    again = await admin_client.post(SOURCES, json=directory("corp"))

    assert (again.status_code, error_code(again)) == (409, "conflict")


async def test_the_sources_are_put_in_the_order_given_and_asked_in_it(
    admin_client, other_client, kinds
):
    ids = []
    for name, password in (("first", "first pw"), ("second", "second pw")):
        sent = directory(name, enabled=True)
        sent["settings"]["people"] = {"bo": person(password)}
        ids.append((await admin_client.post(SOURCES, json=sent)).json()["id"])

    ordered = await admin_client.put(f"{SOURCES}/order", json={"ids": ids[::-1]})
    listed = await admin_client.get(SOURCES)
    signed_in = await other_client.post(LOGIN, json={"username": "bo", "password": "second pw"})

    assert [item["name"] for item in ordered.json()["items"]] == ["second", "first"]
    assert [(item["name"], item["position"]) for item in listed.json()["items"]] == [
        ("second", 0),
        ("first", 1),
    ]
    assert signed_in.status_code == 200


@pytest.mark.parametrize("which", ["missing", "twice", "stranger"])
async def test_an_order_names_every_source_once(admin_client, kinds, which):
    one = (await admin_client.post(SOURCES, json=directory("one"))).json()["id"]
    two = (await admin_client.post(SOURCES, json=directory("two"))).json()["id"]
    ids = {"missing": [one], "twice": [one, two, one], "stranger": [one, str(uuid.uuid4())]}

    refused = await admin_client.put(f"{SOURCES}/order", json={"ids": ids[which]})

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")


async def test_a_test_says_who_the_source_says_someone_is_and_what_they_would_be_given(
    admin_client, sessionmaker, kinds
):
    await make_role(sessionmaker, "staff", "repository:*:*:read")
    made = (
        await admin_client.post(
            SOURCES, json=directory(group_mapping=[{"group": "STAFF", "roles": ["staff"]}])
        )
    ).json()

    tried = await admin_client.post(
        f"{SOURCES}/{made['id']}/test", json={"username": "ann", "password": "ann pw"}
    )
    wrong = await admin_client.post(
        f"{SOURCES}/{made['id']}/test", json={"username": "ann", "password": "no"}
    )
    users = (await admin_client.get("/api/v1/users", params={"limit": 200})).json()

    assert tried.json() == {
        "ok": True,
        "message": "ann signed in.",
        "user": {
            "external_id": "uid=ann,ou=people",
            "username": "ann",
            "display_name": "Ann",
            "email": None,
            "groups": ["staff"],
            "roles": ["staff"],
        },
    }
    assert (wrong.json()["ok"], wrong.json()["user"]) == (False, None)
    assert "ann" not in [user["username"] for user in users["items"]]  # nobody was made


async def test_a_source_that_does_not_answer_says_so_when_tested(admin_client, kinds):
    sent = directory()
    sent["settings"]["down"] = True
    made = (await admin_client.post(SOURCES, json=sent)).json()

    tried = await admin_client.post(f"{SOURCES}/{made['id']}/test", json={})

    assert tried.json() == {"ok": False, "message": "the directory did not answer", "user": None}


async def test_deleting_a_source_disables_and_keeps_its_users(admin_client, other_client, kinds):
    made = (await admin_client.post(SOURCES, json=directory(enabled=True))).json()
    await other_client.post(LOGIN, json={"username": "ann", "password": "ann pw"})
    counted = (await admin_client.get(f"{SOURCES}/{made['id']}")).json()["users"]

    deleted = await admin_client.delete(f"{SOURCES}/{made['id']}")
    session = (await other_client.get("/api/v1/auth/session")).json()
    users = (await admin_client.get("/api/v1/users", params={"limit": 200})).json()["items"]
    ann = next(user for user in users if user["username"] == "ann")
    gone = await admin_client.get(f"{SOURCES}/{made['id']}")

    assert (counted, deleted.status_code, gone.status_code) == (1, 204, 404)
    assert session["authenticated"] is False
    assert (ann["status"], ann["source"], ann["external_id"]) == (
        "disabled",
        None,
        "uid=ann,ou=people",
    )


async def test_a_user_shows_the_source_they_sign_in_through(admin_client, other_client, kinds):
    await admin_client.post(SOURCES, json=directory("Corp", enabled=True))
    await other_client.post(LOGIN, json={"username": "ann", "password": "ann pw"})

    users = (await admin_client.get("/api/v1/users", params={"limit": 200})).json()["items"]
    by_name = {user["username"]: user for user in users}

    assert (by_name["ann"]["source"], by_name["ann"]["external_id"]) == (
        "Corp",
        "uid=ann,ou=people",
    )
    assert (by_name["root"]["source"], by_name["root"]["external_id"]) == (None, None)


async def test_the_sign_in_screen_is_told_the_enabled_sources_signed_in_to_in_the_browser(
    client, add_source
):
    await add_source("Corp SSO", kind="portal", issuer="https://sso.example")
    await add_source("Old SSO", kind="portal", enabled=False)
    await add_source("Corp LDAP")

    listed = await client.get("/api/v1/auth/sources")

    assert listed.status_code == 200
    assert [(item["name"], item["kind"]) for item in listed.json()["items"]] == [
        ("Corp SSO", "portal")
    ]
    assert set(listed.json()["items"][0]) == {"id", "name", "kind"}
```

Change `backend/tests/test_route_guards.py`:

```diff
@@ -16,6 +16,7 @@ OPEN = {
     "/api/v1/status/live",  # health checks, required to be unauthenticated (SYS-2)
     "/api/v1/status/ready",
     "/api/v1/auth/login",  # this is where credentials are presented
+    "/api/v1/auth/sources",  # the sources the sign-in screen offers, before anyone signs in
     # OAuth (MCP spec 7): what a client discovers is public (RFC 9728, RFC 8414); any
     # client may register (RFC 7591); authorize sends a person to the consent page, where
     # they sign in; token takes a code or a refresh token, which are the credentials.
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/security/test_sources_api.py tests/test_route_guards.py`
Expected: `/api/v1/auth-sources` answers `404` where `201`, `200` or `422` is expected (`KeyError: 'id'`, `assert (404, 'not_found') == (422, 'validation_error')`), and the route guard's walk does not find `/api/v1/auth/sources`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/security/users.py`:

```diff
@@ -35,6 +35,10 @@ class UserView:
     roles: list[str]
     created_at: datetime
     last_login_at: datetime | None
+    # The source they sign in through, by its name: None for MegooArti's own users, and
+    # for the users of a source that was deleted, who keep their `external_id`.
+    source: str | None
+    external_id: str | None
 
 
 def normalise_username(username: str) -> str:
@@ -106,6 +110,7 @@ async def describe(db: AsyncSession, user: User) -> UserView:
         .where(UserRole.user_id == user.id)
         .order_by(Role.name)
     )
+    source = None if user.source_id is None else await db.get(AuthSource, user.source_id)
     return UserView(
         id=user.id,
         username=user.username,
@@ -117,6 +122,8 @@ async def describe(db: AsyncSession, user: User) -> UserView:
         roles=list(names),
         created_at=user.created_at,
         last_login_at=user.last_login_at,
+        source=None if source is None else source.name,
+        external_id=user.external_id,
     )
 
 
```

Change `backend/src/megooarti/security/api/users.py`:

```diff
@@ -40,6 +40,10 @@ class UserOut(BaseModel):
     roles: list[str]
     created_at: datetime
     last_login_at: datetime | None
+    # The sign-in source they belong to, by its name; null for MegooArti's own users, and
+    # for those of a source that was deleted, who keep the identity they had there.
+    source: str | None
+    external_id: str | None
 
 
 class UserCreate(BaseModel):
```

Create `backend/src/megooarti/security/api/sources.py`:

```python
"""Administration of sign-in sources (spec 4.3): where people sign in from besides
MegooArti's own users, in the order they are asked."""

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security import sources
from megooarti.security.authentication import Principal, require
from megooarti.security.models import AuthSource

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth-sources", tags=["sign-in sources"])

# Shown on the sign-in screen, and part of a user's name where theirs is taken (name@source).
_NAME = r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$"


class Mapping(BaseModel):
    """The roles a member of a group is given (E4)."""

    group: str = Field(min_length=1, max_length=255)
    roles: list[str] = Field(max_length=50)


class SourceIn(BaseModel):
    name: str = Field(pattern=_NAME)
    enabled: bool = False
    # What its kind needs. A secret left out keeps the stored one (E5).
    settings: dict[str, Any] = {}
    group_mapping: list[Mapping] = Field(default=[], max_length=200)


class SourceCreate(SourceIn):
    kind: str = Field(max_length=16)


class SourceOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    enabled: bool
    position: int
    settings: dict[str, Any]  # without its secrets
    secrets: list[str]  # the names of the secrets that are set
    group_mapping: list[Mapping]
    users: int  # how many users sign in through it
    created_at: datetime
    updated_at: datetime


class Order(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=200)


class TestIn(BaseModel):
    """A name and a password to try, or nothing: only whether the source answers."""

    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=1024)


class TestedUser(BaseModel):
    external_id: str
    username: str
    display_name: str
    email: str | None
    groups: list[str]
    roles: list[str]  # what the group mapping gives them


class TestOut(BaseModel):
    ok: bool
    message: str
    user: TestedUser | None


async def _out(db: AsyncSession, source: AuthSource) -> SourceOut:
    settings, secrets = sources.shown_settings(sources.KINDS.get(source.kind), source.settings)
    return SourceOut(
        id=source.id,
        kind=source.kind,
        name=source.name,
        enabled=source.enabled,
        position=source.position,
        settings=settings,
        secrets=secrets,
        group_mapping=[Mapping(**entry) for entry in source.group_mapping],
        users=await sources.users_of(db, source),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


async def _load(db: AsyncSession, source_id: uuid.UUID) -> AuthSource:
    source = await sources.get_source(db, source_id)
    if source is None:
        raise ApiError(404, "not_found", "No such sign-in source.")
    return source


def _kind(name: str) -> sources.Kind:
    kind = sources.KINDS.get(name)
    if kind is None:
        choices = ", ".join(sorted(sources.KINDS)) or "none yet"
        raise sources.invalid("kind", f"Must be one of: {choices}.")
    return kind


async def _check_name(db: AsyncSession, name: str, own: uuid.UUID | None) -> None:
    if name.casefold() == "local":
        raise sources.invalid("name", "local is the name of MegooArti's own users.")
    holder = await db.scalar(
        select(AuthSource.id).where(func.lower(AuthSource.name) == name.lower())
    )
    if holder is not None and holder != own:
        raise ApiError(409, "conflict", f"A sign-in source named {name} already exists.")


async def _apply(
    db: AsyncSession, request: Request, source: AuthSource, body: SourceIn, kind: sources.Kind
) -> None:
    await _check_name(db, body.name, source.id)
    mapping = [entry.model_dump() for entry in body.group_mapping]
    await sources.check_mapping(db, mapping)
    source.settings = sources.kept_settings(
        request.app.state.settings, kind, body.settings, source.settings or None
    )
    source.name, source.enabled, source.group_mapping = body.name, body.enabled, mapping


@router.get("", response_model=Page[SourceOut])
async def list_sources(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:security:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The sources, in the order they are asked, after MegooArti's own users."""
    every = await sources.in_order(db)
    shown = every[params.offset : params.offset + params.limit]
    return page([await _out(db, source) for source in shown], len(every), params)


@router.post("", response_model=SourceOut, status_code=201)
async def create_source(
    body: SourceCreate,
    request: Request,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> SourceOut:
    """A new source, asked after every other. Test it before it is enabled."""
    kind = _kind(body.kind)
    source = AuthSource(kind=body.kind, position=await sources.next_position(db), settings={})
    await _apply(db, request, source, body, kind)
    db.add(source)
    await db.flush()
    result = await _out(db, source)
    await db.commit()
    log.info("auth_source_created", source=source.name, by=principal.user.username)
    return result


@router.put("/order", response_model=Page[SourceOut])
async def order_sources(
    body: Order,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Put the sources in the order they are to be asked: every one of them, once."""
    await sources.reorder(db, body.ids)
    every = await sources.in_order(db)
    items = [await _out(db, source) for source in every]
    await db.commit()
    log.info("auth_sources_ordered", by=principal.user.username)
    return page(items, len(items), PageParams(limit=200, offset=0))


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: uuid.UUID,
    _: Principal = Depends(require("admin:security:read")),
    db: AsyncSession = Depends(get_session),
) -> SourceOut:
    return await _out(db, await _load(db, source_id))


@router.put("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: uuid.UUID,
    body: SourceIn,
    request: Request,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> SourceOut:
    """Change a source; its kind stays. Turned off, its users are refused until it is on."""
    source = await _load(db, source_id)
    await _apply(db, request, source, body, _kind(source.kind))
    await db.flush()
    result = await _out(db, source)
    await db.commit()
    log.info("auth_source_updated", source=source.name, by=principal.user.username)
    return result


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a source. Its users are disabled, and kept with what they own."""
    source = await _load(db, source_id)
    await sources.delete_source(db, source)
    await db.commit()
    log.info("auth_source_deleted", source=source.name, by=principal.user.username)


@router.post("/{source_id}/test", response_model=TestOut)
async def test_source(
    source_id: uuid.UUID,
    body: TestIn,
    request: Request,
    _: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> TestOut:
    """Whether the source answers, and, given a name and a password, who it says they are
    and the roles they would be given. Nobody is signed in, or made, by it."""
    source = await _load(db, source_id)
    kind = _kind(source.kind)
    opened = sources.opened_settings(request.app.state.settings, kind, source.settings)
    try:
        tested = await kind.test(opened, body.username, body.password)
    except sources.SourceUnavailable as error:
        return TestOut(ok=False, message=str(error), user=None)
    found = tested.identity
    user = None
    if found is not None:
        user = TestedUser(
            external_id=found.external_id,
            username=found.username,
            display_name=found.display_name,
            email=found.email,
            groups=sorted(found.groups),
            roles=sources.mapped_role_names(source, found.groups),
        )
    return TestOut(ok=tested.ok, message=tested.message, user=user)
```

Change `backend/src/megooarti/security/api/auth.py`:

```diff
@@ -9,7 +9,8 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.clock import utcnow
 from megooarti.db.session import get_session
-from megooarti.security import sessions
+from megooarti.pagination import Page, PageParams, page
+from megooarti.security import sessions, sources
 from megooarti.security.authentication import (
     SESSION_COOKIE,
     Principal,
@@ -37,6 +38,14 @@ class UserSummary(BaseModel):
     email: str | None
 
 
+class SignInSource(BaseModel):
+    """A source the sign-in screen sends people to, to sign in there (spec 4.3)."""
+
+    id: uuid.UUID
+    name: str
+    kind: str
+
+
 class SessionInfo(BaseModel):
     authenticated: bool
     method: str | None
@@ -117,6 +126,20 @@ async def logout(
     response.delete_cookie(SESSION_COOKIE, path="/")
 
 
+@router.get("/sources", response_model=Page[SignInSource])
+async def sign_in_sources(
+    params: PageParams = Depends(), db: AsyncSession = Depends(get_session)
+) -> dict:
+    """The enabled sources people sign in to in the browser, for the sign-in screen. Asked
+    before anyone is signed in, so it says no more than their names."""
+    shown = [
+        SignInSource(id=source.id, name=source.name, kind=source.kind)
+        for source in await sources.in_order(db)
+        if source.enabled and (kind := sources.KINDS.get(source.kind)) and kind.in_browser
+    ]
+    return page(shown[params.offset : params.offset + params.limit], len(shown), params)
+
+
 @router.get("/session", response_model=SessionInfo)
 async def session(principal: Principal | None = Depends(current_principal)) -> SessionInfo:
     """Describe the caller. Answers 200 when nobody is signed in, so a UI can start here."""
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -39,6 +39,7 @@ from megooarti.security.api import auth as auth_api
 from megooarti.security.api import me as me_api
 from megooarti.security.api import oauth as oauth_api
 from megooarti.security.api import roles as roles_api
+from megooarti.security.api import sources as sources_api
 from megooarti.security.api import users as users_api
 from megooarti.security.bootstrap import ensure_initial_admin_password
 from megooarti.storage import blobs
@@ -153,6 +154,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.include_router(me_api.router, prefix=API_PREFIX)
     app.include_router(users_api.router, prefix=API_PREFIX)
     app.include_router(roles_api.router, prefix=API_PREFIX)
+    app.include_router(sources_api.router, prefix=API_PREFIX)
     app.include_router(settings_router, prefix=API_PREFIX)
     app.include_router(information_router, prefix=API_PREFIX)
     app.include_router(blob_stores_router, prefix=API_PREFIX)
```

Change `frontend/openapi.json`:

```diff
@@ -858,6 +858,31 @@
         "title": "LoginRequest",
         "type": "object"
       },
+      "Mapping": {
+        "description": "The roles a member of a group is given (E4).",
+        "properties": {
+          "group": {
+            "maxLength": 255,
+            "minLength": 1,
+            "title": "Group",
+            "type": "string"
+          },
+          "roles": {
+            "items": {
+              "type": "string"
+            },
+            "maxItems": 50,
+            "title": "Roles",
+            "type": "array"
+          }
+        },
+        "required": [
+          "group",
+          "roles"
+        ],
+        "title": "Mapping",
+        "type": "object"
+      },
       "NegativeCache": {
         "properties": {
           "enabled": {
@@ -875,6 +900,24 @@
         "title": "NegativeCache",
         "type": "object"
       },
+      "Order": {
+        "properties": {
+          "ids": {
+            "items": {
+              "format": "uuid",
+              "type": "string"
+            },
+            "maxItems": 200,
+            "title": "Ids",
+            "type": "array"
+          }
+        },
+        "required": [
+          "ids"
+        ],
+        "title": "Order",
+        "type": "object"
+      },
       "Page_BlobStoreOut_": {
         "properties": {
           "items": {
@@ -1123,6 +1166,68 @@
         "title": "Page[RoleOut]",
         "type": "object"
       },
+      "Page_SignInSource_": {
+        "properties": {
+          "items": {
+            "items": {
+              "$ref": "#/components/schemas/SignInSource"
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
+        "title": "Page[SignInSource]",
+        "type": "object"
+      },
+      "Page_SourceOut_": {
+        "properties": {
+          "items": {
+            "items": {
+              "$ref": "#/components/schemas/SourceOut"
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
+        "title": "Page[SourceOut]",
+        "type": "object"
+      },
       "Page_TokenInfo_": {
         "properties": {
           "items": {
@@ -2059,6 +2164,31 @@
         "title": "SignInSettings",
         "type": "object"
       },
+      "SignInSource": {
+        "description": "A source the sign-in screen sends people to, to sign in there (spec 4.3).",
+        "properties": {
+          "id": {
+            "format": "uuid",
+            "title": "Id",
+            "type": "string"
+          },
+          "kind": {
+            "title": "Kind",
+            "type": "string"
+          },
+          "name": {
+            "title": "Name",
+            "type": "string"
+          }
+        },
+        "required": [
+          "id",
+          "name",
+          "kind"
+        ],
+        "title": "SignInSource",
+        "type": "object"
+      },
       "SigningKeyGenerate": {
         "properties": {
           "algorithm": {
@@ -2134,108 +2264,366 @@
         "title": "SigningKeyOut",
         "type": "object"
       },
-      "TokenCreate": {
+      "SourceCreate": {
         "properties": {
-          "expires_at": {
-            "anyOf": [
-              {
-                "format": "date-time",
-                "type": "string"
-              },
-              {
-                "type": "null"
-              }
-            ],
-            "title": "Expires At"
+          "enabled": {
+            "default": false,
+            "title": "Enabled",
+            "type": "boolean"
+          },
+          "group_mapping": {
+            "default": [],
+            "items": {
+              "$ref": "#/components/schemas/Mapping"
+            },
+            "maxItems": 200,
+            "title": "Group Mapping",
+            "type": "array"
+          },
+          "kind": {
+            "maxLength": 16,
+            "title": "Kind",
+            "type": "string"
           },
           "name": {
-            "maxLength": 100,
-            "minLength": 1,
+            "pattern": "^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$",
             "title": "Name",
             "type": "string"
           },
-          "scopes": {
-            "anyOf": [
-              {
-                "items": {
-                  "type": "string"
-                },
-                "type": "array"
-              },
-              {
-                "type": "null"
-              }
-            ],
-            "title": "Scopes"
+          "settings": {
+            "additionalProperties": true,
+            "default": {},
+            "title": "Settings",
+            "type": "object"
+          }
+        },
+        "required": [
+          "name",
+          "kind"
+        ],
+        "title": "SourceCreate",
+        "type": "object"
+      },
+      "SourceIn": {
+        "properties": {
+          "enabled": {
+            "default": false,
+            "title": "Enabled",
+            "type": "boolean"
+          },
+          "group_mapping": {
+            "default": [],
+            "items": {
+              "$ref": "#/components/schemas/Mapping"
+            },
+            "maxItems": 200,
+            "title": "Group Mapping",
+            "type": "array"
+          },
+          "name": {
+            "pattern": "^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$",
+            "title": "Name",
+            "type": "string"
+          },
+          "settings": {
+            "additionalProperties": true,
+            "default": {},
+            "title": "Settings",
+            "type": "object"
           }
         },
         "required": [
           "name"
         ],
-        "title": "TokenCreate",
+        "title": "SourceIn",
         "type": "object"
       },
-      "TokenCreated": {
+      "SourceOut": {
         "properties": {
           "created_at": {
             "format": "date-time",
             "title": "Created At",
             "type": "string"
           },
-          "display_prefix": {
-            "title": "Display Prefix",
-            "type": "string"
+          "enabled": {
+            "title": "Enabled",
+            "type": "boolean"
           },
-          "expires_at": {
-            "anyOf": [
-              {
-                "format": "date-time",
-                "type": "string"
-              },
-              {
-                "type": "null"
-              }
-            ],
-            "title": "Expires At"
+          "group_mapping": {
+            "items": {
+              "$ref": "#/components/schemas/Mapping"
+            },
+            "title": "Group Mapping",
+            "type": "array"
           },
           "id": {
             "format": "uuid",
             "title": "Id",
             "type": "string"
           },
-          "last_used_at": {
+          "kind": {
+            "title": "Kind",
+            "type": "string"
+          },
+          "name": {
+            "title": "Name",
+            "type": "string"
+          },
+          "position": {
+            "title": "Position",
+            "type": "integer"
+          },
+          "secrets": {
+            "items": {
+              "type": "string"
+            },
+            "title": "Secrets",
+            "type": "array"
+          },
+          "settings": {
+            "additionalProperties": true,
+            "title": "Settings",
+            "type": "object"
+          },
+          "updated_at": {
+            "format": "date-time",
+            "title": "Updated At",
+            "type": "string"
+          },
+          "users": {
+            "title": "Users",
+            "type": "integer"
+          }
+        },
+        "required": [
+          "id",
+          "kind",
+          "name",
+          "enabled",
+          "position",
+          "settings",
+          "secrets",
+          "group_mapping",
+          "users",
+          "created_at",
+          "updated_at"
+        ],
+        "title": "SourceOut",
+        "type": "object"
+      },
+      "TestIn": {
+        "description": "A name and a password to try, or nothing: only whether the source answers.",
+        "properties": {
+          "password": {
             "anyOf": [
               {
-                "format": "date-time",
+                "maxLength": 1024,
                 "type": "string"
               },
               {
                 "type": "null"
               }
             ],
-            "title": "Last Used At"
-          },
-          "name": {
-            "title": "Name",
-            "type": "string"
+            "title": "Password"
           },
-          "scopes": {
+          "username": {
             "anyOf": [
               {
-                "items": {
-                  "type": "string"
-                },
-                "type": "array"
+                "maxLength": 128,
+                "type": "string"
               },
               {
                 "type": "null"
               }
             ],
-            "title": "Scopes"
-          },
-          "token": {
-            "title": "Token",
-            "type": "string"
+            "title": "Username"
+          }
+        },
+        "title": "TestIn",
+        "type": "object"
+      },
+      "TestOut": {
+        "properties": {
+          "message": {
+            "title": "Message",
+            "type": "string"
+          },
+          "ok": {
+            "title": "Ok",
+            "type": "boolean"
+          },
+          "user": {
+            "anyOf": [
+              {
+                "$ref": "#/components/schemas/TestedUser"
+              },
+              {
+                "type": "null"
+              }
+            ]
+          }
+        },
+        "required": [
+          "ok",
+          "message",
+          "user"
+        ],
+        "title": "TestOut",
+        "type": "object"
+      },
+      "TestedUser": {
+        "properties": {
+          "display_name": {
+            "title": "Display Name",
+            "type": "string"
+          },
+          "email": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Email"
+          },
+          "external_id": {
+            "title": "External Id",
+            "type": "string"
+          },
+          "groups": {
+            "items": {
+              "type": "string"
+            },
+            "title": "Groups",
+            "type": "array"
+          },
+          "roles": {
+            "items": {
+              "type": "string"
+            },
+            "title": "Roles",
+            "type": "array"
+          },
+          "username": {
+            "title": "Username",
+            "type": "string"
+          }
+        },
+        "required": [
+          "external_id",
+          "username",
+          "display_name",
+          "email",
+          "groups",
+          "roles"
+        ],
+        "title": "TestedUser",
+        "type": "object"
+      },
+      "TokenCreate": {
+        "properties": {
+          "expires_at": {
+            "anyOf": [
+              {
+                "format": "date-time",
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Expires At"
+          },
+          "name": {
+            "maxLength": 100,
+            "minLength": 1,
+            "title": "Name",
+            "type": "string"
+          },
+          "scopes": {
+            "anyOf": [
+              {
+                "items": {
+                  "type": "string"
+                },
+                "type": "array"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Scopes"
+          }
+        },
+        "required": [
+          "name"
+        ],
+        "title": "TokenCreate",
+        "type": "object"
+      },
+      "TokenCreated": {
+        "properties": {
+          "created_at": {
+            "format": "date-time",
+            "title": "Created At",
+            "type": "string"
+          },
+          "display_prefix": {
+            "title": "Display Prefix",
+            "type": "string"
+          },
+          "expires_at": {
+            "anyOf": [
+              {
+                "format": "date-time",
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Expires At"
+          },
+          "id": {
+            "format": "uuid",
+            "title": "Id",
+            "type": "string"
+          },
+          "last_used_at": {
+            "anyOf": [
+              {
+                "format": "date-time",
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Last Used At"
+          },
+          "name": {
+            "title": "Name",
+            "type": "string"
+          },
+          "scopes": {
+            "anyOf": [
+              {
+                "items": {
+                  "type": "string"
+                },
+                "type": "array"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Scopes"
+          },
+          "token": {
+            "title": "Token",
+            "type": "string"
           }
         },
         "required": [
@@ -2448,6 +2836,17 @@
             ],
             "title": "Email"
           },
+          "external_id": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "External Id"
+          },
           "id": {
             "format": "uuid",
             "title": "Id",
@@ -2476,6 +2875,17 @@
             "title": "Roles",
             "type": "array"
           },
+          "source": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Source"
+          },
           "status": {
             "title": "Status",
             "type": "string"
@@ -2495,7 +2905,9 @@
           "builtin",
           "roles",
           "created_at",
-          "last_login_at"
+          "last_login_at",
+          "source",
+          "external_id"
         ],
         "title": "UserOut",
         "type": "object"
@@ -2605,25 +3017,41 @@
   },
   "openapi": "3.1.0",
   "paths": {
-    "/api/v1/auth/login": {
-      "post": {
-        "operationId": "login_api_v1_auth_login_post",
-        "requestBody": {
-          "content": {
-            "application/json": {
-              "schema": {
-                "$ref": "#/components/schemas/LoginRequest"
-              }
+    "/api/v1/auth-sources": {
+      "get": {
+        "description": "The sources, in the order they are asked, after MegooArti's own users.",
+        "operationId": "list_sources_api_v1_auth_sources_get",
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
             }
           },
-          "required": true
-        },
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
         "responses": {
           "200": {
             "content": {
               "application/json": {
                 "schema": {
-                  "$ref": "#/components/schemas/SessionInfo"
+                  "$ref": "#/components/schemas/Page_SourceOut_"
                 }
               }
             },
@@ -2640,17 +3068,33 @@
             "description": "Any error."
           }
         },
-        "summary": "Login",
+        "summary": "List Sources",
         "tags": [
-          "authentication"
+          "sign-in sources"
         ]
-      }
-    },
-    "/api/v1/auth/logout": {
+      },
       "post": {
-        "operationId": "logout_api_v1_auth_logout_post",
+        "description": "A new source, asked after every other. Test it before it is enabled.",
+        "operationId": "create_source_api_v1_auth_sources_post",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/SourceCreate"
+              }
+            }
+          },
+          "required": true
+        },
         "responses": {
-          "204": {
+          "201": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SourceOut"
+                }
+              }
+            },
             "description": "Successful Response"
           },
           "default": {
@@ -2664,17 +3108,308 @@
             "description": "Any error."
           }
         },
-        "summary": "Logout",
+        "summary": "Create Source",
         "tags": [
-          "authentication"
+          "sign-in sources"
         ]
       }
     },
-    "/api/v1/auth/session": {
-      "get": {
-        "description": "Describe the caller. Answers 200 when nobody is signed in, so a UI can start here.",
-        "operationId": "session_api_v1_auth_session_get",
-        "responses": {
+    "/api/v1/auth-sources/order": {
+      "put": {
+        "description": "Put the sources in the order they are to be asked: every one of them, once.",
+        "operationId": "order_sources_api_v1_auth_sources_order_put",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/Order"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Page_SourceOut_"
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
+        "summary": "Order Sources",
+        "tags": [
+          "sign-in sources"
+        ]
+      }
+    },
+    "/api/v1/auth-sources/{source_id}": {
+      "delete": {
+        "description": "Delete a source. Its users are disabled, and kept with what they own.",
+        "operationId": "delete_source_api_v1_auth_sources__source_id__delete",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "source_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "Source Id",
+              "type": "string"
+            }
+          }
+        ],
+        "responses": {
+          "204": {
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
+        "summary": "Delete Source",
+        "tags": [
+          "sign-in sources"
+        ]
+      },
+      "get": {
+        "operationId": "get_source_api_v1_auth_sources__source_id__get",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "source_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "Source Id",
+              "type": "string"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SourceOut"
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
+        "summary": "Get Source",
+        "tags": [
+          "sign-in sources"
+        ]
+      },
+      "put": {
+        "description": "Change a source; its kind stays. Turned off, its users are refused until it is on.",
+        "operationId": "update_source_api_v1_auth_sources__source_id__put",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "source_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "Source Id",
+              "type": "string"
+            }
+          }
+        ],
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/SourceIn"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SourceOut"
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
+        "summary": "Update Source",
+        "tags": [
+          "sign-in sources"
+        ]
+      }
+    },
+    "/api/v1/auth-sources/{source_id}/test": {
+      "post": {
+        "description": "Whether the source answers, and, given a name and a password, who it says they are\nand the roles they would be given. Nobody is signed in, or made, by it.",
+        "operationId": "test_source_api_v1_auth_sources__source_id__test_post",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "source_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "Source Id",
+              "type": "string"
+            }
+          }
+        ],
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/TestIn"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/TestOut"
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
+        "summary": "Test Source",
+        "tags": [
+          "sign-in sources"
+        ]
+      }
+    },
+    "/api/v1/auth/login": {
+      "post": {
+        "operationId": "login_api_v1_auth_login_post",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/LoginRequest"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SessionInfo"
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
+        "summary": "Login",
+        "tags": [
+          "authentication"
+        ]
+      }
+    },
+    "/api/v1/auth/logout": {
+      "post": {
+        "operationId": "logout_api_v1_auth_logout_post",
+        "responses": {
+          "204": {
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
+        "summary": "Logout",
+        "tags": [
+          "authentication"
+        ]
+      }
+    },
+    "/api/v1/auth/session": {
+      "get": {
+        "description": "Describe the caller. Answers 200 when nobody is signed in, so a UI can start here.",
+        "operationId": "session_api_v1_auth_session_get",
+        "responses": {
           "200": {
             "content": {
               "application/json": {
@@ -2702,6 +3437,63 @@
         ]
       }
     },
+    "/api/v1/auth/sources": {
+      "get": {
+        "description": "The enabled sources people sign in to in the browser, for the sign-in screen. Asked\nbefore anyone is signed in, so it says no more than their names.",
+        "operationId": "sign_in_sources_api_v1_auth_sources_get",
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
+                  "$ref": "#/components/schemas/Page_SignInSource_"
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
+        "summary": "Sign In Sources",
+        "tags": [
+          "authentication"
+        ]
+      }
+    },
     "/api/v1/blob-stores": {
       "get": {
         "operationId": "list_blob_stores_api_v1_blob_stores_get",
```

Change `docs/administration.md`:

```diff
@@ -37,6 +37,42 @@ Users, roles, your own API tokens and anonymous access are managed in the web UI
   are: see [Installation](installation.md#behind-your-own-reverse-proxy).
 - Requests without credentials can only ever be allowed `repository:` permissions,
   whatever roles the `anonymous` user holds.
+- A **default role**, set at `PUT /api/v1/settings/default-role`, is held by every
+  signed-in user besides their own roles, and kept on none of them. It is not a
+  visitor's: anonymous access has the `anonymous` user's roles alone.
+
+### Sign-in sources
+
+People can sign in with the accounts their organisation already has: an LDAP
+directory, an OIDC provider, or a reverse proxy that says who they are. Each is a
+**sign-in source**, kept under `/api/v1/auth-sources` and on the Authentication screen.
+
+- **Who belongs where.** A user belongs to one source: MegooArti's own users, or one
+  of the sources, which knows them by an identity of its own (an LDAP DN, an OIDC
+  subject). A user of a source has no password here: theirs is the source's, and
+  setting one is refused with `409 external_user`.
+- **The first sign-in makes the user.** Their name, display name and email are the
+  source's. Where another user has the name already, they are called
+  `name@source`. At each sign-in after, the same are brought up to date.
+- **Groups give roles.** A source's group mapping gives the members of a group the
+  roles it names. At each sign-in, the roles the groups no longer give are taken
+  back; the roles an administrator gave by hand are kept.
+- **The order.** A user signs in where they belong. A name nobody has yet is asked of
+  each enabled source that takes a password, from the first, and the first that
+  knows the name decides: a wrong password there is not tried anywhere else. The
+  order is set at `PUT /api/v1/auth-sources/order`.
+- **On and off.** A new source is off: test it first, at
+  `POST /api/v1/auth-sources/{id}/test`. While a source is off, its users are refused
+  as disabled users are: their sessions and API tokens too. A source that does not
+  answer is said by name: `503 source_unavailable`.
+- **MegooArti's own users** can be turned off at `PUT /api/v1/settings/local-sign-in`.
+  The built-in `admin` still signs in with its password, whatever is on or off, so
+  nobody is ever locked out; it must hold full access for this to be allowed. Every
+  other user of ours is refused while it is off.
+- **Deleting a source** disables its users and keeps them, with their tokens and
+  what they own.
+- The sign-in screen asks `GET /api/v1/auth/sources`, open to anyone, for the sources
+  people sign in to in the browser.
 
 The full API is described at `/api/docs`. The page is served with its own script and
 stylesheet, and asks nothing of another host.
```

Then write the API's description again: (in `backend/`) `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/security tests/test_route_guards.py tests/test_openapi_snapshot.py tests/test_documents.py`
Expected: 466 passed.

- [ ] **Step 5: Commit**

```bash
git add backend frontend/openapi.json docs/administration.md
git commit -m "feat(security): the sign-in sources' API: kept with their secrets sealed, ordered, tested, deleted; the sign-in screen's list"
```

---

### Task 4: The Authentication screen, a user's source, and what the plan settled

**Files:**
- Create: `frontend/src/screens/authentication.tsx`, `frontend/src/app/(shell)/admin/authentication/page.tsx`
- Modify: `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api`), `frontend/src/lib/api/types.ts`, `frontend/src/lib/paths.ts`, `frontend/src/lib/navigation.ts`, `frontend/src/lib/security.ts`, `frontend/messages/en.json`, `frontend/src/screens/user.tsx`, `docs/web-ui.md`, `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`
- Test: `frontend/src/screens/authentication.test.tsx`; modify `frontend/src/screens/security.test.tsx`, `frontend/src/lib/navigation.test.ts`, `frontend/src/components/shell.test.tsx`

**Interfaces:**
- Consumes: Tasks 1 and 3's routes and schemas; the UI's `Table`, `StatusTag`, `ConfirmDialog`, `SelectField`, `Facts`, `useNotify`, `useEveryRole`.
- Produces: `AUTHENTICATION`; the navigation item `authentication` (`admin:security:read`); `useSignInSettings`, `useSetDefaultRole`, `useSetLocalSignIn`, `useSources`, `useUpdateSource`, `useOrderSources`, `useDeleteSource`, `useTestSource`; `AuthenticationScreen`; the types `SignInSettings`, `SourceOut`, `SourceIn`, `SourceTested`; the messages `authentication.*`, `nav.items.authentication`, `users.facts.source`, `users.localUser`, `users.deletedSource`, `users.externalPassword*`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/authentication.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { AuthenticationScreen } from "./authentication";

const page = (items: unknown[], total = items.length) => ({ items, total, limit: 200, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

const source = (name: string, position: number, more: Record<string, unknown> = {}) => ({
  id: name.toLowerCase().replace(" ", "-"),
  kind: "ldap",
  name,
  enabled: true,
  position,
  settings: { url: "ldaps://ldap.example" },
  secrets: ["bind_password"],
  group_mapping: [{ group: "developers", roles: ["deployers"] }],
  users: 3,
  created_at: "2026-10-19T08:00:00Z",
  updated_at: "2026-10-19T08:00:00Z",
  ...more,
});
const CORP = source("Corp LDAP", 0);
const LAB = source("Lab LDAP", 1, { enabled: false, users: 0 });
const SIGN_IN = { default_role: null, local_sign_in: { enabled: true } };
const ROLES = page(
  ["admin", "anonymous", "deployers"].map((name) => ({
    name,
    description: "",
    builtin: name !== "deployers",
    permissions: [],
    roles: [],
  })),
);

function authentication(more: Routes = {}, session = ADMIN) {
  const api = mockApi({
    "GET /settings/sign-in": { json: SIGN_IN },
    "GET /auth-sources": { json: page([CORP, LAB]) },
    "GET /roles": { json: ROLES },
    "GET /auth/session": { json: session },
    ...more,
  });
  navigation.at("/admin/authentication");
  return { ...renderUi(<AuthenticationScreen />, { session }), ...api };
}

/** The rows of the table of sources, each as the text of its cells. */
async function rows() {
  const table = await screen.findByRole("table", { name: "Sign-in sources" });
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .slice(0, 4)
        .map((cell) => cell.textContent),
    );
}

describe("the sign-in sources (SEC-15)", () => {
  test("are MegooArti's own users first, then each source in the order it is asked", async () => {
    authentication();

    expect(await rows()).toEqual([
      ["MegooArti's own users", "local", "", "On"],
      ["Corp LDAP", "ldap", "3", "On"],
      ["Lab LDAP", "ldap", "0", "Off"],
    ]);
    expect(screen.getByRole("button", { name: "Move Corp LDAP up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move Lab LDAP down" })).toBeDisabled();
    await expectAccessible();
  });

  test("say so when there is none but ours", async () => {
    authentication({ "GET /auth-sources": { json: page([]) } });

    expect(await screen.findByText(/There is no other source yet/)).toBeVisible();
  });

  test("are moved by sending the whole order, and shown in the order the server answers", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "PUT /auth-sources/order": {
        json: page([
          { ...LAB, position: 0 },
          { ...CORP, position: 1 },
        ]),
      },
    });

    await user.click(await screen.findByRole("button", { name: "Move Lab LDAP up" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Moved Lab LDAP."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ ids: ["lab-ldap", "corp-ldap"] });
    expect((await rows()).map((row) => row[0])).toEqual([
      "MegooArti's own users",
      "Lab LDAP",
      "Corp LDAP",
    ]);
  });

  test("are turned on and off with what they have, their secrets kept by the server", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "PUT /auth-sources/lab-ldap": (call) => ({
        json: { ...LAB, ...(call.body as object) },
      }),
    });

    await user.click(await screen.findByRole("button", { name: "Turn on Lab LDAP" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Lab LDAP is on."));
    expect(of(calls, "PUT")[0]?.body).toEqual({
      name: "Lab LDAP",
      enabled: true,
      settings: { url: "ldaps://ldap.example" },
      group_mapping: [{ group: "developers", roles: ["deployers"] }],
    });
  });

  test("are tested, and what the test found is said", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "POST /auth-sources/corp-ldap/test": {
        json: { ok: false, message: "ldap.example did not answer.", user: null },
      },
    });

    await user.click(await screen.findByRole("button", { name: "Test Corp LDAP" }));

    expect(await screen.findByText("ldap.example did not answer.")).toBeVisible();
    expect(of(calls, "POST")[0]?.body).toEqual({});
  });

  test("are deleted only for whoever types the name, and say their users are kept", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({ "DELETE /auth-sources/corp-ldap": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete Corp LDAP" }));
    const dialog = screen.getByRole("alertdialog", {
      name: "Delete the sign-in source Corp LDAP?",
    });
    expect(dialog).toHaveTextContent("3 users are disabled, and kept with what they own.");
    expect(within(dialog).getByRole("button", { name: "Delete source" })).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox"), "Corp LDAP");
    await user.click(within(dialog).getByRole("button", { name: "Delete source" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Deleted the sign-in source Corp LDAP."),
    );
    expect(of(calls, "DELETE")).toHaveLength(1);
  });

  test("say what the server refuses", async () => {
    const user = userEvent.setup();
    authentication({
      "PUT /auth-sources/order": failure(422, "validation_error", "Give every source once."),
    });

    await user.click(await screen.findByRole("button", { name: "Move Lab LDAP up" }));

    expect(await screen.findByText(/Give every source once/)).toBeVisible();
  });

  test("are shown, and not changed, to whoever may only read them", async () => {
    authentication({}, holding("admin:security:read"));

    expect((await rows()).length).toBe(3);
    expect(screen.queryByRole("button", { name: /Delete|Turn|Move|Test/ })).toBeNull();
    expect(screen.getByText("None")).toBeVisible();
    expect(screen.queryByLabelText("Default role")).toBeNull();
  });
});

describe("MegooArti's own users (E1)", () => {
  test("are turned off only after saying that only admin will sign in here", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "PUT /settings/local-sign-in": (call) => ({
        json: { ...SIGN_IN, local_sign_in: call.body },
      }),
    });

    const [local] = await rows();
    expect(local).toEqual(["MegooArti's own users", "local", "", "On"]);
    await user.click(screen.getByRole("button", { name: "Turn off" }));
    const dialog = screen.getByRole("alertdialog", { name: "Turn off MegooArti's own users?" });
    expect(dialog).toHaveTextContent("Only the built-in admin will sign in");
    expect(of(calls, "PUT")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Turn off" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent(
        "Only the built-in admin signs in as one of MegooArti's own users now.",
      ),
    );
    expect(of(calls, "PUT")[0]?.body).toEqual({ enabled: false });
    // What the person who did it may do can have changed with it.
    await waitFor(() =>
      expect(of(calls, "GET").some((c) => c.path === "/auth/session")).toBe(true),
    );
  });

  test("say why they stay on when the server refuses", async () => {
    const user = userEvent.setup();
    authentication({
      "PUT /settings/local-sign-in": failure(
        409,
        "last_administrator",
        "This change would leave no active user with full access.",
      ),
    });

    await user.click(await screen.findByRole("button", { name: "Turn off" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Turn off" }),
    );

    expect(
      await screen.findByText(/This change would leave no active user with full access/),
    ).toBeVisible();
  });
});

describe("the default role (SEC-16)", () => {
  test("is none until one is chosen, and is saved as it is chosen", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "PUT /settings/default-role": (call) => ({ json: { ...SIGN_IN, ...(call.body as object) } }),
    });

    const chooser = await screen.findByLabelText("Default role");
    expect(chooser).toHaveValue("");
    await user.selectOptions(chooser, "deployers");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Every signed-in user has the role deployers."),
    );
    expect(of(calls, "PUT")[0]?.body).toEqual({ default_role: "deployers" });
  });

  test("is taken away by choosing none", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "GET /settings/sign-in": { json: { ...SIGN_IN, default_role: "deployers" } },
      "PUT /settings/default-role": (call) => ({ json: { ...SIGN_IN, ...(call.body as object) } }),
    });

    const chooser = await screen.findByLabelText("Default role");
    expect(chooser).toHaveValue("deployers");
    await user.selectOptions(chooser, "None");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("There is no default role."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ default_role: null });
  });
});
```

Change `frontend/src/screens/security.test.tsx`:

```diff
@@ -27,6 +27,8 @@ const person = (username: string, more: Record<string, unknown> = {}) => ({
   roles: [],
   created_at: "2026-10-01T08:00:00Z",
   last_login_at: null,
+  source: null,
+  external_id: null,
   ...more,
 });
 const ALICE = person("alice", { roles: ["deployers"], email: "alice@example.com" });
@@ -399,6 +401,27 @@ describe("one user", () => {
     await expectAccessible();
   });
 
+  test("says where they sign in: here, through a source, or through one that was deleted", async () => {
+    const { unmount } = one();
+    expect(await screen.findByText("Here, with a password of MegooArti's own")).toBeVisible();
+    unmount();
+
+    const gone = person("bea", { external_id: "uid=bea,ou=people", status: "disabled" });
+    one(gone);
+    expect(await screen.findByText("Through a source that was deleted")).toBeVisible();
+  });
+
+  test("of a source signs in with the source's password, which nobody sets here (E2)", async () => {
+    const carol = person("carol", { source: "Corp LDAP", external_id: "uid=carol,ou=people" });
+    one(carol);
+
+    expect(await screen.findByText("Corp LDAP")).toBeVisible();
+    expect(
+      screen.getByText("carol signs in through Corp LDAP, with the password they have there."),
+    ).toBeVisible();
+    expect(screen.queryByLabelText("New password")).toBeNull();
+  });
+
   test("is saved with what was changed, and the session is asked again (A10)", async () => {
     const user = userEvent.setup();
     const { calls } = one(ALICE, { "PATCH /users/id-of-alice": { json: ALICE } });
```

Change `frontend/src/lib/navigation.test.ts`:

```diff
@@ -82,10 +82,15 @@ describe("the navigation as it is", () => {
       ["users", "/admin/users"],
       ["roles", "/admin/roles"],
       ["anonymousAccess", "/admin/anonymous-access"],
+      ["authentication", "/admin/authentication"],
       ["manageRepositories", "/admin/repositories"],
       ["blobStores", "/admin/blob-stores"],
       ["system", "/admin/system"],
     ]);
+    // How people sign in is security's, not a setting's (spec 4.3).
+    expect(administration({ ...ADMIN, permissions: ["admin:security:read"] })).toEqual([
+      ["authentication", "/admin/authentication"],
+    ]);
     expect(administration({ ...ADMIN, permissions: ["admin:roles:read"] })).toEqual([
       ["roles", "/admin/roles"],
     ]);
```

Change `frontend/src/components/shell.test.tsx`:

```diff
@@ -76,6 +76,7 @@ describe("the shell", () => {
       ["Users", "/admin/users"],
       ["Roles", "/admin/roles"],
       ["Anonymous access", "/admin/anonymous-access"],
+      ["Authentication", "/admin/authentication"],
       // Not "Repositories": that is the list for browsing, in the same navigation (R14).
       ["Manage repositories", "/admin/repositories"],
       ["Blob stores", "/admin/blob-stores"],
@@ -89,6 +90,7 @@ describe("the shell", () => {
       null,
       null,
       null,
+      null,
     ]);
   });
 
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/screens/authentication.test.tsx src/screens/security.test.tsx src/lib/navigation.test.ts src/components/shell.test.tsx`
Expected: `authentication.test.tsx` does not load (`./authentication` is not there), and 4 failed: the navigation has no Authentication, and a user's page says nothing of where they sign in: 4 failed, 89 passed.

- [ ] **Step 3: Write the code**

First (in `frontend/`): `pnpm gen:api`, which writes `src/lib/api/schema.d.ts` from Task 3's `openapi.json`.

Change `frontend/src/lib/api/schema.d.ts`:

```diff
@@ -4,6 +4,96 @@
  */
 
 export interface paths {
+    "/api/v1/auth-sources": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /**
+         * List Sources
+         * @description The sources, in the order they are asked, after MegooArti's own users.
+         */
+        get: operations["list_sources_api_v1_auth_sources_get"];
+        put?: never;
+        /**
+         * Create Source
+         * @description A new source, asked after every other. Test it before it is enabled.
+         */
+        post: operations["create_source_api_v1_auth_sources_post"];
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/auth-sources/order": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        /**
+         * Order Sources
+         * @description Put the sources in the order they are to be asked: every one of them, once.
+         */
+        put: operations["order_sources_api_v1_auth_sources_order_put"];
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/auth-sources/{source_id}": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /** Get Source */
+        get: operations["get_source_api_v1_auth_sources__source_id__get"];
+        /**
+         * Update Source
+         * @description Change a source; its kind stays. Turned off, its users are refused until it is on.
+         */
+        put: operations["update_source_api_v1_auth_sources__source_id__put"];
+        post?: never;
+        /**
+         * Delete Source
+         * @description Delete a source. Its users are disabled, and kept with what they own.
+         */
+        delete: operations["delete_source_api_v1_auth_sources__source_id__delete"];
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/auth-sources/{source_id}/test": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        put?: never;
+        /**
+         * Test Source
+         * @description Whether the source answers, and, given a name and a password, who it says they are
+         *     and the roles they would be given. Nobody is signed in, or made, by it.
+         */
+        post: operations["test_source_api_v1_auth_sources__source_id__test_post"];
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/auth/login": {
         parameters: {
             query?: never;
@@ -58,6 +148,27 @@ export interface paths {
         patch?: never;
         trace?: never;
     };
+    "/api/v1/auth/sources": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /**
+         * Sign In Sources
+         * @description The enabled sources people sign in to in the browser, for the sign-in screen. Asked
+         *     before anyone is signed in, so it says no more than their names.
+         */
+        get: operations["sign_in_sources_api_v1_auth_sources_get"];
+        put?: never;
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/blob-stores": {
         parameters: {
             query?: never;
@@ -636,6 +747,64 @@ export interface paths {
         patch?: never;
         trace?: never;
     };
+    "/api/v1/settings/default-role": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        /**
+         * Set Default Role
+         * @description The role every signed-in user has, besides their own; null for none.
+         */
+        put: operations["set_default_role_api_v1_settings_default_role_put"];
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/settings/local-sign-in": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        /**
+         * Set Local Sign In
+         * @description Whether MegooArti's own users sign in. Off, the built-in `admin` still does (E1),
+         *     and must then hold full access: else nobody who signs in would.
+         */
+        put: operations["set_local_sign_in_api_v1_settings_local_sign_in_put"];
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/settings/sign-in": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /** Read Sign In Settings */
+        get: operations["read_sign_in_settings_api_v1_settings_sign_in_get"];
+        put?: never;
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/status/live": {
         parameters: {
             query?: never;
@@ -1021,6 +1190,11 @@ export interface components {
             /** Version */
             version: string;
         };
+        /** DefaultRole */
+        DefaultRole: {
+            /** Default Role */
+            default_role: string | null;
+        };
         /** Entry */
         Entry: {
             component?: components["schemas"]["ComponentRef"] | null;
@@ -1123,6 +1297,11 @@ export interface components {
             /** Next */
             next: string | null;
         };
+        /** LocalSignIn */
+        LocalSignIn: {
+            /** Enabled */
+            enabled: boolean;
+        };
         /** LoginRequest */
         LoginRequest: {
             /** Password */
@@ -1130,6 +1309,16 @@ export interface components {
             /** Username */
             username: string;
         };
+        /**
+         * Mapping
+         * @description The roles a member of a group is given (E4).
+         */
+        Mapping: {
+            /** Group */
+            group: string;
+            /** Roles */
+            roles: string[];
+        };
         /** NegativeCache */
         NegativeCache: {
             /**
@@ -1143,6 +1332,11 @@ export interface components {
              */
             ttl_minutes: number;
         };
+        /** Order */
+        Order: {
+            /** Ids */
+            ids: string[];
+        };
         /** Page[BlobStoreOut] */
         Page_BlobStoreOut_: {
             /** Items */
@@ -1231,6 +1425,28 @@ export interface components {
             /** Total */
             total: number;
         };
+        /** Page[SignInSource] */
+        Page_SignInSource_: {
+            /** Items */
+            items: components["schemas"]["SignInSource"][];
+            /** Limit */
+            limit: number;
+            /** Offset */
+            offset: number;
+            /** Total */
+            total: number;
+        };
+        /** Page[SourceOut] */
+        Page_SourceOut_: {
+            /** Items */
+            items: components["schemas"]["SourceOut"][];
+            /** Limit */
+            limit: number;
+            /** Offset */
+            offset: number;
+            /** Total */
+            total: number;
+        };
         /** Page[TokenInfo] */
         Page_TokenInfo_: {
             /** Items */
@@ -1581,6 +1797,31 @@ export interface components {
             /** Base Url */
             base_url: string | null;
         };
+        /**
+         * SignInSettings
+         * @description How people sign in, besides the sources (spec 4.1): the role every signed-in user
+         *     has, and whether MegooArti's own users sign in.
+         */
+        SignInSettings: {
+            /** Default Role */
+            default_role: string | null;
+            local_sign_in: components["schemas"]["LocalSignIn"];
+        };
+        /**
+         * SignInSource
+         * @description A source the sign-in screen sends people to, to sign in there (spec 4.3).
+         */
+        SignInSource: {
+            /**
+             * Id
+             * Format: uuid
+             */
+            id: string;
+            /** Kind */
+            kind: string;
+            /** Name */
+            name: string;
+        };
         /** SigningKeyGenerate */
         SigningKeyGenerate: {
             /** Algorithm */
@@ -1609,6 +1850,121 @@ export interface components {
             /** Readable */
             readable: boolean;
         };
+        /** SourceCreate */
+        SourceCreate: {
+            /**
+             * Enabled
+             * @default false
+             */
+            enabled: boolean;
+            /**
+             * Group Mapping
+             * @default []
+             */
+            group_mapping: components["schemas"]["Mapping"][];
+            /** Kind */
+            kind: string;
+            /** Name */
+            name: string;
+            /**
+             * Settings
+             * @default {}
+             */
+            settings: {
+                [key: string]: unknown;
+            };
+        };
+        /** SourceIn */
+        SourceIn: {
+            /**
+             * Enabled
+             * @default false
+             */
+            enabled: boolean;
+            /**
+             * Group Mapping
+             * @default []
+             */
+            group_mapping: components["schemas"]["Mapping"][];
+            /** Name */
+            name: string;
+            /**
+             * Settings
+             * @default {}
+             */
+            settings: {
+                [key: string]: unknown;
+            };
+        };
+        /** SourceOut */
+        SourceOut: {
+            /**
+             * Created At
+             * Format: date-time
+             */
+            created_at: string;
+            /** Enabled */
+            enabled: boolean;
+            /** Group Mapping */
+            group_mapping: components["schemas"]["Mapping"][];
+            /**
+             * Id
+             * Format: uuid
+             */
+            id: string;
+            /** Kind */
+            kind: string;
+            /** Name */
+            name: string;
+            /** Position */
+            position: number;
+            /** Secrets */
+            secrets: string[];
+            /** Settings */
+            settings: {
+                [key: string]: unknown;
+            };
+            /**
+             * Updated At
+             * Format: date-time
+             */
+            updated_at: string;
+            /** Users */
+            users: number;
+        };
+        /**
+         * TestIn
+         * @description A name and a password to try, or nothing: only whether the source answers.
+         */
+        TestIn: {
+            /** Password */
+            password?: string | null;
+            /** Username */
+            username?: string | null;
+        };
+        /** TestOut */
+        TestOut: {
+            /** Message */
+            message: string;
+            /** Ok */
+            ok: boolean;
+            user: components["schemas"]["TestedUser"] | null;
+        };
+        /** TestedUser */
+        TestedUser: {
+            /** Display Name */
+            display_name: string;
+            /** Email */
+            email: string | null;
+            /** External Id */
+            external_id: string;
+            /** Groups */
+            groups: string[];
+            /** Roles */
+            roles: string[];
+            /** Username */
+            username: string;
+        };
         /** TokenCreate */
         TokenCreate: {
             /** Expires At */
@@ -1716,6 +2072,8 @@ export interface components {
             display_name: string;
             /** Email */
             email: string | null;
+            /** External Id */
+            external_id: string | null;
             /**
              * Id
              * Format: uuid
@@ -1727,6 +2085,8 @@ export interface components {
             must_change_password: boolean;
             /** Roles */
             roles: string[];
+            /** Source */
+            source: string | null;
             /** Status */
             status: string;
             /** Username */
@@ -1766,18 +2126,17 @@ export interface components {
 }
 export type $defs = Record<string, never>;
 export interface operations {
-    login_api_v1_auth_login_post: {
+    list_sources_api_v1_auth_sources_get: {
         parameters: {
-            query?: never;
+            query?: {
+                limit?: number;
+                offset?: number;
+            };
             header?: never;
             path?: never;
             cookie?: never;
         };
-        requestBody: {
-            content: {
-                "application/json": components["schemas"]["LoginRequest"];
-            };
-        };
+        requestBody?: never;
         responses: {
             /** @description Successful Response */
             200: {
@@ -1785,7 +2144,7 @@ export interface operations {
                     [name: string]: unknown;
                 };
                 content: {
-                    "application/json": components["schemas"]["SessionInfo"];
+                    "application/json": components["schemas"]["Page_SourceOut_"];
                 };
             };
             /** @description Any error. */
@@ -1799,14 +2158,243 @@ export interface operations {
             };
         };
     };
-    logout_api_v1_auth_logout_post: {
+    create_source_api_v1_auth_sources_post: {
         parameters: {
             query?: never;
             header?: never;
             path?: never;
             cookie?: never;
         };
-        requestBody?: never;
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["SourceCreate"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            201: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SourceOut"];
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
+    order_sources_api_v1_auth_sources_order_put: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["Order"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Page_SourceOut_"];
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
+    get_source_api_v1_auth_sources__source_id__get: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                source_id: string;
+            };
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
+                    "application/json": components["schemas"]["SourceOut"];
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
+    update_source_api_v1_auth_sources__source_id__put: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                source_id: string;
+            };
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["SourceIn"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SourceOut"];
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
+    delete_source_api_v1_auth_sources__source_id__delete: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                source_id: string;
+            };
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            204: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content?: never;
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
+    test_source_api_v1_auth_sources__source_id__test_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                source_id: string;
+            };
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["TestIn"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["TestOut"];
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
+    login_api_v1_auth_login_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["LoginRequest"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SessionInfo"];
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
+    logout_api_v1_auth_logout_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
         responses: {
             /** @description Successful Response */
             204: {
@@ -1855,6 +2443,38 @@ export interface operations {
             };
         };
     };
+    sign_in_sources_api_v1_auth_sources_get: {
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
+                    "application/json": components["schemas"]["Page_SignInSource_"];
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
     list_blob_stores_api_v1_blob_stores_get: {
         parameters: {
             query?: {
@@ -3256,6 +3876,101 @@ export interface operations {
             };
         };
     };
+    set_default_role_api_v1_settings_default_role_put: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["DefaultRole"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SignInSettings"];
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
+    set_local_sign_in_api_v1_settings_local_sign_in_put: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["LocalSignIn"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SignInSettings"];
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
+    read_sign_in_settings_api_v1_settings_sign_in_get: {
+        parameters: {
+            query?: never;
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
+                    "application/json": components["schemas"]["SignInSettings"];
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
     live_api_v1_status_live_get: {
         parameters: {
             query?: never;
```

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -30,6 +30,13 @@ export type RoleOut = Schemas["RoleOut"];
 export type RoleCreate = Schemas["RoleCreate"];
 export type RoleContent = Schemas["RoleContent"];
 export type SettingsOut = Schemas["SettingsOut"];
+/** The default role, and whether MegooArti's own users sign in (spec 4.1). */
+export type SignInSettings = Schemas["SignInSettings"];
+/** A sign-in source as an administrator sees it: never its secrets. */
+export type SourceOut = Schemas["SourceOut"];
+export type SourceIn = Schemas["SourceIn"];
+/** What testing a source found. */
+export type SourceTested = Schemas["TestOut"];
 /** A repository as an administrator sees it: how it is set up, and a proxy's state. */
 export type RepositoryOut = Schemas["RepositoryOut"];
 export type RepositoryCreate = Schemas["RepositoryCreate"];
```

Change `frontend/src/lib/paths.ts`:

```diff
@@ -23,6 +23,7 @@ export const ROLES = "/admin/roles" as Route;
 // Where no role's name can be: a role may be called "new", and has `~` in no name.
 export const NEW_ROLE = "/admin/roles/~new" as Route;
 export const ANONYMOUS_ACCESS = "/admin/anonymous-access" as Route;
+export const AUTHENTICATION = "/admin/authentication" as Route;
 export const MANAGE_REPOSITORIES = "/admin/repositories" as Route;
 // As for a role: a repository may be called "new", and has `~` in no name.
 export const NEW_REPOSITORY = "/admin/repositories/~new" as Route;
```

Change `frontend/src/lib/navigation.ts`:

```diff
@@ -5,6 +5,7 @@
 import {
   Boxes,
   HardDrive,
+  KeyRound,
   Search,
   Server,
   ShieldCheck,
@@ -19,6 +20,7 @@ import type { Route } from "next";
 import type { SessionInfo } from "@/lib/api/types";
 import {
   ANONYMOUS_ACCESS,
+  AUTHENTICATION,
   BLOB_STORES,
   MANAGE_REPOSITORIES,
   ROLES,
@@ -35,6 +37,7 @@ export type ItemKey =
   | "users"
   | "roles"
   | "anonymousAccess"
+  | "authentication"
   | "manageRepositories"
   | "blobStores"
   | "system";
@@ -88,6 +91,12 @@ export const NAVIGATION: readonly NavArea[] = [
         icon: Unlock,
         permission: "admin:settings:read",
       },
+      {
+        key: "authentication",
+        href: AUTHENTICATION,
+        icon: KeyRound,
+        permission: "admin:security:read",
+      },
       {
         key: "manageRepositories",
         href: MANAGE_REPOSITORIES,
```

Change `frontend/src/lib/security.ts`:

```diff
@@ -19,6 +19,10 @@ import type {
   RoleCreate,
   RoleOut,
   SettingsOut,
+  SignInSettings,
+  SourceIn,
+  SourceOut,
+  SourceTested,
   TokenCreate,
   TokenCreated,
   TokenInfo,
@@ -38,6 +42,8 @@ const APPS = "connected-apps";
 const USERS = "users";
 const ROLES = "roles";
 const SETTINGS = "settings";
+const SIGN_IN = "sign-in";
+const SOURCES = "auth-sources";
 /** Where the settings are kept among what was fetched: whoever changes one puts the answer there. */
 export const SETTINGS_KEY = [SETTINGS] as const;
 
@@ -299,3 +305,88 @@ export function useSetAnonymousAccess() {
     onSuccess: (settings) => client.setQueryData([SETTINGS], settings),
   });
 }
+
+// --- How people sign in (spec 4) ------------------------------------------------------------
+
+const source = (id: string) => `/auth-sources/${encodeURIComponent(id)}`;
+
+export function useSignInSettings() {
+  return useQuery({
+    queryKey: [SIGN_IN],
+    queryFn: () => api.get<SignInSettings>("/settings/sign-in"),
+  });
+}
+
+/** What every signed-in user may do can change with it: the session is asked again. */
+export function useSetDefaultRole() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (role: string | null) =>
+      api.put<SignInSettings>("/settings/default-role", { default_role: role }),
+    onSuccess: (settings) => {
+      client.setQueryData([SIGN_IN], settings);
+      return client.invalidateQueries({ queryKey: SESSION_KEY });
+    },
+  });
+}
+
+/** Turned off, whoever is signed in as one of MegooArti's own users but `admin` is no longer. */
+export function useSetLocalSignIn() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (enabled: boolean) =>
+      api.put<SignInSettings>("/settings/local-sign-in", { enabled }),
+    onSuccess: (settings) => {
+      client.setQueryData([SIGN_IN], settings);
+      return client.invalidateQueries({ queryKey: SESSION_KEY });
+    },
+  });
+}
+
+/** Every source, in the order they are asked: there are few, and their order is the point. */
+export function useSources() {
+  return useQuery({
+    queryKey: [SOURCES],
+    queryFn: () => api.get<Page<SourceOut>>("/auth-sources", { query: { limit: EVERY } }),
+  });
+}
+
+export function useUpdateSource() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: ({ id, wanted }: { id: string; wanted: SourceIn }) =>
+      api.put<SourceOut>(source(id), wanted),
+    onSuccess: () => {
+      void client.invalidateQueries({ queryKey: [USERS] });
+      return client.invalidateQueries({ queryKey: [SOURCES] });
+    },
+  });
+}
+
+export function useOrderSources() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (ids: string[]) => api.put<Page<SourceOut>>("/auth-sources/order", { ids }),
+    onSuccess: (ordered) => client.setQueryData([SOURCES], ordered),
+  });
+}
+
+/** Its users are disabled, and kept: the users are asked for again. */
+export function useDeleteSource() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (id: string) => api.delete<void>(source(id)),
+    onSuccess: () => {
+      void client.invalidateQueries({ queryKey: [USERS] });
+      return client.invalidateQueries({ queryKey: [SOURCES] });
+    },
+  });
+}
+
+/** Whether a source answers. What it found is given to whoever asked, and kept nowhere. */
+export function useTestSource() {
+  return useMutation({
+    mutationFn: (id: string) => api.post<SourceTested>(`${source(id)}/test`, {}),
+    gcTime: 0,
+  });
+}
```

Change `frontend/messages/en.json`:

```diff
@@ -21,6 +21,7 @@
       "users": "Users",
       "roles": "Roles",
       "anonymousAccess": "Anonymous access",
+      "authentication": "Authentication",
       "manageRepositories": "Manage repositories",
       "blobStores": "Blob stores",
       "system": "System"
@@ -520,7 +521,8 @@
     },
     "facts": {
       "created": "Created",
-      "lastSignIn": "Last sign-in"
+      "lastSignIn": "Last sign-in",
+      "source": "Signs in"
     },
     "usernameRule": "A user name is 1 to 64 letters, digits or . _ @ -",
     "displayNameNeeded": "Give their name.",
@@ -563,7 +565,11 @@
     "appsTitle": "Connected apps",
     "appsOf": "Applications {username} connected",
     "noApps": "This user has connected no application.",
-    "appRevoked": "Revoked {name}, which {username} connected."
+    "appRevoked": "Revoked {name}, which {username} connected.",
+    "localUser": "Here, with a password of MegooArti's own",
+    "deletedSource": "Through a source that was deleted",
+    "externalPasswordTitle": "Password",
+    "externalPassword": "{username} signs in through {source}, with the password they have there."
   },
   "roles": {
     "title": "Roles",
@@ -632,6 +638,55 @@
     "onlyRepositories": "Whatever its roles say, a visitor is never allowed anything but what concerns repositories.",
     "userDisabled": "The anonymous user is disabled, so nothing is given without signing in, though the switch is on. Enable the user to let visitors in."
   },
+  "authentication": {
+    "title": "Authentication",
+    "intro": "Where people sign in from, in the order they are asked, and what every signed-in user may do.",
+    "sourcesTitle": "Sign-in sources",
+    "columns": {
+      "name": "Name",
+      "kind": "Kind",
+      "users": "Users",
+      "state": "State",
+      "actions": "Actions"
+    },
+    "local": "MegooArti's own users",
+    "localKind": "local",
+    "on": "On",
+    "off": "Off",
+    "noSources": "There is no other source yet: everybody signs in as one of MegooArti's own users.",
+    "order": "A user signs in where they belong. A name nobody has yet is asked of each source that is on, from the top, and the first that knows it decides. The built-in admin always signs in here.",
+    "turnOn": "Turn on",
+    "turnOff": "Turn off",
+    "turnOnNamed": "Turn on {name}",
+    "turnOffNamed": "Turn off {name}",
+    "turnedOn": "{name} is on.",
+    "turnedOff": "{name} is off: its users are refused until it is on again.",
+    "turnOnLocal": "Turn on",
+    "turnOffLocal": "Turn off",
+    "localTurnedOn": "MegooArti's own users sign in again.",
+    "localTurnedOff": "Only the built-in admin signs in as one of MegooArti's own users now.",
+    "askLocal": "Turn off MegooArti's own users?",
+    "askLocalBody": "Only the built-in admin will sign in with a password of MegooArti's own. Every other user of ours, you too unless you are admin, is signed out, and their API tokens are refused until this is on again.",
+    "moveUp": "Move {name} up",
+    "moveDown": "Move {name} down",
+    "moved": "Moved {name}.",
+    "test": "Test",
+    "testNamed": "Test {name}",
+    "tested": "Test",
+    "delete": "Delete",
+    "deleteNamed": "Delete {name}",
+    "deleteSource": "Delete source",
+    "deleteAsk": "Delete the sign-in source {name}?",
+    "deleteBody": "Nobody signs in through it any more. Its {users, plural, =0 {users, of whom there are none,} one {one user is} other {# users are}} disabled, and kept with what they own.",
+    "deleted": "Deleted the sign-in source {name}.",
+    "defaultRoleTitle": "Default role",
+    "defaultRoleIntro": "Every signed-in user has it, besides their own roles. It is given to nobody who is not signed in, and kept on no user.",
+    "defaultRole": "Default role",
+    "noDefaultRole": "None",
+    "save": "Save",
+    "defaultRoleSet": "Every signed-in user has the role {role}.",
+    "defaultRoleCleared": "There is no default role."
+  },
   "members": {
     "none": "It has no member yet, and so answers nothing.",
     "up": "Move {name} up",
```

Create `frontend/src/screens/authentication.tsx`:

```tsx
"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Alert, StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts } from "@/components/ui/details";
import { SelectField } from "@/components/ui/inputs";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import type { SourceOut } from "@/lib/api/types";
import {
  useDeleteSource,
  useEveryRole,
  useOrderSources,
  useSetDefaultRole,
  useSetLocalSignIn,
  useSignInSettings,
  useSources,
  useTestSource,
  useUpdateSource,
} from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

const H2 = "mb-3 text-lg font-semibold text-fg uppercase";
const NONE = "";

/** A source as it is sent back: what it has, with one thing changed. Its secrets stay. */
function asSent(source: SourceOut, changes: { enabled?: boolean } = {}) {
  return {
    name: source.name,
    enabled: changes.enabled ?? source.enabled,
    settings: source.settings,
    group_mapping: source.group_mapping,
  };
}

function OnOff({ on }: { on: boolean }) {
  const t = useTranslations("authentication");
  return <StatusTag tone={on ? "success" : "info"}>{on ? t("on") : t("off")}</StatusTag>;
}

/** MegooArti's own users and the sources, in the order a password is asked of them (E3). */
function Sources({ mayWrite }: { mayWrite: boolean }) {
  const t = useTranslations("authentication");
  const notify = useNotify();
  const settings = useSignInSettings();
  const sources = useSources();
  const local = useSetLocalSignIn();
  const update = useUpdateSource();
  const order = useOrderSources();
  const remove = useDeleteSource();
  const test = useTestSource();
  const [askingLocal, setAskingLocal] = useState(false);
  const [deleting, setDeleting] = useState<SourceOut | null>(null);
  const [tested, setTested] = useState<string | null>(null);

  const failed = settings.isError ? settings : sources.isError ? sources : null;
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  if (!settings.data || !sources.data) return <LoadingState className="p-4" />;

  const localOn = settings.data.local_sign_in.enabled;
  const listed = sources.data.items;
  const setLocal = (enabled: boolean) =>
    local.mutate(enabled, {
      onSuccess: () => notify(enabled ? t("localTurnedOn") : t("localTurnedOff")),
      onSettled: () => setAskingLocal(false),
    });
  const move = (index: number, by: -1 | 1) => {
    const ids = listed.map((source) => source.id);
    const [moved] = ids.splice(index, 1);
    if (moved === undefined) return;
    ids.splice(index + by, 0, moved);
    order.mutate(ids, { onSuccess: () => notify(t("moved", { name: listed[index]?.name ?? "" })) });
  };
  const turn = (source: SourceOut, enabled: boolean) =>
    update.mutate(
      { id: source.id, wanted: asSent(source, { enabled }) },
      {
        onSuccess: () =>
          notify(
            enabled ? t("turnedOn", { name: source.name }) : t("turnedOff", { name: source.name }),
          ),
      },
    );
  const failure = [local, update, order, remove].find((mutation) => mutation.isError);
  const shownTest = tested !== null && test.data && test.variables === tested ? test.data : null;

  return (
    <>
      <Table caption={t("sourcesTitle")}>
        <thead>
          <tr>
            <Th>{t("columns.name")}</Th>
            <Th>{t("columns.kind")}</Th>
            <Th className="text-right">{t("columns.users")}</Th>
            <Th>{t("columns.state")}</Th>
            {mayWrite ? <Th className="text-right">{t("columns.actions")}</Th> : null}
          </tr>
        </thead>
        <tbody>
          <tr>
            <Td className="font-medium">{t("local")}</Td>
            <Td className="text-fg-muted">{t("localKind")}</Td>
            <Td />
            <Td>
              <OnOff on={localOn} />
            </Td>
            {mayWrite ? (
              <Td className="text-right">
                <Button
                  size="sm"
                  busy={local.isPending && !askingLocal}
                  onClick={() => (localOn ? setAskingLocal(true) : setLocal(true))}
                >
                  {localOn ? t("turnOffLocal") : t("turnOnLocal")}
                </Button>
              </Td>
            ) : null}
          </tr>
          {listed.map((source, index) => (
            <tr key={source.id} className="hover:bg-raised">
              <Td className="font-medium break-all">{source.name}</Td>
              <Td className="font-mono text-fg-muted">{source.kind}</Td>
              <Td className="text-right font-mono">{source.users}</Td>
              <Td>
                <OnOff on={source.enabled} />
              </Td>
              {mayWrite ? (
                <Td className="text-right">
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button
                      size="sm"
                      aria-label={t("moveUp", { name: source.name })}
                      disabled={index === 0 || order.isPending}
                      onClick={() => move(index, -1)}
                    >
                      <ArrowUp aria-hidden="true" className="size-4" />
                    </Button>
                    <Button
                      size="sm"
                      aria-label={t("moveDown", { name: source.name })}
                      disabled={index === listed.length - 1 || order.isPending}
                      onClick={() => move(index, 1)}
                    >
                      <ArrowDown aria-hidden="true" className="size-4" />
                    </Button>
                    <Button
                      size="sm"
                      aria-label={t("testNamed", { name: source.name })}
                      busy={test.isPending && test.variables === source.id}
                      onClick={() => {
                        setTested(source.id);
                        test.mutate(source.id);
                      }}
                    >
                      {t("test")}
                    </Button>
                    <Button
                      size="sm"
                      aria-label={
                        source.enabled
                          ? t("turnOffNamed", { name: source.name })
                          : t("turnOnNamed", { name: source.name })
                      }
                      onClick={() => turn(source, !source.enabled)}
                    >
                      {source.enabled ? t("turnOff") : t("turnOn")}
                    </Button>
                    <Button
                      size="sm"
                      aria-label={t("deleteNamed", { name: source.name })}
                      onClick={() => {
                        remove.reset();
                        setDeleting(source);
                      }}
                    >
                      {t("delete")}
                    </Button>
                  </div>
                </Td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="flex flex-col gap-3 p-4">
        {listed.length === 0 ? <p className="text-fg-muted">{t("noSources")}</p> : null}
        <p className="text-sm text-fg-subtle">{t("order")}</p>
        {shownTest ? (
          <Alert tone={shownTest.ok ? "success" : "danger"} title={t("tested")}>
            {shownTest.message}
          </Alert>
        ) : null}
        {test.isError ? <ErrorState error={test.error} /> : null}
        {failure ? <ErrorState error={failure.error} /> : null}
      </div>
      <ConfirmDialog
        open={askingLocal}
        onOpenChange={setAskingLocal}
        title={t("askLocal")}
        confirmLabel={t("turnOffLocal")}
        busy={local.isPending}
        onConfirm={() => setLocal(false)}
      >
        {t("askLocalBody")}
      </ConfirmDialog>
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("deleteAsk", { name: deleting?.name ?? "" })}
        confirmLabel={t("deleteSource")}
        mustType={deleting?.name}
        busy={remove.isPending}
        onConfirm={() => {
          if (deleting === null) return;
          remove.mutate(deleting.id, {
            onSuccess: () => notify(t("deleted", { name: deleting.name })),
            onSettled: () => setDeleting(null),
          });
        }}
      >
        {t("deleteBody", { users: deleting?.users ?? 0 })}
      </ConfirmDialog>
    </>
  );
}

/** The role every signed-in user has besides their own (spec 4.1). */
function DefaultRole({ mayWrite }: { mayWrite: boolean }) {
  const t = useTranslations("authentication");
  const notify = useNotify();
  const session = useSession();
  const settings = useSignInSettings();
  const mayChoose =
    mayWrite && session.data !== undefined && allows(session.data, "admin:roles:read");
  const roles = useEveryRole(mayChoose);
  const change = useSetDefaultRole();
  const [chosen, setChosen] = useState<string | null>(null);

  if (settings.isError) {
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  }
  if (!settings.data) return <LoadingState className="p-4" />;
  const current = settings.data.default_role;
  if (!mayChoose) {
    return (
      <Facts>
        <Fact name={t("defaultRole")} mono>
          {current ?? t("noDefaultRole")}
        </Fact>
      </Facts>
    );
  }
  if (roles.isError) return <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />;
  if (!roles.data) return <LoadingState className="p-4" />;

  const value = chosen ?? current ?? NONE;
  function submit(event: FormEvent) {
    event.preventDefault();
    const role = value === NONE ? null : value;
    change.mutate(role, {
      onSuccess: () =>
        notify(role === null ? t("defaultRoleCleared") : t("defaultRoleSet", { role })),
    });
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <SelectField
        label={t("defaultRole")}
        value={value}
        onChange={(event) => setChosen(event.target.value)}
        choices={[
          { value: NONE, label: t("noDefaultRole") },
          ...roles.data.items.map((role) => ({ value: role.name, label: role.name })),
        ]}
      />
      {change.isError ? <ErrorState error={change.error} /> : null}
      <div>
        <Button type="submit" variant="primary" busy={change.isPending}>
          {t("save")}
        </Button>
      </div>
    </form>
  );
}

/** Where people sign in from, in order, and the role every signed-in user has (SEC-15, SEC-16). */
export function AuthenticationScreen() {
  const t = useTranslations("authentication");
  const session = useSession();
  const mayWrite = session.data !== undefined && allows(session.data, "admin:security:write");
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel>
        <h2 className={`${H2} px-4 pt-4`}>{t("sourcesTitle")}</h2>
        <Sources mayWrite={mayWrite} />
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("defaultRoleTitle")}</h2>
        <p className="mb-4 text-fg-muted">{t("defaultRoleIntro")}</p>
        <DefaultRole mayWrite={mayWrite} />
      </Panel>
    </div>
  );
}
```

Create `frontend/src/app/(shell)/admin/authentication/page.tsx`:

```tsx
import type { Metadata } from "next";

import { AuthenticationScreen } from "@/screens/authentication";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.authentication.title };

export default function Page() {
  return <AuthenticationScreen />;
}
```

Change `frontend/src/screens/user.tsx`:

```diff
@@ -348,6 +348,9 @@ function Details({
         <Fact name={t("facts.lastSignIn")}>
           <Time value={user.last_login_at} />
         </Fact>
+        <Fact name={t("facts.source")}>
+          {user.source ?? (user.external_id === null ? t("localUser") : t("deletedSource"))}
+        </Fact>
       </Facts>
       <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
         <fieldset disabled={!mayWrite} className="flex min-w-0 flex-col gap-5 border-0 p-0">
@@ -614,7 +617,15 @@ export function UserScreen() {
         {found.builtin ? <Alert tone="info">{t("builtinNote")}</Alert> : null}
       </div>
       <Details user={found} mayWrite={mayWrite} isSelf={isSelf} />
-      {!mayWrite || isAnonymous ? null : isSelf ? (
+      {!mayWrite || isAnonymous ? null : found.source !== null ? (
+        // Theirs is the source's, which no one sets here (E2).
+        <Panel className="p-6">
+          <h2 className={H2}>{t("externalPasswordTitle")}</h2>
+          <p className="text-fg-muted">
+            {t("externalPassword", { username: found.username, source: found.source })}
+          </p>
+        </Panel>
+      ) : isSelf ? (
         // Set here, with "must choose a new one", it would end this page and ask for the
         // password that was on it: an administrator could lock themselves out.
         <Panel className="p-6">
```

Change `docs/web-ui.md`:

```diff
@@ -53,7 +53,8 @@ repositories, blob stores and the installation's own settings.
     sets a new password, lists and revokes their API tokens, and deletes them after
     you type their name. Your own account cannot be disabled or deleted there, and
     your own password is changed under your account, where you are asked for the one
-    you have. A built-in user cannot be deleted.
+    you have. A built-in user cannot be deleted. A user's page says where they sign
+    in: here, or through a sign-in source, whose users have no password here.
   - **Roles.** A role's permissions are rows: choose what a row is about (a
     repository, or an area of administration), then the format, repository and
     action from lists. The pattern the row makes is shown with what it grants in
@@ -63,6 +64,12 @@ repositories, blob stores and the installation's own settings.
   - **Anonymous access** is one switch, which asks before it is turned on, and shows
     what someone who is not signed in may then do. If the `anonymous` user is
     disabled, nothing is given though the switch is on, and the page says so.
+  - **Authentication** lists where people sign in from, in the order they are
+    asked: MegooArti's own users first, then each sign-in source, with how many
+    users it has. A source is turned on or off, moved up or down, tested, and deleted
+    after you type its name. Turning MegooArti's own users off asks first: only the
+    built-in `admin` signs in here then. The default role, which every signed-in
+    user has, is chosen from the roles.
   - **Manage repositories** lists every repository as it is set up. A new one is made
     on one page: choose the format and the type, and the page shows what that
     combination has. A hosted repository has a deployment policy; a proxy has its
```

Change `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`:

```diff
@@ -77,6 +77,26 @@ Settled here, by the designer:
 - REST: `GET/POST /api/v1/auth-sources`, `GET/PUT/DELETE /api/v1/auth-sources/{id}`, `PUT /api/v1/auth-sources/order`, `POST /api/v1/auth-sources/{id}/test`; `PUT /api/v1/settings/default-role`. Permissions: `admin:security:read`, `admin:security:write` (a new area).
 - `GET /api/v1/auth/sources` (no sign-in needed): the enabled OIDC sources' ids and names, for the sign-in screen.
 
+### Settled while building plan 15a
+
+| # | What | Why |
+| --- | --- | --- |
+| S1 | Whether MegooArti's own users sign in is a setting, `local_sign_in` (on unless set), beside `default_role`. Both are read at `GET /api/v1/settings/sign-in` and changed at `PUT /api/v1/settings/local-sign-in` and `PUT /api/v1/settings/default-role`, under `admin:security`; `GET /api/v1/settings` is unchanged. | 4.1 makes the local source no row. Whoever keeps sign-in may not be given the base URL with it, nor need it. |
+| S2 | While it is off, a user of ours other than the built-in `admin` is refused as a disabled user is: sign-in, session, Basic, API tokens, OAuth. It is turned off only while `admin` is active, has a password and holds full access (`409 last_administrator`); the check of who remains counts `admin` alone then. | E1, and 4.2's "refused as a disabled user is". Nobody can lock everyone out. |
+| S3 | A user's source is `users.source_id` (the spec's `source`), with `external_id`; one user per `(source_id, external_id)`. Deleting a source disables its users and ends their sessions before the key is set null; their `external_id` stays, so they are a deleted source's users, not ours, and have no password. | 4.1, 4.3. A user of a deleted source must not become one of ours by the key's going. |
+| S4 | A kind of source is a `sources.Kind` (`checked`, `password`, `test`, its `secrets`, `in_browser`, `takes_passwords`) registered in `sources.KINDS`. This plan registers none: a source can be made once 15b or 15d brings its kind, and until then `kind` is refused with what there is. The tests register kinds of their own. | Section 13: LDAP and OIDC are their own plans; what they share is here. |
+| S5 | A source answers a name and a password with who they are, `unknown` (the next source is asked) or `refused` (nobody else is). A user of a source is asked of their own source alone, with their identity there, and is refused if it says another. | E3: the first that knows the name decides; a wrong password is not tried against every directory. |
+| S6 | A user's name is what the source says, in lower case, a character a name may not hold made `-`. Where another user has it: `name@source` (the source's name made so too), then `-2`, `-3`. `__token__` and names shaped as a token are never given. The name is brought up to date at each sign-in, as the rest is. | 4.2, and names that the users' API and HTTP Basic take. |
+| S7 | Groups are matched whatever their case. A mapped role that does not exist gives nothing; the mapping's roles are checked when it is saved (`422`). | Directories differ in case; section 11. |
+| S8 | Each held role records who gave it (`granted_by`: `admin` or `source`). Roles an administrator sets on a user keep a source's role the source's, so the groups still decide it at the next sign-in. | E4. |
+| S9 | The default role is added to the permissions of every signed-in principal (session, password, token, OAuth), not to a visitor's. Deleting the role clears the setting. | 4.1. A setting that names nothing would say what no one has. |
+| S10 | A user of a source has no password here: setting one is refused, by an administrator or by them, with `409 external_user`. | E2. |
+| S11 | `POST /api/v1/auth-sources/{id}/test` takes a name and a password, or nothing, needs `admin:security:write` (it reaches out), and says whether the source answered, who it says they are and the roles the mapping would give. Nobody is made or signed in by it. | 4.3, 14: a source is tested before it is enabled. |
+| S12 | `GET /api/v1/auth/sources` lists the enabled sources of a kind signed in to in the browser, by id, name and kind only, paged. | 4.3. It is open: the sign-in screen asks it before anyone signs in. |
+| S13 | A source's name is 1 to 64 letters, digits, spaces, `.`, `_` and `-`, beginning with a letter or a digit; not `local`; unique whatever its case. A source is made off, and last. `PUT` replaces all but its kind; a secret left out keeps the stored one. | Shown on the sign-in screen and in `name@source`; 14's "tested before it is enabled"; E5. |
+| S14 | A source that cannot be asked answers `503 source_unavailable`, naming it, and is not counted as a failed sign-in. | Section 11. A directory that is down must not lock its users out for 15 minutes. |
+| S15 | The Authentication screen lists the sources, turns them on and off, moves, tests and deletes them; the form that makes or edits one comes with its kind, in 15b (OIDC) and 15d (LDAP), whose settings it shows. | A source's settings are its kind's; this plan has no kind to show. |
+
 ## 5. OIDC (plan 15b)
 
 - Settings: issuer, client id, client secret (sealed), scopes (`openid profile email` and any more), the claims of the user name (`preferred_username`), the display name (`name`), the email (`email`) and the groups (`groups`), and whether a user must have a verified email.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/screens/authentication.test.tsx src/screens/security.test.tsx src/lib/navigation.test.ts src/components/shell.test.tsx && pnpm lint && pnpm typecheck`; then (in `backend/`) `uv run pytest -q tests/test_documents.py`
Expected: 105 passed; `All matched files use Prettier code style!`; the types check; then 147 passed.

- [ ] **Step 5: Run every test**

Run (in `backend/`): `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`; then (in `frontend/`): `pnpm vitest run`
Expected: `428 files already formatted`, `All checks passed!`, 4119 passed, 2 skipped, 112 deselected; then 883 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend docs
git commit -m "feat(ui): the Authentication screen: sign-in sources in order, our own users, the default role; where a user signs in; what plan 15a settled"
```
