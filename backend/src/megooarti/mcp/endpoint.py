"""`/mcp`: the MCP endpoint (spec 4), over Streamable HTTP without sessions."""

from fastapi import APIRouter, Depends, Request
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from megooarti.mcp.server import Server
from megooarti.mcp.tools import Caller, enter
from megooarti.security.authentication import Principal, agent_principal

router = APIRouter()

# A request is signed in with a bearer token, which a browser never attaches by itself:
# the SDK's check of the Host header, against a site that rebinds a name to this
# server, guards nothing here, and would refuse every name the server is reached by.
_ANY_HOST = TransportSecuritySettings(enable_dns_rebinding_protection=False)


class _Answered(Response):
    """A request handed to the MCP server, which writes the response itself."""

    def __init__(self, server: Server) -> None:
        self.server = server
        self.background = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Nothing is kept between requests, so nothing outlives one: a session manager
        # of its own runs it, and stops with it.
        manager = StreamableHTTPSessionManager(
            app=self.server.lowlevel,
            stateless=True,
            json_response=True,
            security_settings=_ANY_HOST,
        )
        async with manager.run():
            await manager.handle_request(scope, receive, send)


@router.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def mcp(request: Request, principal: Principal = Depends(agent_principal)) -> Response:
    """The MCP endpoint. Signed in with an API token only (spec 5)."""
    enter(Caller(principal, request))
    return _Answered(request.app.state.mcp)
