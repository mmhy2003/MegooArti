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
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from megooarti.errors import ApiError
from megooarti.security.authentication import Principal

log = structlog.get_logger(__name__)

# What a tool that only reads says of itself (E3): it changes nothing, and asks nothing
# of the world outside this server.
READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
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


@dataclass(frozen=True)
class Tool:
    function: Callable[..., Awaitable[Any]]
    name: str
    annotations: ToolAnnotations
    # Whether a caller is shown the tool, and may call it (E1).
    shown_to: Callable[[Principal], bool]


# Every tool, as the modules that define them register them on import.
TOOLS: list[Tool] = []


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
                    token=None if principal.token_id is None else str(principal.token_id),
                    arguments=arguments,
                    outcome=outcome,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )

        TOOLS.append(Tool(called, function.__name__, annotations, shown_to))
        return function

    return register
