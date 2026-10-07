"""The paging convention every list endpoint uses."""

from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel


class PageParams:
    """Use as `params: PageParams = Depends()`."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def page(items: list[Any], total: int, params: PageParams) -> dict[str, Any]:
    """The body of a list response. Declare `response_model=Page[...]` on the route."""
    return {"items": items, "total": total, "limit": params.limit, "offset": params.offset}
