"""The Raw format: arbitrary files stored and served by path."""

from megooarti.repositories.formats import Format, register


class RawFormat(Format):
    """Entirely the generic behaviour."""

    name = "raw"


register(RawFormat())
