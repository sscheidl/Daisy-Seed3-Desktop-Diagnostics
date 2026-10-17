#!/usr/bin/env bash
# Installs the pinned xPack ARM GCC and GNU Make for Windows x64 into <repo>/.tools
# (run from Git Bash). Checksums are the values published with the xPack releases.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tools="$repo/.tools"
mkdir -p "$tools"
cd "$tools"
fetch() {  # url, archive name, sha256
    if [[ ! -f "$2.done" ]]; then
        curl --fail --location --retry 3 "$1" --output "$2.partial"
        printf '%s  %s\n' "$3" "$2.partial" | sha256sum --check -
        unzip -q -o "$2.partial"
        rm "$2.partial"
        touch "$2.done"
    fi
}
fetch https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v13.2.1-1.1/xpack-arm-none-eabi-gcc-13.2.1-1.1-win32-x64.zip \
    arm-gcc.zip 56b18ccb0a50f536332ec5de57799342ff0cd005ca2c54288c74759b51929e4f
fetch https://github.com/xpack-dev-tools/windows-build-tools-xpack/releases/download/v4.4.1-3/xpack-windows-build-tools-4.4.1-3-win32-x64.zip \
    build-tools.zip 113d4dfdbbc56dc9b865c9f75d38cd0da82f0d7094187e6f7a803fe6eef1d218
echo "export PATH=\"$tools/xpack-arm-none-eabi-gcc-13.2.1-1.1/bin:$tools/xpack-windows-build-tools-4.4.1-3/bin:\$PATH\""
