# Test report

## Version 0.2.0 SD card reader

This extension has software-only validation. Both ARM variants build with separate
symbol policies. Host tests execute the actual portable ownership controller,
MSC BOT/SCSI implementation, application command handling and composite USB adapter
(with HAL stubs). Python tests exercise the DDP extension, session and GUI. The
simulator models ownership/status only; it does not create a Windows disk or
execute USB MSC. New code has not been flashed and no physical card was written.
Exact verification commands/results and pending physical checks:
[SD_CARD_READER_REVIEW.md](SD_CARD_READER_REVIEW.md).

> Imported software-validation record, supplemented by hardware results on
> 17 October 2026. See [MIGRATION.md](MIGRATION.md) for repository history.

## A. Software and simulation validation

The original software checks ran on Windows 11 Pro 10.0.26300, branch
`fix/codex-review-findings`, with no Seed3 connected. COM3 (VID `17CC`) belonged to
another device and was correctly ignored. Review fixes are documented in
[HANDOVER.md, section 9](HANDOVER.md#9-review-of-6f709ec-findings-and-fixes).

| # | Check | Command / method | Result |
| --- | --- | --- | --- |
| 1 | Clean ARM cross-build | `bash scripts/build-firmware.sh` | Passed; no warnings from project code with `-Wall` |
| 2 | BOOT_SRAM vectors | `make -C firmware check` | Passed: 122,152 bytes, stack `0x20020000`, reset `0x240003f1` |
| 3 | No SD write/erase/lock path at SDMMC, HAL, BSP, or FatFs level | `make check` and nm | Passed; an injected `f_open(..., FA_WRITE)` was detected |
| 4 | Reproducibility | Two clean builds | Identical SHA-256 |
| 5 | C++ core/protocol/main-loop host tests | `scripts\run-host-tests-msvc.cmd`, MSVC 19.51 `/W4 /WX` | 339 + 635 checks, zero failures |
| 6 | Python tests | `python -m pytest tests/python` | Original correction branch: 162; with GUI design tests and English text: 167 |
| 7 | Source GUI simulation startup | `python -m daisy_diag --sim --selftest 3` | Passed, exit 0 |
| 8 | EXE packaging | `windows\build_exe.cmd`, PyInstaller 6.19.0 | Passed; original EXE about 46.9 MB |
| 9 | Packaged simulation startup | `DaisyDiagnostic.exe --sim --selftest 5` | Passed, exit 0 |
| 10 | Hardware-mode startup without a device | `DaisyDiagnostic.exe --selftest 4` | No crash; expected exit 1 because no device data was received |

Original Python environment: Python 3.12.10, PySide6 6.8.3, pytest 9.0.3.
GUI and EXE startup tests use `QT_QPA_PLATFORM=offscreen`. Windows font lookup uses
`QT_QPA_FONTDIR=C:\Windows\Fonts`. CI runs g++ ASan/UBSan as well as ARM and Windows builds.

The English UI revision was checked separately on 17 October 2026: all 167 Python
tests passed, the source simulation started successfully, and the rebuilt EXE
passed `--sim --selftest 5` (exit 0). Startup with an explicitly nonexistent port
and `--selftest 3` exited with the expected code 1. The simulation screenshot was
regenerated and inspected. No hardware was flashed or exercised for this revision.

### Software coverage

| Area | Coverage | Layer |
| --- | --- | --- |
| Protocol | Shared CRC vectors generated independently using `binascii.crc_hqx`; round trips; noise, truncation, CRC/format/overflow errors, CRLF, lowercase CRC; field parsers; byte-identical ST formatting | C++, Python |
| All 16 buttons | Bit positions; press/release through the host stack and GUI; count wrap; short presses between frames; no duplicate count after contact dropout | C++, Python, GUI |
| All 8 knobs | Field positions; 0/25/100% values; GUI drag and min/max; rounding and NaN/out-of-range inputs | C++, Python, GUI |
| Toggle switches | U/D and U/C/D; SW18 rejects disturbances shorter than eight reads | C++, Python, GUI |
| LEDs | Five modes, all individual LEDs, chase positions, brightness, invalid-command atomicity, board clicks | C++, Python, GUI |
| microSD | No card, detection, readable filesystem, FR_NO_FILESYSTEM, removal; simulated six-second blocking test without disconnection | C++, Python, GUI |
| Connection | Unplug/replug, restart, frozen firmware/timeouts, lost first HELLO, foreign devices, port failures, incompatible protocol, BYE, host timeout | Python, GUI |
| Main loop | Actual portable `diag_app` with fake board/USB; busy endpoint, output ownership, overflow/resync, ring index wrap/full state, LED rate limit, SD requests | C++ |

### What software tests alone do not prove

The Python simulator is a **model**, not the firmware. The portable main loop
`diag_app` executes as actual C++ with fake hardware; `firmware/src/main.cpp`
(audio callback, CDC guard, SD driver, LED hardware) is compiled but not executed
by host tests. ASan/UBSan requires g++ and runs in CI. Simulation does not establish
actual USB-driver behavior, ADC noise, physical debounce, or board timing.

## B. Hardware test on the Seed3 Desktop Dev Kit — 17 October 2026

The flashed `DaisyDiagnostic.bin` had SHA-256:

```text
5246380984e199368a30c545b45d1263493903ad02a864bde2f04f17c0d15dc0
```

It is bit-identical to the CI firmware from `8c0522d` and
[release v0.1.0](https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics/releases/tag/v0.1.0).
Testing used J7 on Windows 11 with the Daisy bootloader (`0483:DF11`), reported by
libDaisy as `v6_1` (v6.1 or newer).

**Recorded** means values were captured through the diagnostic protocol.
**Operator test** means checked on the board and in the Windows application and
reported as successful, without per-control measurements.

| # | Test | Result | Evidence |
| --- | --- | --- | --- |
| H1 | J7 flashing, startup, USR LED | **Passed** | Recorded: bootloader `0483:DF11`, then firmware `0483:5740` on COM14; no reboot loop |
| H2 | COM port, discovery, HELLO, bootloader display | **Passed** | Recorded: firmware 0.1.0, protocol 1, BOOT_SRAM, `bl=v6_1`, libDaisy f715e48 |
| H3 | Control/state rate and frame errors | **Passed, shortened** | About three minutes rather than ten: 1000 Hz control, 50 Hz state, zero frame/content/lost-frame/receive errors |
| H4 | S1–S16 mapping, debounce, counts | **Passed** | Operator test |
| H5 | VR1–VR8 mapping/endpoints | **Passed** | VR1 recorded in both directions: 0.0–100.0%, raw 1–65534; only VR1 changed. VR2–VR8: operator test |
| H6 | SW17/SW18 physical/displayed directions | **Passed** | Operator test |
| H7 | D1–D16 modes and brightness, visually | **Passed** | Operator test |
| H8 | microSD detection/read test | **Passed** | Operator test |
| H9 | Left/right audio input jack detection | **Passed** | Operator test; audio outputs have no jack detection |
| H10 | USB unplug/replug and application close/reopen | **Passed** | Operator test; immediate reconnection after port close/open was also recorded |
| H11 | EXE on a second Windows 11 PC without Python | **Open** | Not performed |

After closing the port without BYE, firmware reported 117 dropped frames (`txdrop`).
This is the documented behavior (up to three seconds of continued transmission),
not a failure; see [HANDOVER.md, risk 7](HANDOVER.md#4-known-issues-and-risks).

Still unmeasured: idle knob noise; ten-minute long-term stability; exFAT, cards
without a filesystem, and card removal during a test (H8 subcases unless covered
by the operator test). The English UI update does not add hardware measurements.

Procedure: [HANDOVER.md, section 8](HANDOVER.md#8-hardware-test-procedure).
