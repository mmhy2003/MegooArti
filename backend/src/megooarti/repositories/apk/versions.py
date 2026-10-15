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
# An architecture, as Alpine names them (`x86_64`, `aarch64`, `armv7`, `noarch`).
ARCH = re.compile(r"[a-z0-9_]{1,32}")
NOARCH = "noarch"
