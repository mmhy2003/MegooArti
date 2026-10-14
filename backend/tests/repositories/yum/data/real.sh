# Two of Fedora 44's packages, and what createrepo_c writes of them; and of nothing.
set -e
dnf install -y -q createrepo_c > /dev/null 2>&1
mkdir -p /tmp/real /tmp/empty /out/real
cd /tmp/real && dnf download -q bash-5.3.9-3.fc44 setup-2.15.0-28.fc44 > /dev/null 2>&1
createrepo_c -q --general-compress-type=gz --no-database /tmp/real
createrepo_c -q --general-compress-type=gz --no-database /tmp/empty
for repo in real empty; do
  cd /tmp/$repo/repodata
  for f in *-primary.xml.gz *-filelists.xml.gz *-other.xml.gz; do
    kind=$(echo $f | sed -E 's/^[0-9a-f]+-//; s/\.gz$//')
    gunzip -c $f > /out/real/$repo-createrepo-$kind
  done
done
cp /tmp/real/*.rpm /out/real/
