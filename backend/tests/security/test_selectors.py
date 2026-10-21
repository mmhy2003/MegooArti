"""Content selectors' expressions (spec 10, D2): what they say, what they match, what they
refuse and where, and what they let a listing leave out."""

import pytest
from sqlalchemy import literal, select

from megooarti.security.selectors import Reach, SelectorError, parse

PATHS = [
    "/com/acme/app/1.0/app-1.0.jar",
    "/com/acme/lib/2.0/lib-2.0.pom",
    "/org/example/tool/1.0/tool-1.0.jar",
    "/org/example/tool/1.1/tool-1.1.jar",
    '/odd/"quoted"/a\\b.txt',
]


@pytest.mark.parametrize(
    ("text", "format", "matching"),
    [
        ('format == "maven"', "maven", PATHS),
        ('format == "maven"', "npm", []),
        ('path == "/com/acme/app/1.0/app-1.0.jar"', "maven", PATHS[:1]),
        ('path =^ "/com/acme/"', "maven", PATHS[:2]),
        ('path =~ "^/org/[^/]+/[^/]+/1\\\\.0/.*$"', "maven", PATHS[2:3]),
        ('path =~ "/org/.*"', "maven", PATHS[2:4]),  # the whole path, anchored or not
        ('path =~ "org"', "maven", []),
        ('not path =^ "/com/"', "maven", PATHS[2:]),
        ('format == "maven" and path =^ "/org/"', "maven", PATHS[2:4]),
        ('path =^ "/com/acme/lib/" or path =~ ".*1\\\\.1.*"', "maven", [PATHS[1], PATHS[3]]),
        ('not (path =^ "/com/" or path =^ "/org/")', "maven", PATHS[4:]),
        ('path == "/odd/\\"quoted\\"/a\\\\b.txt"', "raw", PATHS[4:]),
        ('  path=^"/com/acme/app/"and format=="maven"  ', "maven", PATHS[:1]),
    ],
)
def test_an_expression_matches_what_it_says(text, format, matching):
    expression = parse(text)

    assert [path for path in PATHS if expression.matches(format, path)] == matching


def test_and_binds_before_or_and_not_before_both():
    # a or (b and c), and (not a) and b
    either = parse('path =^ "/com/" or path =^ "/org/" and path =^ "/org/none/"')
    negated = parse('not path =^ "/com/" and path =^ "/org/"')

    assert [path for path in PATHS if either.matches("maven", path)] == PATHS[:2]
    assert [path for path in PATHS if negated.matches("maven", path)] == PATHS[2:4]


@pytest.mark.parametrize(
    ("text", "position", "said"),
    [
        ("", 1, "An expression is needed"),
        ('format = "maven"', 8, "Unexpected '='"),
        ('name == "x"', 1, "Expected format, path or ("),
        ('path "x"', 6, "Expected ==, =^ or =~"),
        ("path == maven", 9, "Expected a string in double quotes"),
        ('path == "open', 9, "A string is not closed"),
        ('path == "a\\n"', 11, 'Only \\" and \\\\ are written so'),
        ('(path == "x"', 13, "Expected )"),
        ('path == "x" path == "y"', 13, "Unexpected 'path'"),
        ('path =~ "("', 9, "Not a pattern"),
        ('path == "x" and', 16, "Expected format, path or ("),
        ('Path == "x"', 1, "Expected format, path or ("),
        ('path == "x" AND path == "y"', 13, "Unexpected 'AND'"),
    ],
)
def test_what_does_not_parse_is_refused_saying_where(text, position, said):
    with pytest.raises(SelectorError) as refused:
        parse(text)

    assert refused.value.position == position
    assert refused.value.message.startswith(said)


def test_too_long_a_pattern_or_too_deep_a_nesting_is_refused():
    with pytest.raises(SelectorError, match="at most 1000"):
        parse('path =~ "' + "a" * 1001 + '"')
    with pytest.raises(SelectorError, match="Too deeply nested"):
        parse("(" * 40 + 'path == "x"' + ")" * 40)
    with pytest.raises(SelectorError, match="Too deeply nested"):
        parse("not " * 40 + 'path == "x"')


def test_an_expression_is_parsed_once_for_its_text():
    assert parse('path =^ "/com/"') is parse('path =^ "/com/"')


@pytest.mark.parametrize(
    ("text", "folder", "reach"),
    [
        ('path =^ "/com/acme/"', "/", Reach.SOME),
        ('path =^ "/com/acme/"', "/com/", Reach.SOME),
        ('path =^ "/com/acme/"', "/com/acme/lib/", Reach.ALL),
        ('path =^ "/com/acme/"', "/org/", Reach.NONE),
        ('path == "/com/acme/app/1.0/app-1.0.jar"', "/com/acme/", Reach.SOME),
        ('path == "/com/acme/app/1.0/app-1.0.jar"', "/org/", Reach.NONE),
        ('path =~ "/org/.*"', "/com/", Reach.SOME),  # a pattern's reach cannot be told
        ('format == "npm"', "/", Reach.NONE),
        ('format == "maven"', "/", Reach.ALL),
        ('not path =^ "/com/"', "/com/acme/", Reach.NONE),
        ('not path =^ "/com/"', "/org/", Reach.ALL),
        ('path =^ "/com/" and path =^ "/org/"', "/", Reach.SOME),
        ('path =^ "/com/" and format == "npm"', "/com/", Reach.NONE),
        ('path =^ "/com/" or path =^ "/org/"', "/org/example/", Reach.ALL),
        ('path =^ "/com/" or path =^ "/org/"', "/net/", Reach.NONE),
    ],
)
def test_an_expression_says_how_much_of_a_folder_it_may_match(text, folder, reach):
    assert parse(text).under("maven", folder) is reach


@pytest.mark.parametrize(
    "text",
    [
        'path =^ "/com/acme/"',
        'path == "/org/example/tool/1.0/tool-1.0.jar"',
        'path =~ "/org/.*1\\\\.1.*"',
        'not path =^ "/com/"',
        'not path =~ "/com/.*"',
        'path =^ "/org/" and not path =~ ".*1\\\\.0.*"',
        'path =^ "/com/acme/lib/" or path =~ ".*1\\\\.1.*"',
        'path =^ "/odd/\\"quoted\\"/" or path =^ "/a%_b/"',
        'format == "npm" or path =^ "/org/"',
    ],
)
async def test_what_a_database_is_asked_keeps_every_match_and_is_exact_where_it_says(db, text):
    expression = parse(text)
    paths = [*PATHS, "/a%_b/c", "/aXYb/c"]

    for path in paths:
        condition, exact = expression.narrowing("maven", literal(path))
        kept = await db.scalar(select(condition))
        matched = expression.matches("maven", path)
        assert kept or not matched, (text, path)
        if exact:
            assert kept == matched, (text, path)


@pytest.mark.parametrize(
    "pattern",
    ["^/(\\\\w+/?)*\\\\.jar$", "(a+)+", "(a*)*b", "(?:x+){2,}", "((ab)+c)*"],
)
def test_a_pattern_that_repeats_a_repetition_is_refused(pattern):
    # Each takes time that doubles with the length of a path made to defeat it.
    with pytest.raises(SelectorError, match="repeats a repetition"):
        parse(f'path =~ "{pattern}"')


@pytest.mark.parametrize("pattern", [".*\\\\.jar", "(abc)+/x", "[a-z]+/.*", "(a|b)*", "x{2,5}"])
def test_a_pattern_that_repeats_no_repetition_is_kept(pattern):
    assert parse(f'path =~ "{pattern}"')
