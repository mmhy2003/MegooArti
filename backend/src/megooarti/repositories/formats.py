"""The interface every package format implements, and the registry of formats.

The base class is complete, generic, path-addressed behaviour. A format subclasses it,
sets `name`, and overrides only what differs. Formats never touch tables or files:
they work through the repository context they are handed.
"""

from dataclasses import dataclass
from typing import Any

from megooarti.errors import ApiError


@dataclass(frozen=True)
class ComponentKey:
    """What identifies a component (a package) inside a repository."""

    namespace: str
    name: str
    version: str = ""


class Format:
    name: str = ""
    types: frozenset[str] = frozenset({"hosted", "proxy", "group"})

    def validate_config(self, repository_type: str, config: dict[str, Any]) -> dict[str, Any]:
        """Check and return this format's own settings. The generic format has none."""
        if config:
            details = [
                {"field": "format_config", "message": f"The {self.name} format has no settings."}
            ]
            raise ApiError(422, "validation_error", "The request is not valid.", details)
        return {}

    def describe_component(self, path: str) -> ComponentKey:
        """Which component a stored path belongs to: the file, in its directory."""
        directory, _, filename = path.rpartition("/")
        return ComponentKey(namespace=directory, name=filename)


_registry: dict[str, Format] = {}


def register(format: Format) -> None:
    if not format.name:
        raise ValueError("a format needs a name before it can be registered")
    _registry[format.name] = format


def get_format(name: str) -> Format | None:
    return _registry.get(name)


def format_names() -> list[str]:
    return sorted(_registry)
