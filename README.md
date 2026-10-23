# Daisy Seed3 Hardware Diagnostic Suite

Standalone diagnostics for the **Electro-Smith Seed3 Desktop Development Kit**:
C++ firmware and a Windows application (Python/PySide6), communicating over USB CDC
through the carrier's **J7** connector. The GUI and documentation are in English.

> **Validation:** ARM builds and automated software/simulation tests pass.
> Hardware tests **H1–H10 passed on 17 October 2026**, with H3 shortened to about
> three minutes. Some results are operator reports rather than recorded measurements.
> H11 (a second Windows PC without Python) is still open. See the [test report](docs/TEST_REPORT.md).

![Diagnostic GUI in simulation mode](docs/images/gui-simulation.png)

## Features

| Area | Firmware | Windows GUI |
| --- | --- | --- |
| 16 buttons S1–S16 | libDaisy debounce, held state, press counts | Two rows of eight, highlighting and counts |
| 16 LEDs D1–D16 | Off / on / individual / chase / follow buttons, brightness | Commanded state and controls |
| 8 knobs VR1–VR8 | Normalized value and raw ADC value | Knobs, percentage, min/max |
| SW17 / SW18 | Two-position / three-position switches; SW18 debounce | Position display |
| microSD | Card detection; optional **read-only** filesystem test | No card / detected / readable / error |
| Audio inputs L/R | Input jack detection only; outputs have no detection | Input connector indicators |
| USB | DDP v1: handshake, 10–100 Hz state stream, CRC, keepalive | Discovery, timeouts, reconnection |
| Simulation | — | Device model speaking the same protocol |

Audio processing, DSP, MIDI DIN, USB-MIDI, USB host, CV, and gate functions are
marked **Not implemented** or **N/I**. Displayed LED states are targets, not optical
or electrical feedback from the LEDs.

## Binary downloads

The [Hardware diagnostics workflow](https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics/actions/workflows/diagnostics.yml)
builds firmware (`DaisyDiagnostic.bin`, `.elf`) and Windows (`DaisyDiagnostic.exe`).
Open a successful run and download its two ZIP files under **Artifacts**; each
includes `SHA256SUMS`. Access to this private repository is required. Actions
artifacts expire according to their retention period. Releases are separate,
versioned snapshots and are not created automatically.

## Quick start

```bash
git clone https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics.git
cd Daisy-Seed3-Desktop-Diagnostics
git submodule update --init libDaisy
git -C libDaisy submodule update --init --recursive --jobs 4

# Firmware: Windows / Git Bash
bash scripts/install-toolchain-windows.sh
bash scripts/build-firmware.sh
# -> firmware/build/DaisyDiagnostic.bin

# Python application and tests, from the repository root
python -m pip install -r windows/requirements.txt
python -m pytest tests/python
```

Start the GUI on Windows with `windows\run.cmd --sim` (simulation) or
`windows\run.cmd` (hardware). Build the EXE with `windows\build_exe.cmd`.
Host firmware tests: `make -C firmware test test-sanitize` (Linux/g++), or
`scripts\run-host-tests-msvc.cmd` (Windows/MSVC).

## Layout

```text
firmware/   C++ firmware, hardware glue, portable application logic
windows/    PySide6 application and EXE packaging
protocol/   DDP specification, C++ framing, shared test vectors
tests/      C++ host tests and Python/protocol/session/GUI tests
scripts/    Toolchain installers, builds, binary checks, MSVC tests
docs/       Setup, operation, firmware details, validation, handover
libDaisy/   Pinned official hardware-library submodule
```

## Documentation

* [Installation and usage](docs/INSTALLATION_AND_USAGE.md)
* [Build and dependencies](docs/BUILD.md)
* [Flashing](docs/FLASHING.md)
* [Firmware architecture and limits](docs/FIRMWARE.md)
* [DDP v1 protocol](protocol/PROTOCOL.md)
* [Software and hardware test report](docs/TEST_REPORT.md)
* [Technical handover](docs/HANDOVER.md)
* [Repository migration](docs/MIGRATION.md)

[Toy Piano](https://github.com/sscheidl/Daisy-Seed) is developed separately. This
repository needs neither its source code nor DaisySP.
