set -e
dnf install -y -q rpm-build createrepo_c > /dev/null 2>&1
mkdir -p /tmp/rpm/SPECS && cd /tmp/rpm
cat > SPECS/hello.spec <<'SPEC'
Name: megooarti-hello
Version: 1.0
Release: 1
Summary: Says hello
License: MIT
URL: https://example.com/megooarti-hello
BuildArch: noarch
Requires: bash
Requires(pre): coreutils
Requires(post): grep
Requires(preun): sed
Requires(postun): gawk
Requires(posttrans): findutils
Provides: hello-tool = 1.0
%description
A package made for the tests of MegooArti.
It prints one line: “hello”.
%install
mkdir -p %{buildroot}/usr/bin %{buildroot}/etc/megooarti
printf '#!/bin/sh\necho "hello from megooarti-hello 1.0"\n' > %{buildroot}/usr/bin/megooarti-hello
chmod 755 %{buildroot}/usr/bin/megooarti-hello
echo "greeting=hello" > %{buildroot}/etc/megooarti/hello.conf
%files
/usr/bin/megooarti-hello
%dir /etc/megooarti
%config /etc/megooarti/hello.conf
%ghost /var/log/megooarti-hello.log
%changelog
* Mon Oct 12 2026 MegooArti Tests <tests@example.com> - 1.0-1
- The first version.
SPEC
cat > SPECS/tool.spec <<'SPEC'
Name: megooarti-tool
Epoch: 2
Version: 0.3
Release: 2
Summary: A tool with every kind of dependency
License: MIT
BuildArch: x86_64
Requires: megooarti-hello >= 1.0
Recommends: less
Suggests: vim-minimal
Supplements: megooarti-hello
Enhances: bash
Conflicts: megooarti-old < 1
Obsoletes: megooarti-older <= 0.9
%global debug_package %{nil}
%description
A tool.
%install
mkdir -p %{buildroot}/usr/share/megooarti
echo tool > %{buildroot}/usr/share/megooarti/tool.txt
%files
/usr/share/megooarti/tool.txt
%changelog
* Mon Oct 12 2026 Tool Maker <maker@example.com> - 2:0.3-12
- Change 12 & more <here>.

* Mon Oct 12 2026 Tool Maker <maker@example.com> - 2:0.3-11
- Change 11 & more <here>.

* Fri Oct 09 2026 Tool Maker <maker@example.com> - 2:0.3-10
- Change 10 & more <here>.

* Thu Oct 08 2026 Tool Maker <maker@example.com> - 2:0.3-9
- Change 9 & more <here>.

* Wed Oct 07 2026 Tool Maker <maker@example.com> - 2:0.3-8
- Change 8 & more <here>.

* Tue Oct 06 2026 Tool Maker <maker@example.com> - 2:0.3-7
- Change 7 & more <here>.

* Mon Oct 05 2026 Tool Maker <maker@example.com> - 2:0.3-6
- Change 6 & more <here>.

* Sun Oct 04 2026 Tool Maker <maker@example.com> - 2:0.3-5
- Change 5 & more <here>.

* Sat Oct 03 2026 Tool Maker <maker@example.com> - 2:0.3-4
- Change 4 & more <here>.

* Fri Oct 02 2026 Tool Maker <maker@example.com> - 2:0.3-3
- Change 3 & more <here>.

* Thu Oct 01 2026 Tool Maker <maker@example.com> - 2:0.3-2
- Change 2 & more <here>.

* Wed Sep 30 2026 Tool Maker <maker@example.com> - 2:0.3-1
- Change 1 & more <here>.
SPEC
rpmbuild --quiet --define "_topdir /tmp/rpm" -ba SPECS/hello.spec
rpmbuild --quiet --define "_topdir /tmp/rpm" -bb SPECS/tool.spec
mkdir -p /tmp/repo && cp RPMS/*/*.rpm /tmp/repo/ && cp RPMS/*/*.rpm SRPMS/*.rpm /out/
createrepo_c -q --general-compress-type=gz --no-database /tmp/repo
cd /tmp/repo/repodata && for f in *-primary.xml.gz *-filelists.xml.gz *-other.xml.gz; do kind=$(echo $f | sed -E 's/^[0-9a-f]+-//; s/\.gz$//'); gunzip -c $f > /out/createrepo-$kind; done
cp repomd.xml /out/createrepo-repomd.xml
rpm --version
ls /out
