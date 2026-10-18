"""RPM's names and versions: how they are written, split and compared."""

import re

# A package's name, as rpm takes one.
NAME = re.compile(r"[A-Za-z0-9_+][A-Za-z0-9._+-]{0,254}")
# A version or a release: what a command can be given.
PART = re.compile(r"[A-Za-z0-9._+~^]{1,128}")


def evr(epoch: str, version: str, release: str) -> str:
    """`epoch:version-release`, as dnf is given it: without an epoch of 0."""
    return f"{version}-{release}" if epoch in ("", "0") else f"{epoch}:{version}-{release}"


def split(evr: str) -> tuple[str, str, str] | None:
    """A component's `[epoch:]version-release`, if it can be put in a command as it is."""
    epoch, _, rest = evr.rpartition(":")
    version, _, release = rest.rpartition("-")
    if epoch and not (epoch.isascii() and epoch.isdigit()):
        return None
    if PART.fullmatch(version) is None or PART.fullmatch(release) is None:
        return None
    return epoch or "0", version, release


def split_evr(said: str) -> tuple[str, str, str]:
    """The epoch, version and release of a dependency's version, as createrepo_c splits it.

    An epoch that is not a number is not one, and none is 0. The version ends at the
    first `-`; a release may be empty.
    """
    epoch, colon, rest = said.partition(":")
    if not colon:
        epoch, rest = "", said
    elif not (epoch.isascii() and epoch.isdigit()):
        epoch = ""
    version, _, release = rest.partition("-")
    return epoch or "0", version, release


def compare_evr(one: str, two: str) -> int:
    """-1, 0 or 1 as `[epoch:]version-release` `one` is older, the same or newer than `two`."""
    first, second = split_evr(one), split_evr(two)
    if int(first[0]) != int(second[0]):
        return -1 if int(first[0]) < int(second[0]) else 1
    return compare(first[1], second[1]) or compare(first[2], second[2])


def _alnum(text: str, at: int) -> bool:
    return at < len(text) and text[at].isascii() and text[at].isalnum()


def compare(one: str, two: str) -> int:
    """rpm's `rpmvercmp`: -1, 0 or 1 as `one` is older, the same or newer than `two`."""
    if one == two:
        return 0
    i = j = 0
    while i < len(one) or j < len(two):
        while i < len(one) and not _alnum(one, i) and one[i] not in "~^":
            i += 1
        while j < len(two) and not _alnum(two, j) and two[j] not in "~^":
            j += 1
        a = one[i] if i < len(one) else ""
        b = two[j] if j < len(two) else ""
        if a == "~" or b == "~":  # a tilde sorts before everything, its end too
            if a != "~":
                return 1
            if b != "~":
                return -1
            i, j = i + 1, j + 1
            continue
        if a == "^" or b == "^":  # a caret sorts after its end, before anything else
            if not a:
                return -1
            if not b:
                return 1
            if a != "^":
                return 1
            if b != "^":
                return -1
            i, j = i + 1, j + 1
            continue
        if not (a and b):
            break
        numeric = a.isdigit()
        same = str.isdigit if numeric else str.isalpha
        end_one, end_two = i, j
        while end_one < len(one) and one[end_one].isascii() and same(one[end_one]):
            end_one += 1
        while end_two < len(two) and two[end_two].isascii() and same(two[end_two]):
            end_two += 1
        if end_two == j:  # a number is newer than letters
            return 1 if numeric else -1
        left, right = one[i:end_one], two[j:end_two]
        if numeric:
            left, right = left.lstrip("0"), right.lstrip("0")
            if len(left) != len(right):
                return 1 if len(left) > len(right) else -1
        if left != right:
            return 1 if left > right else -1
        i, j = end_one, end_two
    if i >= len(one) and j >= len(two):
        return 0
    return -1 if i >= len(one) else 1
