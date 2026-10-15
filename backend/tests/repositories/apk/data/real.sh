# Two of Alpine 3.24's packages, and what its own index says of them.
set -e
base=https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64
for package in lxc-lvm-7.0.0-r0 yash-binsh-2.60-r0; do
  curl -sf "$base/$package.apk" -o "$package.apk"
done
curl -sf "$base/APKINDEX.tar.gz" | tar -xzO APKINDEX 2>/dev/null \
  | awk -v RS= -v ORS='\n\n' '/\nP:(lxc-lvm|yash-binsh)\n/' > alpine-APKINDEX
