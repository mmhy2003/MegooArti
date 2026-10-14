set -e
apt-get update -qq >/dev/null && apt-get install -y -qq dpkg-dev zstd xz-utils >/dev/null
cd /tmp
make() {  # name version arch compression
  rm -rf p && mkdir -p p/DEBIAN p/usr/bin
  printf '#!/bin/sh\necho "hello from %s %s"\n' "$1" "$2" > p/usr/bin/$1 && chmod 755 p/usr/bin/$1
  cat > p/DEBIAN/control <<CONTROL
Package: $1
Version: $2
Architecture: $3
Maintainer: MegooArti Tests <tests@example.com>
Installed-Size: 1
Depends: libc6 (>= 2.17)
Section: utils
Priority: optional
Homepage: https://example.com/$1
Description: Says hello ($4)
 A package made for the tests of MegooArti.
 .
 It prints one line.
CONTROL
  dpkg-deb -Z$4 --root-owner-group --build p "/out/$1_$2_$3.deb" >/dev/null
}
make megooarti-hello 1.0-1 all gzip
make megooarti-hello 1:2.0~rc1-1 amd64 xz
make megooarti-tool 0.3 arm64 zstd
make megooarti-plain 1.0 amd64 none
cd /out && dpkg-scanpackages --multiversion . /dev/null > Packages 2>/dev/null
dpkg-deb --version | head -1
