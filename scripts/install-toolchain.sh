#!/usr/bin/env bash
set -euo pipefail
# Pinned, relocatable Linux x86_64 toolchain, no sudo required.
[[ "$(uname -s)-$(uname -m)" == Linux-x86_64 ]] || {
    echo 'This installer supports Linux x86_64. See docs/BUILD.md for other systems.' >&2
    exit 1
}
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version=13.2.1-1.1
archive="xpack-arm-none-eabi-gcc-${version}-linux-x64.tar.gz"
checksum=1252a8cafe9237de27a765376697230368eec21db44dc3f1edeb8d838dabd530
mkdir -p "$project_dir/.tools"
cd "$project_dir/.tools"
curl --fail --location --retry 3 \
    "https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v${version}/${archive}" \
    --output "${archive}.partial"
printf '%s  %s\n' "$checksum" "${archive}.partial" | sha256sum --check -
tar -xzf "${archive}.partial"
rm "${archive}.partial"
echo "Installed in $project_dir/.tools/xpack-arm-none-eabi-gcc-${version}/bin"
