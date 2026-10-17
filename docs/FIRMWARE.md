# Diagnostic firmware — configuration, dependencies, architecture

## Target configuration

| Item | Value |
| --- | --- |
| Hardware | Electro-Smith **Seed3 Desktop Development Kit**, `daisy::desktop_devkit::Hardware` |
| Application | `APP_TYPE=BOOT_SRAM`; execution at AXI SRAM `0x24000000`, image in QSPI `0x90040000` |
| Bootloader | Daisy **v6.x External**, intended `dsy_bootloader_v6_4-extdfu-2000ms.bin`; J7 DFU, two-second window; never installed automatically |
| USB | `UsbHandle::FS_EXTERNAL`: OTG-HS in FS mode, D29/D30, carrier J7; CDC-ACM, VID `0483`, PID `5740` |
| Control rate | Audio callback at 48 kHz / 48 samples = **1 kHz**; audio outputs silent |
| Compiler | xPack GCC **13.2.1-1.1**, `13.2.1 20231009`, GNU++17, `-O2`, Cortex-M7, FPv5-D16, hard float |
| Recorded memory, 17 October 2026 | SRAM 122,152 / 480 KiB (24.9%); DTCM 71,808 / 128 KiB; SDRAM 632 bytes |

## Pinned dependencies

| Component | Version / source |
| --- | --- |
| libDaisy | Unmodified submodule `f715e4875b2d28445d0c11a0a17f064a248f69d0` (v9.0.0-5) |
| STM32H7xx HAL | libDaisy submodule `404a70d4c19c124636c78801ff7c0dbc87bc4256` |
| STM32 USB Device Library | libDaisy submodule `7b5e6886d2f11ad15d2b46364e8a96984358f639` |
| FatFs | Included under `Middlewares/Third_Party/FatFs`; `USE_FATFS=1`, custom protected disk driver instead of `SD_Driver` |
| DaisySP | Not required |
| Windows toolchain | xPack ARM GCC 13.2.1-1.1 win32-x64, SHA-256 `56b18ccb…29e4f`; Windows Build Tools 4.4.1-3, Make 4.4.1, SHA-256 `113d4dfd…1d218` |
| Linux CI toolchain | xPack ARM GCC 13.2.1-1.1 linux-x64 |

Submodules are initialized at their pinned commits, without `--remote`.
The installers contain full archive checksums. See [BUILD.md](BUILD.md).

## Building and checks

```bash
git submodule update --init libDaisy
git -C libDaisy submodule update --init --recursive --jobs 4
bash scripts/install-toolchain-windows.sh  # Windows / Git Bash
bash scripts/build-firmware.sh
# -> firmware/build/DaisyDiagnostic.bin
make -C firmware test test-sanitize       # Linux / g++
```

Windows host-test alternative: `scripts\run-host-tests-msvc.cmd` (`/W4 /WX`).
`make check` checks BOOT_SRAM vectors using `scripts/check-firmware.py` and checks
linked symbols using `arm-none-eabi-nm`. It rejects write, erase, and lock paths:
SDMMC CMD24/25, CMD32/33/38, CMD42, HAL SD writers, BSP/disk writers, and FatFs APIs
including `f_open`, `f_write`, and `f_mkfs`. Required symbols (`RoRead`, `RoWrite`,
`f_mount`, `f_readdir`, and `SDMMC_CmdReadSingleBlock`) prevent a vacuous pass.
A reachable injected `f_open(..., FA_WRITE)` was confirmed to fail this check.

## Architecture

```text
firmware/src/main.cpp      Hardware glue: audio callback, protected CDC sender,
                          SD driver, board adapter
firmware/src/diag_app.*    Portable main loop: receive/commands, scheduling,
                          double-buffered output, statistics, LEDs
firmware/src/diag_core.*   Buttons, SW18 debounce, LED modes, session, formatting
firmware/src/ring_buffer.h Lock-free USB ISR → main-loop receive ring
protocol/ddp.*            Frames, CRC, parsing, bounded writing
```

* **Audio callback (1 kHz, priority 0):** update all controls, track 16 button
  edges, debounce SW18, and snapshot digital inputs. No USB, SD, or LED transfers;
  audio outputs are zero.
* **USB receive (OTG-HS, priority 1):** copy bytes into a lock-free 1 KiB ring;
  never parse or send from the ISR.
* **Main loop (`diag::App::Step`, host-tested):** parse commands, copy digital
  inputs with interrupts briefly masked, read `pot[i].Value()` and ADC mux values,
  update LEDs only on change and at most every 10 ms, format and send frames,
  and blink the USR LED. `UpdateLeds()` may wait for previous DMA completion.

## Design decisions

* **UsbHandle instead of Logger:** bidirectional CDC without the logger's blocking
  transmit behavior. See [PROTOCOL.md](../protocol/PROTOCOL.md).
* **Protected transmit:** libDaisy's `CDC_Transmit_HS()` dereferences `pClassData`
  without checking it; USB reset can free it. Readiness checks and submission run
  together with USB priority 1 masked by `BASEPRI`. Audio priority 0 remains enabled.
  The guard is reviewed; basic USB operation has hardware evidence, but reset-race
  stress timing has not been measured.
* **Two output buffers:** the CDC class owns submitted bytes until completion.
  New frames collect in the other buffer. BYE is acknowledged; new HELLO drops
  unsent data from the previous session.
* **Host supervision:** after three seconds of silence, only HELLO restarts
  streaming. Requested SD-test time is excluded because queued PINGs are processed later.
* **Interrupt priorities:** libDaisy defaults USB and audio DMA to 0. Firmware
  lowers OTG-HS to 1 so audio can preempt it.
* **Buttons:** held between RisingEdge and FallingEdge. A repeated rising edge
  after a short contact dropout does not count twice. Modulo-256 press counts
  retain short presses between state frames.
* **SW18:** accept a position after eight identical reads (8 ms).
* **Read-only microSD:** custom FatFs driver always reports `STA_PROTECT`;
  its write entry returns `RES_WRPRT` without touching the card. Each DMA read
  operation is limited to 1 s; the test has a 5 s read budget plus initialization.
  Each test deinitializes the SD interface and relinks the driver, resetting
  FatFs' initialization flag after swaps or failed attempts. Read errors abort DMA.
  Cache clean/invalidate operations surround DMA.
* **SDRAM:** BOOT_SRAM places ordinary BSS in DTCM, which SDMMC1 IDMA cannot reach.
  `FATFS` (including its sector window) and `DIR` use `.sdram_bss`, initialized
  after Seed setup; no static constructor writes there before SDRAM setup.
* **Knobs:** unmodified libDaisy normalized values plus 16-bit raw mux values;
  no application-specific calibration.

## Known firmware limits

* SD tests block the main loop and stream. Reads have a 5 s budget (plus an
  in-flight operation); `HAL_SD_Init` is bounded only by HAL's own timeouts.
  The host allows 20 s for requested tests, otherwise 1.5 s. A basic read test
  passed as an operator test; exceptional cards and timeout behavior remain unmeasured.
* libDaisy distinguishes `v6_0` and `v6_1` or newer, not specifically v6.4.
* The unmodified LED driver can hang after a failed `TransmitDma()` start.
* `Hardware::Init()` also configures unused MIDI UART, DAC, gate inputs, and CV ADC.

See [TEST_REPORT.md](TEST_REPORT.md) for hardware-test scope and open measurements.
