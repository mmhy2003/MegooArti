# Two packages built with abuild in Alpine's image, their index made and signed as
# abuild makes and signs it, and the key they are signed with.
set -e
apk add -q alpine-sdk > /dev/null
adduser -D builder && addgroup builder abuild
su builder -c 'abuild-keygen -a -n -q' > /dev/null 2>&1
cp /home/builder/.abuild/*.rsa.pub /etc/apk/keys/
mkdir -p /work/hello /work/tool
cat > /work/hello/APKBUILD <<'SPEC'
pkgname=megooarti-hello
pkgver=1.0
pkgrel=0
pkgdesc="Says hello"
url="https://example.com/megooarti-hello"
arch="noarch"
license="MIT"
depends="busybox"
provides="hello-tool=1.0"
replaces="megooarti-old"
provider_priority=10
replaces_priority=5
maintainer="MegooArti Tests <tests@example.com>"
options="!check"
package() {
	mkdir -p "$pkgdir"/usr/bin
	printf '#!/bin/sh\necho "hello from megooarti-hello 1.0"\n' > "$pkgdir"/usr/bin/megooarti-hello
	chmod 755 "$pkgdir"/usr/bin/megooarti-hello
}
SPEC
cat > /work/tool/APKBUILD <<'SPEC'
pkgname=megooarti-tool
pkgver=0.3_rc1
pkgrel=2
pkgdesc="A tool with every kind of dependency"
url="https://example.com/megooarti-tool"
arch="x86_64"
license="MIT"
depends="megooarti-hello>=1.0"
provides="cmd:megooarti-tool=0.3_rc1-r2"
install_if="megooarti-hello busybox"
options="!check"
package() {
	mkdir -p "$pkgdir"/usr/share/megooarti
	echo tool > "$pkgdir"/usr/share/megooarti/tool.txt
}
SPEC
chown -R builder /work
for p in hello tool; do su builder -c "cd /work/$p && abuild -q -r -P /work/out" > /dev/null 2>&1 || { echo "build $p failed"; exit 1; }; done
find /work/out -type f
