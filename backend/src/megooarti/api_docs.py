"""The API's documentation page, served with its own script and stylesheet.

FastAPI's own page loads Swagger UI from a public CDN: an installation without the
internet then has no page, and one with it runs a third party's script on its own
origin. The files are kept in `static/swagger-ui`, with their licence and the version
they are. They are those of the npm package `swagger-ui-dist`, unchanged: to replace
them, unpack another version of it (`npm pack swagger-ui-dist@<version>`), copy the
same six files, and write the version to `VERSION`.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse

from megooarti.errors import ApiError

DOCS_PATH = "/api/docs"
ASSETS = Path(__file__).parent / "static" / "swagger-ui"
# What the page loads, by the name it asks for. Nothing else in the folder is served.
_SERVED = {
    "swagger-ui-bundle.js": "text/javascript",
    "swagger-ui.css": "text/css",
    "favicon-32x32.png": "image/png",
}


def docs_router(openapi_url: str, title: str) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get(DOCS_PATH, response_class=HTMLResponse)
    async def docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=openapi_url,
            title=title,
            swagger_js_url=f"{DOCS_PATH}/assets/swagger-ui-bundle.js",
            swagger_css_url=f"{DOCS_PATH}/assets/swagger-ui.css",
            swagger_favicon_url=f"{DOCS_PATH}/assets/favicon-32x32.png",
            oauth2_redirect_url=None,
            # Swagger UI asks swagger.io to validate the document of a server that is
            # not on localhost, unless it is told not to.
            swagger_ui_parameters={"validatorUrl": None},
        )

    @router.get(f"{DOCS_PATH}/assets/{{name}}")
    async def asset(name: str) -> FileResponse:
        media_type = _SERVED.get(name)
        if media_type is None:
            raise ApiError(404, "not_found", "No such file.")
        return FileResponse(ASSETS / name, media_type=media_type)

    return router
