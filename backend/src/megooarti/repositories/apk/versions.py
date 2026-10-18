"""apk's names, versions and architectures: what each may be."""

import re

# A package's name, as abuild takes one.
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._+-]{0,254}")
# A version: numbers, a letter, suffixes (`_rc1`, `_git20260101`), a release (`-r2`).
VERSION = re.compile(
    r"[0-9]+(\.[0-9]+)*[a-z]?"
    r"(_(alpha|beta|pre|rc|cvs|svn|git|hg|p)[0-9]*)*"
    r"(~[0-9a-f]+)?(-r[0-9]+)?"
)
# A suffix's place: those before a release, none, and those after one.
_SUFFIXES = {"alpha": 0, "beta": 1, "pre": 2, "rc": 3, "": 4, "cvs": 5, "svn": 6, "git": 7}
_SUFFIXES |= {"hg": 8, "p": 9}
_PARTS = re.compile(
    r"(?P<numbers>[0-9]+(?:\.[0-9]+)*)(?P<letter>[a-z]?)"
    r"(?P<suffixes>(?:_[a-z]+[0-9]*)*)(?:~[0-9a-f]+)?(?:-r(?P<release>[0-9]+))?"
)
_SUFFIX = re.compile(r"_([a-z]+)([0-9]*)")


def sort_key(version: str) -> tuple:
    """A version's place as apk orders them: `1.0_rc1` before `1.0`, before `1.0-r1`,
    before `1.0a`. Text that is not a version comes before them all."""
    found = _PARTS.fullmatch(version)
    if found is None:
        return (0, (), version)
    numbers = tuple(int(number) for number in found["numbers"].split("."))
    suffixes = tuple(
        (_SUFFIXES.get(name, 4), int(number or 0))
        for name, number in _SUFFIX.findall(found["suffixes"])
    ) + ((_SUFFIXES[""], 0),)
    release = int(found["release"] or 0)
    return (1, (numbers, found["letter"], suffixes, release), version)


def is_prerelease(version: str) -> bool:
    """Whether a suffix says that it comes before a release (`_alpha`, `_beta`, `_pre`,
    `_rc`)."""
    found = _PARTS.fullmatch(version)
    return found is not None and any(
        _SUFFIXES.get(name, 4) < _SUFFIXES[""] for name, _ in _SUFFIX.findall(found["suffixes"])
    )


# An architecture, as Alpine names them (`x86_64`, `aarch64`, `armv7`, `noarch`).
ARCH = re.compile(r"[a-z0-9_]{1,32}")
NOARCH = "noarch"
