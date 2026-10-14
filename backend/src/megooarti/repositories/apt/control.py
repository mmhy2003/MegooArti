"""A Debian control paragraph: fields, in order, as `control` files and `Packages` have them.

A value keeps its continuation lines, each beginning with a space, so that writing a
paragraph again gives back what was read. A continuation line cannot begin a field of
its own: whatever a package says, it cannot add a field to an index it is listed in.
"""

import re

# A field's name: printable, without a colon or a space, and not beginning with `#`
# or `-`, which a control file uses for comments and for signatures.
_NAME = re.compile(r"[!-9;-~][!-9;-~]*")
_LINE = re.compile(r"([^:\s]+):(.*)")

type Paragraph = list[tuple[str, str]]


class InvalidControl(ValueError):
    """Text that is not one control paragraph."""


def parse(text: str) -> Paragraph:
    """The fields of one paragraph, in order. Comments and blank lines around it go."""
    fields: Paragraph = []
    seen: set[str] = set()
    ended = False
    for line in text.split("\n"):
        if "\r" in line:
            raise InvalidControl("a line ends in a carriage return")
        if line.startswith("#"):
            continue
        if not line.strip():
            ended = ended or bool(fields)
            continue
        if ended:
            raise InvalidControl("there is more than one paragraph")
        if line[0] in " \t":
            if not fields:
                raise InvalidControl("it begins with a continuation line")
            name, value = fields[-1]
            fields[-1] = (name, f"{value}\n{line.rstrip()}")
            continue
        found = _LINE.fullmatch(line)
        if found is None or _NAME.fullmatch(found[1]) is None or found[1][0] in "#-":
            raise InvalidControl(f"a line is not a field: {line[:60]!r}")
        name = found[1]
        if name.lower() in seen:
            raise InvalidControl(f"the field {name} is given twice")
        seen.add(name.lower())
        fields.append((name, found[2].strip()))
    if not fields:
        raise InvalidControl("it has no fields")
    return fields


def get(paragraph: Paragraph, name: str) -> str | None:
    """A field's value, whatever the case of its name. None if it is not there."""
    wanted = name.lower()
    return next((value for field, value in paragraph if field.lower() == wanted), None)


def first_line(value: str) -> str:
    return value.partition("\n")[0]


def format_paragraph(paragraph: Paragraph) -> str:
    """The paragraph as text, each field on its line, without a blank line after it."""
    lines = []
    for name, value in paragraph:
        lines.append(f"{name}:{value}" if value.startswith("\n") else f"{name}: {value}")
    return "\n".join(lines) + "\n"
