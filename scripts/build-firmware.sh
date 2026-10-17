#!/usr/bin/env bash
# Builds and checks build/DaisyDiagnostic.bin. Linux: put arm-none-eabi-* on PATH
# (../../scripts/install-toolchain.sh). Windows/Git Bash: install-toolchain-windows.sh.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
for dir in "$repo/.tools/xpack-arm-none-eabi-gcc-13.2.1-1.1/bin" \
           "$repo/.tools/xpack-windows-build-tools-4.4.1-3/bin"; do
    [[ -d "$dir" ]] && PATH="$dir:$PATH"
done
export PATH
python_cmd=python3
command -v python3 >/dev/null 2>&1 && python3 -c "" 2>/dev/null || python_cmd=python
make -C "$repo/diagnostics/firmware" -j4
make -C "$repo/diagnostics/firmware" check PYTHON="$python_cmd"
(cd "$repo/diagnostics/firmware/build" && sha256sum DaisyDiagnostic.bin)
