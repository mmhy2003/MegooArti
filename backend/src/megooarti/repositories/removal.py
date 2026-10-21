"""Deleting a stored file as its format would: what the content API and the cleanup run
both do (cleanup spec 5.3)."""

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext


async def delete_file(context: RepositoryContext, path: str) -> bool:
    """Delete one stored file as its format would. False if there is none."""
    if context.repository.type == "proxy":
        # Only ever a cached copy. It is fetched again when it is next asked for.
        return await context.delete(path)
    if context.format is None:
        raise ApiError(
            503, "repository_unavailable", "This version cannot serve this kind of repository."
        )
    return await context.format.delete_asset(context, path)
