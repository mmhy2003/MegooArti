"""What a path of a NuGet repository is."""

import pytest

from megooarti.repositories.nuget import paths
from megooarti.repositories.nuget.paths import NuGetPath


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("index.json", NuGetPath("service-index")),
        ("v3/package/megooarti.hello/index.json", NuGetPath("versions", "megooarti.hello")),
        (
            "v3/package/megooarti.hello/1.0.0-beta/megooarti.hello.1.0.0-beta.nupkg",
            NuGetPath("package", "megooarti.hello", "1.0.0-beta"),
        ),
        (
            "v3/package/megooarti.hello/1.0.0/megooarti.hello.nuspec",
            NuGetPath("nuspec", "megooarti.hello", "1.0.0"),
        ),
        (
            "v3/package/megooarti.hello/1.0.0/megooarti.hello.1.0.0.snupkg",
            NuGetPath("symbols", "megooarti.hello", "1.0.0"),
        ),
        (
            "v3/registration/megooarti.hello/index.json",
            NuGetPath("registration", "megooarti.hello"),
        ),
        (
            "v3/registration/megooarti.hello/1.0.0.json",
            NuGetPath("leaf", "megooarti.hello", "1.0.0"),
        ),
        (
            "v3/registration/megooarti.hello/page/1.0.0/1.63.0.json",
            NuGetPath("page", "megooarti.hello", lower="1.0.0", upper="1.63.0"),
        ),
        # Bounds that are not versions, or not as a client is given them.
        ("v3/registration/megooarti.hello/page/1.0/1.63.0.json", NuGetPath("other")),
        ("v3/registration/megooarti.hello/page/1.0.0/other.json", NuGetPath("other")),
        ("v3/registration/MegooArti.Hello/page/1.0.0/1.63.0.json", NuGetPath("other")),
        ("v3/search", NuGetPath("search")),
        ("v3/autocomplete", NuGetPath("autocomplete")),
        ("api/v2/package", NuGetPath("publish")),
        # As dotnet pushes: to the service index's address, with a slash after it.
        ("api/v2/package/", NuGetPath("publish")),
        ("api/v2/symbolpackage/", NuGetPath("symbol-publish")),
        (
            "api/v2/package/MegooArti.Hello/1.0",
            NuGetPath("delete", "megooarti.hello", "1.0.0"),
        ),
        # Not as a client asks: in capitals, not normalized, another file, or no id.
        ("v3/package/MegooArti.Hello/index.json", NuGetPath("other")),
        ("v3/package/megooarti.hello/1.0/megooarti.hello.1.0.nupkg", NuGetPath("other")),
        ("v3/package/megooarti.hello/1.0.0/other.dll", NuGetPath("other")),
        ("v3/package/.hello/index.json", NuGetPath("other")),
        # V2's feed: its root, its metadata and its functions; and its address of a package.
        ("", NuGetPath("v2")),
        ("$metadata", NuGetPath("v2")),
        ("FindPackagesById()", NuGetPath("v2")),
        ("Search()/$count", NuGetPath("v2")),
        ("Packages(Id='MegooArti.Hello',Version='1.0.0')", NuGetPath("v2")),
        ("package/MegooArti.Hello/1.0", NuGetPath("download", "megooarti.hello", "1.0.0")),
        ("package/MegooArti.Hello/not-a-version", NuGetPath("other")),
        ("GetUpdates()", NuGetPath("other")),
    ],
)
def test_a_path_is_what_a_nuget_client_asks_for(path, kind):
    assert paths.classify(path) == kind


def test_a_package_is_kept_where_a_client_asks_for_it():
    assert (
        paths.package_path("MegooArti.Hello", "1.0.0-Beta")
        == "v3/package/megooarti.hello/1.0.0-beta/megooarti.hello.1.0.0-beta.nupkg"
    )
    assert paths.nuspec_path("MegooArti.Hello", "1.0.0") == (
        "v3/package/megooarti.hello/1.0.0/megooarti.hello.nuspec"
    )
    assert paths.symbols_path("MegooArti.Hello", "1.0.0") == (
        "v3/package/megooarti.hello/1.0.0/megooarti.hello.1.0.0.snupkg"
    )


def test_a_slash_too_many_is_passed_over_before_v2s_paths_alone():
    assert paths.v2_path("/FindPackagesById()") == "FindPackagesById()"
    assert paths.v2_path("//package/MegooArti.Hello/1.0.0") == "package/MegooArti.Hello/1.0.0"
    assert paths.v2_path("/index.json") == "/index.json"


def test_a_v2_client_deletes_a_version_under_the_repositorys_address():
    assert paths.v2_delete("MegooArti.Hello/1.0") == ("megooarti.hello", "1.0.0")
    assert paths.v2_delete("MegooArti.Hello/not-a-version") is None
    assert paths.v2_delete("v3/package/megooarti.hello") is None
