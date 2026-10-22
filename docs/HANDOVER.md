# Technical handover — Daisy Seed3 Hardware Diagnostic Suite

> **0.2.0 reader extension:** the separate writable firmware, GUI/session changes,
> software evidence, open hardware checks and independent-review targets are in
> [SD_CARD_READER_REVIEW.md](SD_CARD_READER_REVIEW.md). The H1–H10 results in this
> imported handover concern 0.1.0 and do not validate the reader implementation.

> Imported from the original repository and updated with hardware results.
> See [MIGRATION.md](MIGRATION.md) for repository history and [TEST_REPORT.md](TEST_REPORT.md)
> for the exact evidence behind each result.

Status: 17 October 2026; firmware/application 0.1.0, DDP v1, pinned libDaisy f715e48.
The review-fix branch was `fix/codex-review-findings`; section 9 maps the findings
against `6f709ec` to their corrections. The GUI and current documentation are English.

Firmware and Windows application are implemented; ARM cross-build and automated
software/simulation tests pass. **H1–H10 passed on hardware; H3 was shortened to
about three minutes and some results are operator reports. H11 remains open.**
Earlier design claims came from code, libDaisy, and official documentation;
subsequent hardware evidence is listed separately in the test report.

## 1. Implemented features

### Firmware (`firmware`, C++17, libDaisy f715e48, BOOT_SRAM)

* Official `daisy::desktop_devkit::Hardware`, without custom pin mapping: 16
  debounced buttons with held states and press counts, eight normalized/raw ADC
  knobs, SW17/SW18 (additional SW18 debounce), microSD and audio input jack detection.
* 1 kHz control sampling in the audio callback (48 kHz / 48); audio outputs silent.
* Sixteen PCA9685 LEDs: off, on, individual mask, chase, and follow buttons
  (default); 0–100% brightness.
* Optional read-only SD mount/root-directory test over a custom protected driver.
  The build rejects SD write/erase/lock commands at SDMMC, HAL, driver, and FatFs levels.
* Nonblocking J7 USB CDC: ISR → receive ring → main loop.
* DDP v1 CRC frames; HELLO/version handshake; full state stream at 10–100 Hz
  (default 50), digital-change frames at least 10 ms apart, 1 Hz statistics,
  HELLO/PING/GET/RATE/LED/SDTEST/BYE; three-second host supervision.
* USR LED: slow while waiting, fast while connected.

### Windows application (`windows`, Python 3.12, PySide6 6.8.3, pyserial 3.5)

* Board view based on photo/pinout: buttons, LED targets, knobs with min/max,
  switches, microSD, input jack detection, J7, and marked unimplemented areas.
* VID/PID discovery plus HELLO, retries, PING keepalive, 1.5 s timeout,
  reconnection, errors/loss counters, round-trip time, and version information.
* LED and SD controls, raw/normalized knob table, press counts, event log.
* Clearly marked simulator speaking DDP, with unplug/freeze/corrupt-frame and
  slow-SD scenarios. It is a model, not hardware emulation.
* Dark instrument-style GUI: charcoal/gray panels, red LEDs, green/red statuses,
  yellow simulation banner; no menus. EXE packaged by PyInstaller.

## 2. Deliberately not implemented

Audio input/output processing (only input jack detection), DSP, MIDI DIN,
USB-MIDI, USB host, CV input/output, and gate input are labeled **Not implemented**
or **N/I**. Audio outputs have no jack detection. USB-host capability and electrical
requirements have not been verified. No SD writes/formatting and no automatic
bootloader installation are implemented.

## 3. Validation results

| Check | Result |
| --- | --- |
| ARM cross-build, xPack GCC 13.2.1-1.1 | Passed, reproducible BIN |
| BOOT_SRAM vectors and protected SD symbol check | Passed |
| C++ core/protocol host tests, MSVC `/W4 /WX` | 339 checks passed |
| C++ main-loop host tests | 635 checks passed |
| Python tests | 162 on the correction branch; 167 with design tests and English UI |
| Injected reachable `f_open(..., FA_WRITE)` | Correctly rejected by the symbol check |
| GUI/EXE simulation startup | Passed |
| g++, ASan/UBSan, Linux ARM build, Windows tests/EXE | Covered by the independent GitHub workflow |
| Hardware, 17 October 2026 | H1–H10 passed (H3 shortened); H11 open |

Details and limitations: [TEST_REPORT.md](TEST_REPORT.md).

## 4. Known issues and risks

1. **Some hardware evidence is operator-reported.** Protocol recordings cover
   flashing, J7 enumeration, handshake, about three minutes of rates/errors, and
   VR1. Other controls, SD, input jack detection, and unplugging were operator
   tests. Ten-minute stability, idle knob noise, and special SD cases remain unmeasured.
