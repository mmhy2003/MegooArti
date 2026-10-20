"""Who may do what to a repository's content (spec 10, E6): the one place that decides.

A caller reaches a repository's content for an action by a repository permission
(`repository:<format>:<repository>:<action>`), which is every path of it; or by
selector permissions (`selector:<selector>:<format>:<repository>:<action>`), each the
paths its selector's expression matches. `may` asks for one path; `reach` says it all,
for listing what a caller may see: whether the whole, which paths, which folders, and
what a database can be asked to leave out first.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, or_

from megooarti.errors import ApiError
from megooarti.repositories.models import Repository
from megooarti.security.authentication import (
    Principal,
    Scheme,
    refuse_pending_password_change,
    unauthorized,
)
from megooarti.security.selectors import Expression, Reach, SelectorError, parse


def slashed(path: str) -> str:
    """A path as an expression sees it: from `/`."""
    return path if path.startswith("/") else f"/{path}"


@dataclass(frozen=True)
class Reached:
    """What of one repository a caller reaches for one action."""

    format: str
    whole: bool  # by a repository permission: every path
    expressions: Sequence[Expression]  # else, the paths any of these match

    @property
    def anything(self) -> bool:
        """Whether the caller reaches any of it: what a repository is listed by."""
        return self.whole or any(
            expression.under(self.format, "/") is not Reach.NONE for expression in self.expressions
        )

    def allows(self, path: str) -> bool:
        path = slashed(path)
        return self.whole or any(e.matches(self.format, path) for e in self.expressions)

    def folder(self, folder: str) -> bool:
        """Whether a folder may hold anything reached: what a folder is listed by."""
        if self.whole:
            return True
        folder = slashed(folder.rstrip("/") + "/")
        return any(e.under(self.format, folder) is not Reach.NONE for e in self.expressions)

    def narrowing(self, path: ColumnElement[str]) -> tuple[ColumnElement[bool] | None, bool]:
        """A condition on a path (from `/`) every reached path meets, None for the whole;
        and whether it is exact. What an inexact one keeps is still to be checked by
        `allows`: a pattern's matches cannot be asked of a database."""
        if self.whole:
            return None, True
        said = [e.narrowing(self.format, path) for e in self.expressions]
        return or_(*(condition for condition, _ in said)), all(exact for _, exact in said)


def reach(principal: Principal | None, repository: Repository, action: str) -> Reached:
    """What of a repository a caller reaches for an action."""
    if principal is None:
        return Reached(repository.format, False, ())
    named = f"{repository.format}:{repository.name}:{action}"
    if principal.allows(f"repository:{named}"):
        return Reached(repository.format, True, ())
    found = []
    for selector, text in sorted(principal.selectors.items()):
        if not principal.allows(f"selector:{selector}:{named}"):
            continue
        try:
            found.append(parse(text))
        except SelectorError:
            continue  # kept before it was checked as it is now: it reaches nothing
    return Reached(repository.format, False, tuple(found))


def may(principal: Principal | None, repository: Repository, path: str, action: str) -> bool:
    """Whether a caller may do this to what is at this path of a repository (E6)."""
    return reach(principal, repository, action).allows(path)


def may_somewhere(principal: Principal | None, repository: Repository, action: str) -> bool:
    """Whether a caller may do this to some of a repository: it is listed to them so."""
    return reach(principal, repository, action).anything


def _refuse(principal: Principal | None, scheme: Scheme) -> None:
    if principal is None or principal.is_anonymous:
        raise unauthorized(scheme=scheme)
    raise ApiError(403, "forbidden", "You do not have permission to do this.")


def require(
    principal: Principal | None,
    repository: Repository,
    path: str,
    action: str,
    *,
    scheme: Scheme = "Basic",
) -> Principal:
    """The caller, if they may do this at this path; else 401 (nobody, or anonymous) or
    403, as `authorize` answers."""
    if principal is not None:
        refuse_pending_password_change(principal)
    if not may(principal, repository, path, action):
        _refuse(principal, scheme)
    assert principal is not None
    return principal


def require_somewhere(
    principal: Principal | None, repository: Repository, action: str, *, scheme: Scheme = "Basic"
) -> Principal:
    """The caller, if they may do this to some of the repository; else 401 or 403. For a
    request whose paths are known only as it is served: each is checked then too."""
    if principal is not None:
        refuse_pending_password_change(principal)
    if not may_somewhere(principal, repository, action):
        _refuse(principal, scheme)
    assert principal is not None
    return principal
