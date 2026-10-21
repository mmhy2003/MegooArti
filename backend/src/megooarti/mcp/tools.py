"""What every tool shares: who is calling, a database session, how a refusal is said to
the agent, and the record of each call (spec 5, 8.1 and 8.4)."""

import functools
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from megooarti.errors import ApiError
from megooarti.security.authentication import Principal

log = structlog.get_logger(__name__)

# What a tool says of itself (E3). One that only reads changes nothing, and asks nothing
# of the world outside this server.
READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
# One that makes something: made again, it is refused, or there are two.
WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
# One that changes something to what it is given: given it again, nothing more changes.
CHANGE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
# One that deletes, or takes away: a client asks the person first.
DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
)


@dataclass(frozen=True)
class Caller:
    """Who called `/mcp`, and the request they called it with."""

    principal: Principal
    request: Request


# Set by the endpoint for each request. The SDK carries it on to the tool it calls.
_caller: ContextVar[Caller] = ContextVar("megooarti_mcp_caller")


def enter(caller: Caller) -> None:
    _caller.set(caller)


def caller() -> Caller:
    try:
        return _caller.get()
    except LookupError:
        raise ToolError("unauthorized: Authentication is required.") from None


@asynccontextmanager
async def database() -> AsyncIterator[AsyncSession]:
    """A session for one tool call. It does not commit: a tool that changes data does."""
    async with caller().request.app.state.sessionmaker() as session:
        yield session


def anyone(principal: Principal) -> bool:
    return True


def holding(permission: str) -> Callable[[Principal], bool]:
    """Shown to whoever holds `permission`, as the REST route it stands beside requires."""
    return lambda principal: principal.allows(permission)


def _could(pattern: str, action: str) -> bool:
    """Whether a pattern grants `action` on the content of some repository: by a
    repository permission, or by a selector permission (spec 10)."""
    # None: whatever its format and its name, and whichever selector.
    shapes = (("repository", None, None, action), ("selector", None, None, None, action))
    return any(
        all(
            part == "*" or want is None or part == want
            for part, want in zip(pattern.split(":"), wanted, strict=False)
        )
        for wanted in shapes
    )


def may_somewhere(action: str) -> Callable[[Principal], bool]:
    """Shown to whoever may do `action` to the content of some repository: by their
    permissions, narrowed by their token's scopes, or by what is public."""

    def shown(principal: Principal) -> bool:
        if any(_could(pattern, action) for pattern in principal.public):
            return True
        if principal.is_anonymous or not any(_could(p, action) for p in principal.patterns):
            return False
        return principal.scopes is None or any(_could(s, action) for s in principal.scopes)

    return shown


@dataclass(frozen=True)
class Tool:
    function: Callable[..., Awaitable[Any]]
    name: str
    annotations: ToolAnnotations
    # Whether a caller is shown the tool, and may call it (E1).
    shown_to: Callable[[Principal], bool]


# Every tool, as the modules that define them register them on import.
TOOLS: list[Tool] = []


def refused(error: ValidationError) -> ApiError:
    """What the tool was given, refused as the REST API refuses a body it cannot take."""
    details = [
        {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
        for item in error.errors()
    ]
    return ApiError(422, "validation_error", "The request is not valid.", details)


# What a tool is given that is a credential: never written to the log (8.4).
_SECRETS = frozenset({"password", "secret"})


def loggable(value: Any) -> Any:
    """What a tool was given, as the log may keep it: a password or a secret in it, at
    any depth, written `[redacted]`."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key in _SECRETS and item is not None else loggable(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [loggable(item) for item in value]
    return value


def said(error: ApiError) -> str:
    """A REST error as an agent reads it: its code, its message, and each field's."""
    lines = [f"{error.code}: {error.message}"]
    lines += [f"- {detail.get('field')}: {detail.get('message')}" for detail in error.details]
    return "\n".join(lines)


def tool(
    *,
    annotations: ToolAnnotations = READ,
    shown_to: Callable[[Principal], bool] = anyone,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Register a tool. Its name is the function's, and its description the docstring:
    what the agent reads to choose it."""

    def register(function: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(function)
        async def called(**arguments: Any) -> Any:
            started = time.perf_counter()
            outcome = "ok"
            try:
                return await function(**arguments)
            except ApiError as error:
                outcome = error.code
                raise ToolError(said(error)) from None
            except ValidationError as error:
                outcome = "validation_error"
                raise ToolError(said(refused(error))) from None
            except ToolError:
                outcome = "refused"
                raise
            except Exception:
                outcome = "internal_error"
                log.exception("mcp_tool_failed", tool=function.__name__)
                raise ToolError(
                    "internal_error: Something went wrong. It has been logged."
                ) from None
            finally:
                principal = caller().principal
                log.info(
                    "mcp_tool_called",
                    tool=function.__name__,
                    user=principal.user.username,
                    token=str(principal.token_id or principal.grant_id or "") or None,
                    arguments=loggable(arguments),
                    outcome=outcome,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )

        TOOLS.append(Tool(called, function.__name__, annotations, shown_to))
        return function

    return register
