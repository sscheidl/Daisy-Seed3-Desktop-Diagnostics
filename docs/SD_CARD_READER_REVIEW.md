# SD card reader — independent review handover

Prepared 22 October 2026. Implementation 0.2.0; **not hardware validated**.
The implementation branch is `codex/sd-card-reader`, based on English-language
PR [#2](https://github.com/sscheidl/Daisy-Seed3-Desktop-Diagnostics/pull/2).
Keep that dependency until it merges, then retarget the reader PR to main after
checking its diff. Do not merge the reader implementation before Claude's review
and explicit merge approval.

## Architecture and changed files

| Files | Responsibility |
| --- | --- |
| `firmware/src/card_reader.*` | Exclusive ownership and quarantine; no HAL or filesystem dependency |
| `firmware/src/msc_bot.*` | Actual portable CBW/data/CSW and SCSI processing; fake block tests use this code |
| `firmware/src/reader_usb.*` | Composite descriptors, CDC delegation, MSC event mailbox, generation-guarded endpoint submissions |
| `firmware/src/reader_ctlreq.c` | Recompile pinned core control handling with interface 2 admitted; original submodule unmodified |
| `firmware/src/main.cpp` | Polled SD block adapter and wiring; original protected FatFs driver retained |
| `firmware/src/diag_core.*`, `diag_app.*` | Capability, reader commands, ordered command execution, SDTEST gating, periodic status |
| `windows/daisy_diag/{protocol,session,simulator}.py`, GUI | Parse status, capability gating, timeouts, explicit handover controls and state-only simulation |
| `firmware/Makefile`, build scripts, CI | Separate objects/images, separate symbol policies, three checked artifacts |
| `tests/firmware/`, `tests/python/` | Ownership, block transfers, transport, USB glue, protocol, session, GUI regression tests |

The pinned `UsbHandle` only initializes CDC. The reader therefore registers one
project composite class using the pinned core and delegates CDC to the unchanged
class. `pClassData` remains CDC's data throughout; MSC never swaps it. There is no
global composite ABI define applied to libDaisy.

## USB layout and ownership

J7 is OTG-HS operated at Full Speed with its internal PHY. Interfaces 0/1 are CDC
(bulk 0x01/0x81, notification 0x82); interface 2 is MSC/SCSI-transparent/BOT
(bulk 0x03/0x83, 64-byte packets). Configuration is 98 bytes, with a CDC IAD and
device class EF/02/01. The reader retains the existing development VID/PID but
uses bcdDevice 3.00 and an `A1` hexadecimal serial suffix to distinguish its Windows
instance from the CDC-only image. The physical Windows binding is untested.
The FIFO allocation is RX 256 words, TX0 64, TX1 128, TX2 16, TX3 128: 592 words
within the OTG-HS 1024-word capacity. The descriptor advertises bus power, 500 mA;
actual consumption/enumeration remains a physical acceptance item.

```text
LOCAL --explicit SHARE + successful initialization--> SHARED
            (transient STARTING)
SHARED --host eject + successful sync--> EJECTED --explicit RETURN--> LOCAL
SHARED/STARTING --bus/BOT reset or removal--> INTERRUPTED
STARTING/SHARED --I/O failure--> ERROR
INTERRUPTED/ERROR --explicit acknowledged RETURN--> LOCAL
```

Only LOCAL permits FatFs diagnostics; only SHARED permits MSC block access.
There is no persistent share preference. No BYE, host timeout or serial-port
closure revokes Windows ownership. Return from SHARED is rejected. SCSI START
never enables sharing. PREVENT/ALLOW MEDIUM REMOVAL is respected for host eject.
The firmware completes each block write through card programming before CSW;
there is no firmware write-back cache. SYNCHRONIZE CACHE waits for the card but
does not claim to flush data still held by Windows. Only host eject establishes
EJECTED. Interrupted acknowledgement cannot recover pending writes.

After return the SD interface is closed/deinitialized. Every later protected
test relinks/remounts FatFs; every new share reinitializes and reads card capacity.
Newly shared media report UNIT ATTENTION / MEDIUM CHANGED.

## Interrupts, buffers and reset races

- Audio/control sampling remains priority 0 and performs no SD/USB work.
- USB priority 1 copies or records MSC events only. No SD operation or SCSI parse
  executes in Init/DeInit/Setup/DataIn/DataOut callbacks. CDC retains its existing
  ISR receive ring and protected double-buffer transmitter.
- The main loop consumes MSC events and executes one block at a time. MSC uses
  CPU-polled HAL I/O, not DMA: a dedicated aligned 512-byte bounce buffer can live
  in DTCM and has no DMA cache-maintenance requirement. USB DMA is disabled by
  the pinned HAL setup. MSC RX/TX buffers stay owned until completion.
- Reader SDMMC priority is set to 2 after initialization. Polling SD never masks
  USB, SDMMC or SysTick while waiting. Per HAL transfer timeout is 1 s; subsequent
  programming/state wait is at most 1 s. Card initialization uses pinned HAL
  timeouts and must be measured on exceptional cards.
- Short BASEPRI sections protect USB mailboxes and LL submissions, allowing audio
  priority 0 to run. An atomic generation changes on configuration/deconfiguration
  and BOT reset. Submissions from a main-loop operation interrupted by reset are
  rejected before touching the endpoint. Main-loop unwinding quarantines the card.
- Deferred BOT reset reapplies already-ACKed clear-halt events after resetting
  transport state, so a fast reset + both clears cannot accidentally leave the
  endpoints re-stalled. Recovery requires reset and both endpoint clears.

## SCSI/BOT scope

Implemented: CBW validation, tag/residue/CSW status, all thirteen BOT direction/
length cases, endpoint halt/recovery, INQUIRY and supported VPD page 0, REQUEST
SENSE, TEST UNIT READY, READ CAPACITY(10), READ FORMAT CAPACITIES, MODE SENSE(6/10)
with write cache disabled, READ/WRITE(10), SYNCHRONIZE CACHE(10), PREVENT/ALLOW,
START STOP UNIT and REPORT LUNS. Mismatched/undersized writes never partially
modify the requested blocks. Valid overlength writes process device length and
halt surplus data; read surplus uses residue/halt. Unsupported commands, including
VERIFY/FORMAT/UNMAP and READ/WRITE(16), fail explicitly. No fabricated verification
success. Capacity and LBA are uint32 sectors of 512 bytes; SDUC/greater-than-2-TiB
media are not supported. Each command range is checked before block access.

## Build guarantees

`make -C firmware CARD_READER=0 check` builds the default protected image in
`firmware/build/`. Its full original SDMMC/HAL/BSP/FatFs mutation blacklist is
retained, with positive required symbols to prevent a vacuous check.

`make -C firmware CARD_READER=1 check` builds `DaisyDiagnostic-CardReader` in
`firmware/build/reader/`. Only `HAL_SD_WriteBlocks` and its SDMMC single/multiple
block-write commands are removed from that blacklist and positively required.
FatFs mutation, formatting, generic disk driver, DMA writes, erase and lock
remain forbidden. This image is deliberately write capable; it does not inherit
the protected binary's absence-of-write-code guarantee.

`bash scripts/build-firmware.sh` builds/checks both and generates per-image
SHA256SUMS. CI uploads separate readonly/reader/Windows artifacts, each with source
commit provenance; it creates no release. GUI and firmware use version 0.2.0,
DDP stays v1 with optional `sdmsc` capability and READER messages.

## Software validation

Local tools: pinned ARM GCC 13.2.1, MSVC `/W4 /WX`, and LLVM MinGW clang++
`-Wall -Wextra -Werror`; no hardware connected or accessed by these tests.

Commands:

```text
make -C firmware test
make -C firmware test-sanitize                 # Linux CI, ASan + UBSan
scripts\run-host-tests-msvc.cmd               # Windows alternative
python -m pytest tests/python -v
bash scripts/build-firmware.sh
windows\build_exe.cmd
DaisyDiagnostic.exe --sim --selftest 5
```

Recorded local host results: existing core 339 checks, existing application 635,
reader/BOT 4,631, real composite adapter with HAL stubs 53, reader application
integration passed. The adapter test checks descriptors/dispatch, deferred I/O,
reset during a block read suppressing stale TX, and reset+clear coalescing.
Python suite currently includes 195 cases. Final CI result, exact PR/head and
artifact links are recorded in the PR; do not infer success for a different head.

## Independent review focus for Claude

1. Review actual code independently of this document, especially all transitions
   that can enable writes or local mounts. Check queued DDP command ordering.
2. Check BOT phase cases, residue, short-packet/halt behaviour, CSW ownership and
   reset recovery against USB MSC BOT 1.0, sections 5/6.
3. Check composite descriptor enumeration, Windows CDC binding, serial identity,
   endpoint/FIFO allocation, class request dispatch and the pinned core override.
4. Audit mailbox event ordering, coalesced resets/clears and generation races;
   look for LL submissions after deconfiguration or TX buffer reuse before completion.
5. Audit polled HAL calls, timeout units, card programming completion and error
   propagation. Confirm no blocking SD call can execute with required IRQs masked.
6. Confirm protected-build symbol checks have not weakened and the reader build
   has not gained FatFs writers, DMA writers, erase/lock or formatting paths.
7. Check host state invalidation and pending-action matching, old-firmware gating,
   app closure/reconnect, simulation limitations and misleading success displays.
8. Run tests independently. Report findings with file, line, severity and concrete
   failure scenario; distinguish source/software evidence from physical evidence.

## Open hardware evidence and limitations

All R1–R12 in [SD_CARD_READER.md](SD_CARD_READER.md) are OPEN. In particular, neither
Windows drive enumeration/binding, Explorer write/eject behaviour, card data
integrity, transfer speed, interrupt timing under real traffic, nor surprise
removal recovery has been measured. The Python simulator is not Windows/USB
emulation, and HAL-stub tests do not execute STM32 peripherals. The older 0.1.0
hardware record cannot close any reader acceptance item. No flashing, release
creation or real-card mutation was performed for this implementation.

References: [USB MSC BOT 1.0](https://www.usb.org/sites/default/files/usbmassbulk_10.pdf),
[Windows USB class drivers](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/supported-usb-classes),
and the pinned ST/libDaisy source in the submodule. These describe the design
constraints; they are not evidence that this firmware enumerates on Windows.
