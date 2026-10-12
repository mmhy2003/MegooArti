"""The name of something that has an address: a repository, a role, a blob store."""

from typing import Annotated

from pydantic import AfterValidator, Field

# The same characters as a permission segment, so a name can never shift a permission.
NAME_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"


def _not_a_folder(name: str) -> str:
    # A browser, a proxy and most clients take these for folders, however they are
    # written: what is so named cannot be reached at its own address.
    if name in (".", ".."):
        raise ValueError("must not be . or ..")
    return name


# For what is being made. What is already there, and so named, is still found.
NewName = Annotated[str, Field(pattern=NAME_PATTERN), AfterValidator(_not_a_folder)]