2. **libDaisy CDC transmit has no null check.** Readiness checks and transfer
   submission share a BASEPRI-protected section masking USB priority 1. The guard
   is source-reviewed; basic USB passed, but reset-race stress timing is unmeasured.
   Recheck when updating libDaisy.
3. **SD tests block the main loop.** Reads: 1 s per operation and 5 s budget;
   `HAL_SD_Init` has HAL timeouts only. Host tolerance is 20 s; requested SD time
   is excluded from firmware host silence. Basic SD read passed an operator test;
   exceptional cards and timeout behavior remain unmeasured.
4. **Shared USB ID 0483:5740.** Other STM32 devices receive HELLO during discovery;
   failed handshakes time out after 1 s and back off for 5 s. Use `--port` to restrict it.
5. **Bootloader version granularity:** `v6_1` means v6.1 or newer; v6.4 cannot be
   identified specifically through libDaisy.
6. **LED driver:** a failed DMA start may make the next buffer swap wait forever.
   Failure handling still needs hardware validation.
7. **Host closes without BYE:** firmware sends for up to 3 s into an unread
   endpoint; drops are counted. New HELLO discards pending old data; already
   submitted packets may remain buffered. Recorded hardware behavior included
   117 drops after closing without BYE.
8. **Busy polling main loop:** functional, but not optimized for power consumption.
9. **Unsigned EXE:** Windows SmartScreen may warn. Original package was about
   46.9 MB including Qt; package size varies by build.
10. **FatFs is not globally `_FS_READONLY`.** Changing that would alter FATFS
    layout relative to precompiled libDaisy. Protection combines the call path,
    driver `STA_PROTECT`/`RES_WRPRT`, and linked-symbol checks.
11. **Host tests do not execute hardware glue.** `main.cpp` is compiled; portable
    `diag_app` executes with fake board/USB. Hardware results do not establish
    all timing and failure cases.

## 5. Firmware and bootloader compatibility

| Item | Value |
| --- | --- |
| Application | BOOT_SRAM; `STM32H750IB_sram.lds`; QSPI image `0x90040000`, SRAM execution `0x24000000` |
| Required bootloader | Daisy v6.x External, intended `dsy_bootloader_v6_4-extdfu-2000ms.bin`, installed separately |
| Flash route | J7 → RESET, then BOOT within 2 s → Web Programmer Custom, or `dfu-util -a 0 -s 0x90040000:leave -D DaisyDiagnostic.bin -d ,0483:df11` |
| Incompatible route | No Daisy bootloader (ROM DFU at `0x08000000`), or bootloader older than v6.0 |
| v6.x internal DFU | Expected to run; flashing uses Seed3 module USB-C; not verified |
| Runtime USB | J7 CDC, OTG-HS/FS PHY, D29/D30, VID 0483 PID 5740, product Daisy Seed External |
| Toy Piano | Separate application, interchangeable through the same bootloader |

## 6. Build artifacts

Local output is under ignored `release/`; CI provides workflow artifacts.
Recorded correction-branch Windows builds:

| File | Size | SHA-256 |
| --- | --- | --- |
| `DaisyDiagnostic.bin` | 122,152 bytes | `5246380984e199368a30c545b45d1263493903ad02a864bde2f04f17c0d15dc0` |
| `DaisyDiagnostic.elf` | 2,170,824 bytes | `ba9f67c0373b6382204877ed53c293c7668c5d1db6972362a943e53f9fbd5ace` |
| `DaisyDiagnostic.exe` | Build-dependent | See the artifact's SHA256SUMS |

Linux CI uses the same GCC release. ELF checksums may differ because of debug
paths. PyInstaller EXEs are not bit-reproducible. The tested BIN matches release
v0.1.0; UI translation does not change firmware.

## 7. Review guidance

1. Compare `protocol/PROTOCOL.md`, `ddp.cpp`, and `windows/daisy_diag/protocol.py`.
2. Review `main.cpp`: callback/main-loop sharing, BASEPRI CDC guard, protected SD
   driver, DMA/cache handling, time limits, reinitialization, SDRAM, and IRQ priorities.
3. Review `diag_app.*`, `ring_buffer.h`, and `diag_core.*`: command validation,
   scheduling, two buffers, host timeout including tick wrap, and statistics.
4. Review `session.py`: handshake, timeout, SD tolerance, backoff, and reconnection.
5. Compare simulator behavior with the firmware model and its limitations.
6. Run:

   ```bash
   bash scripts/build-firmware.sh
   make -C firmware test test-sanitize
   python -m pytest tests/python -v
   ```

## 8. Hardware test procedure

