# Standalone build and tests

Run these commands from the repository root. Requirements: Git, Python 3.12,
GNU Make and the pinned ARM toolchain for firmware; g++ for Linux host tests or
MSVC Build Tools on Windows. The only direct submodule is libDaisy
`f715e4875b2d28445d0c11a0a17f064a248f69d0`. Toy Piano and DaisySP are not required.

```bash
git submodule update --init libDaisy
git -C libDaisy submodule update --init --recursive --jobs 4
# Windows / Git Bash:
bash scripts/install-toolchain-windows.sh
# Linux x86_64 instead:
# bash scripts/install-toolchain.sh
bash scripts/build-firmware.sh
```

Output: `firmware/build/DaisyDiagnostic.bin` and `.elf`. The build checks BOOT_SRAM
vectors and verifies the absence of SD write, erase, and lock paths.

The script also builds `firmware/build/reader/DaisyDiagnostic-CardReader.bin` and
`.elf`, with a separate object directory and an explicit writable symbol policy.
Individual builds/checks: `make -C firmware CARD_READER=0` (protected default) or
`make -C firmware CARD_READER=1`; append `check` to verify the selected image.
Both builds continue to reject FatFs mutation, formatting, erase and lock APIs.
Only the reader build permits the polled HAL/SDMMC block-write path.

```bash
python -m pip install -r windows/requirements.txt
python -m pytest tests/python -v
make -C firmware test test-sanitize
# Windows/MSVC alternative:
# scripts\run-host-tests-msvc.cmd
```

Build the Windows EXE with `windows\build_exe.cmd`; output is
`windows/dist/DaisyDiagnostic.exe`. Startup without hardware:
`DaisyDiagnostic.exe --sim --selftest 5`.

For offscreen Windows tests, set `QT_QPA_PLATFORM=offscreen` and
`QT_QPA_FONTDIR=C:\Windows\Fonts`. This ensures that the headless renderer finds fonts.

GitHub CI runs software tests, ARM compilation, binary checks, EXE packaging, and
a simulation startup test. It uploads separate firmware and Windows artifacts
with checksums and source-commit records. There are three artifacts: protected
firmware, writable reader firmware, and Windows EXE. Software checks do not
replace hardware validation; see [SD_CARD_READER.md](SD_CARD_READER.md).
See [FIRMWARE.md](FIRMWARE.md) and the manual [flashing procedure](FLASHING.md).
