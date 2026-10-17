"""What a request of V2 asks for, read as the clients of D7 send it: each query here is
one that `nuget.exe`, `choco` or PSResourceGet was seen to send."""

import re

import pytest

from megooarti.repositories.nuget import odata
from megooarti.repositories.nuget.odata import Filter, Query


@pytest.mark.parametrize(
    ("path", "arguments", "query"),
    [
        # nuget.exe install, and choco install with a version.
        (
            "Packages(Id='MegooArti.Hello',Version='1.0')",
            {},
            Query("entry", "MegooArti.Hello", "1.0.0"),
        ),
        # nuget.exe install without a version, choco search --all-versions.
        (
            "FindPackagesById()",
            {"id": "'MegooArti.Hello'", "semVerLevel": "2.0.0"},
            Query("find", id="MegooArti.Hello"),
        ),
        # nuget.exe list.
        (
            "Search()",
            {
                "$orderby": "Id",
                "searchTerm": "'MegooArti'",
                "targetFramework": "''",
                "includePrerelease": "true",
                "$skip": "0",
                "$top": "30",
                "semVerLevel": "2.0.0",
            },
            Query("search", search_term="MegooArti", order=(("id", False),), top=30),
        ),
        # choco search.
        (
            "Search()",
            {
                "$filter": "IsLatestVersion",
                "$orderby": "Id,Version desc",
                "searchTerm": "'megooarti'",
                "targetFramework": "''",
                "includePrerelease": "false",
                "$skip": "0",
                "$top": "30",
            },
            Query(
                "search",
                search_term="megooarti",
                prerelease=False,
                filter=Filter(latest=True),
                order=(("id", False), ("version", True)),
                top=30,
            ),
        ),
        # choco install.
        (
            "Packages()",
            {"$filter": "(tolower(Id) eq 'megooarti-choco') and IsLatestVersion"},
            Query("packages", filter=Filter(id="megooarti-choco", latest=True)),
        ),
        # PSResourceGet: Find-PSResource with a range of versions.
        (
            "FindPackagesById()",
            {
                "$filter": (
                    "NormalizedVersion ge '1.0.0' and NormalizedVersion le '2.0.0' and "
                    "IsPrerelease eq false and Id eq 'MegooArtiPS'"
                ),
                "$inlinecount": "allpages",
                "$skip": "0",
                "$orderby": "NormalizedVersion desc",
                "id": "'MegooArtiPS'",
            },
            Query(
                "find",
                id="MegooArtiPS",
                filter=Filter(
                    id="megooartips",
                    versions=(("ge", "1.0.0"), ("le", "2.0.0")),
                    prerelease=False,
                ),
                order=(("version", True),),
                inline_count=True,
            ),
        ),
        # PSResourceGet: a name with a wildcard, and tags; more than a page asked for.
        (
            "Search()",
            {
                "$filter": "IsLatestVersion and startswith(Id, 'MegooArti')",
                "$inlinecount": "allpages",
                "$top": "6000",
            },
            Query(
                "search",
                prerelease=False,
                filter=Filter(id_starts="megooarti", latest=True),
                inline_count=True,
            ),
        ),
        (
            "Search()",
            {
                "$filter": (
                    "IsLatestVersion and substringof('PSModule', Tags) eq true and "
                    "substringof('hello', Tags) eq true"
                ),
            },
            Query(
                "search", prerelease=False, filter=Filter(tags=("psmodule", "hello"), latest=True)
            ),
        ),
        (
            "Packages()/$count",
            {"$filter": "IsAbsoluteLatestVersion"},
            Query("packages", filter=Filter(absolute_latest=True), count=True),
        ),
    ],
)
def test_a_query_a_client_sends_is_read(path, arguments, query):
    assert odata.parse(path, arguments) == query


@pytest.mark.parametrize(
    ("path", "arguments", "said"),
    [
        ("GetUpdates()", {}, "is not a function"),
        ("Packages()", {"$select": "Id"}, "$select is not taken"),
        ("Packages()", {"$filter": "Title eq 'x'"}, "$filter does not take"),
        ("Packages()", {"$filter": "Id eq x"}, "$filter does not take 'Id eq x'"),
        ("Packages()", {"$orderby": "Title"}, "$orderby does not take"),
        ("Packages()", {"$top": "-1"}, "whole number"),
        ("Search()", {"includePrerelease": "maybe"}, "true or false"),
        ("FindPackagesById()", {"id": "'it's'"}, "not doubled"),
    ],
)
def test_what_no_client_sends_is_refused_by_name(path, arguments, said):
    with pytest.raises(odata.UnsupportedQuery, match=re.escape(said)):
        odata.parse(path, arguments)


def test_a_quote_in_a_string_is_doubled():
    assert odata.parse("FindPackagesById()", {"id": "'it''s'"}).id == "it's"


def test_a_version_that_is_none_matches_none():
    query = odata.parse("Packages()", {"$filter": "Version eq 'not.a.version!'"})

    assert query.filter.versions == (("eq", "none:not.a.version!"),)
