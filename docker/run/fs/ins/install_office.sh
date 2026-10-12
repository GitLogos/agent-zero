#!/bin/bash
set -e

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get unavailable; skipping LibreOffice install"
  exit 0
fi

ATK_VERSION="2.60.3-1"
LIBREOFFICE_VERSION="4:26.2.4.2-1"

ATK_PACKAGES=(
  "at-spi2-common=$ATK_VERSION"
  "libatk1.0-0t64=$ATK_VERSION"
  "libatk-bridge2.0-0t64=$ATK_VERSION"
  "libatspi2.0-0t64=$ATK_VERSION"
  "gir1.2-atk-1.0=$ATK_VERSION"
)
for package in at-spi2-core gir1.2-atspi-2.0; do
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
    ATK_PACKAGES+=("$package=$ATK_VERSION")
  fi
done

LIBREOFFICE_PACKAGES=(
  "libreoffice-core=$LIBREOFFICE_VERSION"
  "libreoffice-writer=$LIBREOFFICE_VERSION"
  "libreoffice-calc=$LIBREOFFICE_VERSION"
  "libreoffice-impress=$LIBREOFFICE_VERSION"
  "libreoffice-gtk3=$LIBREOFFICE_VERSION"
  "python3-uno=$LIBREOFFICE_VERSION"
)

cat >/etc/apt/a0-office.list <<EOF
deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian/20260624T000000Z/ forky main
EOF
APT_OPTIONS=(-o Dir::Etc::sourcelist=/etc/apt/a0-office.list -o Dir::Etc::sourceparts=- -o APT::Update::Error-Mode=any)

apt-get "${APT_OPTIONS[@]}" update
DEBIAN_FRONTEND=noninteractive apt-get "${APT_OPTIONS[@]}" install -y --no-install-recommends --allow-downgrades \
  "${ATK_PACKAGES[@]}" \
  gir1.2-gtk-3.0 \
  "${LIBREOFFICE_PACKAGES[@]}" \
  fonts-dejavu \
  fonts-liberation \
  fonts-crosextra-caladea \
  fonts-crosextra-carlito \
  fonts-noto-core \
  fonts-noto-cjk \
  fonts-noto-color-emoji

rm -rf /var/lib/apt/lists/*
