#!/usr/bin/env bash
# Builds/checks both BOOT_SRAM variants. Linux: put arm-none-eabi-* on PATH
# (scripts/install-toolchain.sh). Windows/Git Bash: install-toolchain-windows.sh.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for dir in "$repo/.tools/xpack-arm-none-eabi-gcc-13.2.1-1.1/bin" \
           "$repo/.tools/xpack-windows-build-tools-4.4.1-3/bin"; do
    [[ -d "$dir" ]] && PATH="$dir:$PATH"
done
export PATH
python_cmd=python3
command -v python3 >/dev/null 2>&1 && python3 -c "" 2>/dev/null || python_cmd=python
for reader in 0 1; do
    make -C "$repo/firmware" CARD_READER="$reader" -j4
    make -C "$repo/firmware" CARD_READER="$reader" check PYTHON="$python_cmd"
done
(cd "$repo/firmware/build" && sha256sum DaisyDiagnostic.bin > SHA256SUMS && cat SHA256SUMS)
(cd "$repo/firmware/build/reader" && sha256sum DaisyDiagnostic-CardReader.bin > SHA256SUMS && cat SHA256SUMS)
