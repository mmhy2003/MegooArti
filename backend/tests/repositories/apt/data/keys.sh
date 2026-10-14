set -e
apt-get update -qq >/dev/null && apt-get install -y -qq gnupg >/dev/null 2>&1
export GNUPGHOME=/tmp/g && mkdir -m 700 -p $GNUPGHOME
gpg --batch --pinentry-mode loopback --passphrase 'a passphrase' --quick-gen-key 'Protected <p@example.com>' ed25519 sign never 2>/dev/null
gpg --batch --pinentry-mode loopback --passphrase 'a passphrase' --armor --export-secret-keys 'Protected' > /out/protected.asc
gpg --batch --passphrase '' --quick-gen-key 'Plain RSA <r@example.com>' rsa3072 sign never 2>/dev/null
gpg --batch --armor --export-secret-keys 'Plain RSA' > /out/plain-rsa.asc
gpg --batch --armor --export 'Plain RSA' > /out/plain-rsa.pub.asc
head -1 /out/protected.asc /out/plain-rsa.asc