Preparation: external v6.x bootloader installed; otherwise see [FLASHING.md](FLASHING.md).
Start with audio inputs unplugged and no SD card. This procedure also describes
retesting; recorded results do not claim every subcase below was measured.

1. **H1, flashing:** J7, RESET, BOOT within 2 s, then program `DaisyDiagnostic.bin`.
   Expect slow USR blinking (1 Hz); S1 should light D1 even without the host.
2. **H2, connection:** start the EXE in Hardware (USB). Expect Connected within
   about 2 s, DaisyDiagnostic 0.1.0, DDP v1, BOOT_SRAM / v6_1, and fast USR blinking.
   Device Manager should show VID_0483/PID_5740. Record the port and log on failure.
3. **H3, stability:** run for ten minutes; expect 49–50 Hz state, 1000 Hz control
   (±1), zero frame errors/loss and TX drops. The existing run covered about three minutes.
4. **H4, buttons:** press all S1–S16 separately; corresponding highlight, count +1,
   and physical LED. Verify short taps and no duplicate counts.
5. **H5, knobs:** sweep VR1–VR8 independently; only the matching channel should
   change, with about 0–100% endpoints. Record idle noise and min/max; target < 0.5% noise.
6. **H6, switches:** move SW17/SW18 through all positions and record physical U/C/D
   direction. A direction-label difference is a documentation issue to record.
7. **H7, LEDs:** All on/off, every Individual LED, Chase, brightness 10/50/100%.
   Verify visually: software cannot establish actual light output.
8. **H8, microSD:** FAT32 insertion → Card detected; read test → Filesystem readable
   with plausible size/count. Removal → No card. Also test exFAT, no filesystem,
   and removal during access. The test is read-only; backups of unfamiliar cards
   are nevertheless advisable.
9. **H9, audio inputs:** plug left then right; record indicator side/polarity.
   Audio outputs have no plug detection.
10. **H10, USB:** close/reopen the host; unplug/replug J7; expect reconnection and
    an incremented reconnection count.
11. Record results, observations, and firmware SHA-256 in [TEST_REPORT.md](TEST_REPORT.md).
    **H11:** repeat EXE startup on a second Windows 11 PC without Python.

## 9. Review of 6f709ec: findings and fixes

| Severity | Finding | Fix | Evidence |
| --- | --- | --- | --- |
| P1 | Reset between CDC check and send | BASEPRI guards check and submission together | Hardware-glue source review |
| P2 | SD not reinitialized after swap/failure | Relink custom driver for each test after HAL_SD_DeInit | Reviewed FatFs initialization/linking code |
| P2 | Incomplete symbol check (`f_open`) | Checks all layers plus required symbols; protected driver | Injected writer rejected |
| P3 | No handshake-I/O backoff | Back off every failed handshake for 5 s; try next port after write failure | `test_handshake_io_error_backs_off_and_tries_next_port[write/read]` |
| P2 | Incorrect 35 s SD assumption | Bound firmware reads; host timeout 20 s; correct documentation | `test_slow_sd_card_does_not_drop_connection` |
| P2 | Simulator processes commands while blocked | Queue bytes like the 1 KiB receive ring, including overflow | `test_commands_wait_while_firmware_is_blocked`, `test_rx_ring_overflow_while_blocked_is_counted` |
| P2 | BYE ACK discarded | Retain ACK; clear stale pending output on new HELLO | `TestByeIsAcknowledged`, `TestNewSessionDropsStaleOutput` |
| P2 | Sequence gaps ≥ 1000 ignored | Count gaps, recognize u32 wrap, log backwards jumps | `test_large_sequence_gap_is_counted`, `test_sequence_gap_rules` |
| P3 | PING revives expired stream | Timeout latches until new HELLO in firmware and simulator | `TestSession`, `TestTimeoutNeedsNewHello`, `test_ping_after_timeout_does_not_restart_stream` |
| P3 | Overlong optional LED fields treated as absent | LookupField distinguishes Missing/TooLong; reject command | `TestSession`, `TestFields`, `TestLeds` |
| P3 | Permissive Python numeric fields | Strict digits/hex and bounds for state, SD, SYS | Additional invalid-state cases |
| P3 | Simulator zero clock start | Explicit None check for boot time | `test_simulator_clock_starting_at_zero` |

An additional interaction was fixed: with latched host timeout, a long SD test
would terminate streaming before queued PINGs were processed. Requested SD-test
duration is excluded from silence (`TestBlockingSdTestKeepsStream` and the slow-SD test).

Main-loop regression coverage includes handshake, rates/sequences, change frames,
BYE/timeout, USB not ready/busy, output ownership and overflow, stale-session data,
receive overflow/resynchronization, ring index wrap/full state, LED rate limiting,
and SD requests. `make test-sanitize` requires g++ and runs in GitHub CI.
