# Rocky Linux 10's BaseOS: its repomd.xml as signed, and the key it is signed with.
U=http://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os/repodata
curl -sf $U/repomd.xml -o rocky-10-baseos-repomd.xml
curl -sf $U/repomd.xml.asc -o rocky-10-baseos-repomd.xml.asc
docker run --rm rockylinux/rockylinux:10 cat /etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10 > RPM-GPG-KEY-Rocky-10
