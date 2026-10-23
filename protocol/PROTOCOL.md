# Daisy Diagnostic Protocol (DDP) — Version 1

Bidirectional text protocol between Seed3 diagnostic firmware and the Windows
application. Transport: **USB CDC (virtual COM port)** through **J7**, the external
USB-C connector on the Desktop Dev Kit (OTG-HS peripheral in FS mode, D29/D30).
Baud rate and modem handshake lines have no meaning for USB CDC.

Reference implementations: [`ddp.h`](ddp.h)/[`ddp.cpp`](ddp.cpp), portable C++17
without libDaisy, and [`protocol.py`](../windows/daisy_diag/protocol.py) on the host.
[`vectors.txt`](vectors.txt) contains shared test vectors.

## Why not the libDaisy logger?

`daisy::Logger<LOGGER_EXTERNAL>` at libDaisy `f715e48` can transmit (`Print`,
`PrintLine`) but has no receive API. `TransmitSync()` waits for the host after the
first packets. The firmware therefore uses `UsbHandle` directly with
`Init(FS_EXTERNAL)`, `SetReceiveCallback(..., FS_EXTERNAL)`, and nonblocking
`TransmitExternal()`. It uses the same CDC class; no custom CDC implementation is needed.

Default USB identity: VID `0x0483`, PID `0x5740`, product **Daisy Seed External**.
Other STM32 devices share this identity, so a port becomes a diagnostic device only
after a successful HELLO handshake.

## Frame format

```text
$<body>*<CRC>\n
```

* `body`: printable ASCII `0x20..0x7E`, excluding `$` and `*`; maximum **400 bytes**.
* `CRC`: CRC-16/CCITT-FALSE over the body bytes: polynomial `0x1021`, initial value
  `0xFFFF`, no reflection, no final XOR. Encode as four uppercase hexadecimal digits.
  Check value: `CRC("123456789") = 29B1`.
* A `\r` before `\n` is accepted. Receivers also accept lowercase CRC digits.

Receiver resynchronization rules:

1. Discard bytes outside a frame until `$` appears.
2. `$` inside a frame discards the incomplete frame and starts a new one.
3. Invalid characters, a missing `*`, invalid/wrong CRC, and a body longer than
   400 bytes discard the frame and increment the error counters.

This handles truncated frames after disconnection, buffered old data when reopening
a port, and noise bytes.

## Message structure

```text
TYPE key=value key=value ...
```

`TYPE` is uppercase. Keys are lowercase; values contain neither spaces nor `=`.
Lists use commas. **Unknown keys are ignored**; the host also ignores unknown
message types. Firmware answers unknown commands with `ERR`. New optional fields
therefore do not require a protocol version change; incompatible changes increment `proto`.

## Connection sequence

```text
Host                                    Seed3
 | -- $HELLO proto=1*... ------------>  | enable streaming, start host timer
 | <- $HELLO proto=1 fw=... ----------  |
 | <- $ST ... (configured rate) ------  |
 | <- $SYS ... (1 Hz) ----------------  |
 | -- $PING n=17*... (2 Hz) ----------> |
 | <- $PONG n=17*... -----------------  |
 | -- $LED m=CHASE*... --------------> |
 | <- $ACK c=LED m=CHASE ... ---------  |
```

* Streaming starts after HELLO and continues while a valid host frame arrives
  within **3 s**. After timeout or BYE, only a new HELLO restarts streaming; PING
  still receives PONG but does not restart it. Time spent in a requested SD test
  does not count as host silence. An arbitrary terminal gets no unsolicited stream.
* BYE receives `ACK c=BYE`. A new HELLO discards pending output from the previous session.
* The host sends PING every 0.5 s. It disconnects after **1.5 s** without a valid
  frame or when the port disappears, then searches every second and repeats HELLO.
  An explicitly requested SD test gets a separate timeout of up to **20 s**.
* J7 powers the kit; unplugging it also restarts the firmware. Reconnection starts
  with HELLO.
* USB sends are nonblocking. While CDC holds one buffer, the next frames collect
  in a second buffer. New frames that do not fit are dropped and counted in `SYS txdrop`.

## Host → firmware

| Command | Fields | Response |
| --- | --- | --- |
| `HELLO` | `proto=1` | `HELLO ...`, then streaming |
| `PING` | `n=<u32>` | `PONG n=<u32>` |
| `GET` | — | Immediate `ST` and `SYS` in an active session |
| `RATE` | `hz=10..100` | `ACK c=RATE hz=<n>` |
| `LED` | `m=OFF\|ON\|MASK\|CHASE\|FOLLOW`, optional `mask=<hex4>`, `br=0..100`, `ms=20..2000` | `ACK c=LED m=... mask=... br=... ms=...` |
| `SDTEST` | — | `SD ...` (read-only test) |
| `BYE` | — | `ACK c=BYE`, streaming off |

Errors: `ERR c=<command> e=<code>`, where `UNKNOWN` means unknown command, `ARG`
means a missing/invalid field (including an overlong optional value; the whole
command is rejected), and `PROTO` means unsupported protocol version. Unsigned
numbers contain digits only, without signs or underscores; the host rejects state
values outside the specified ranges. ERR is generated only for complete frames
with a valid CRC.

| LED mode | Meaning |
| --- | --- |
| `OFF` | All 16 LEDs off |
| `ON` | All 16 LEDs on |
| `MASK` | Individual LEDs: bit 0 = D1 … bit 15 = D16 (`mask=8001` selects D1 and D16) |
| `CHASE` | D1 → D16, one step every `ms` (default 120 ms) |
| `FOLLOW` | LED follows its button's held state; default after startup |

`br` sets PWM brightness in percent (default 100). LEDs have **no electrical
feedback**: ST field `l` is the commanded state, not proof of actual light output.

## Firmware → host

### HELLO

```text
HELLO proto=1 fw=0.1.0 app=DaisyDiagnostic dev=seed3-desktop boot=BOOT_SRAM bl=v6_1 libdaisy=f715e48 caps=btn,pot,potraw,sw17,sw18,sd,sdread,jack,led
```

`bl` is the bootloader version recognized by libDaisy: `v6_1` means v6.1 or newer;
other values are `v6_0`, `LT_v6_0`, and `NONE`.

### ST — complete state

```text
ST n=1234 t=56789 b=0001 pc=01000000000000000000000000000000 p=0,10000,5000,0,0,0,0,0 r=0,65535,32768,0,0,0,0,0 s17=U s18=C sd=0 jl=0 jr=1 lm=FOLLOW l=0001 br=100
```

| Field | Meaning |
| --- | --- |
| `n` | Sequence number (u32); gaps indicate lost frames |
| `t` | Firmware uptime in milliseconds (u32) |
| `b` | Debounced button mask: bit 0 = S1 … bit 15 = S16 |
| `pc` | 16 press counts, two hex digits each, modulo 256, S1 first; retains short presses between frames |
| `p` | VR1…VR8 normalized values: `0..10000` = `0.0000..1.0000` |
| `r` | VR1…VR8 raw ADC values `0..65535`, mux channels 0…7 |
| `s17` | SW17: `U` or `D`; libDaisy `tog_sw17.Pressed()` maps to `U` |
| `s18` | SW18: `U`, `C`, or `D`; libDaisy `POS_UP`, `POS_CENTER`, `POS_DOWN` |
| `sd` | microSD detection: `1` = card detected |
| `jl`, `jr` | Left/right audio input plug detected (`1`); outputs have no plug detection |
| `lm` | Active LED mode |
| `l` | Commanded LED mask, bit 0 = D1 |
| `br` | LED brightness, `0..100` percent |

Periodic rate is selected by RATE (default **50 Hz**). Digital input changes
trigger additional frames with a minimum 10 ms interval.

### SYS — firmware diagnostics, 1 Hz

```text
SYS up=123 cbhz=1000 txok=6150 txbusy=3 txdrop=0 rxok=250 rxbad=0 host=1 rate=50
```

`cbhz` is measured control updates per second (target 1000, from 48 kHz / 48 samples).
`rxbad` reports discarded receive data/frames. Remaining fields expose uptime,
transmit/receive counters, host-active state, and configured rate.

### SD — SDTEST result

```text
SD st=MOUNTED res=0 fs=FAT32 mb=30436 ent=12
SD st=NONE res=-1
SD st=ERROR res=13
```

| `st` | Meaning |
| --- | --- |
| `NONE` | No card detected; no access attempted |
| `MOUNTED` | Filesystem mounted and root directory read: `ent` entries, capped at 1000 |
| `ERROR` | Access failed; `res` is FatFs FRESULT, e.g. `3` = FR_NOT_READY, `13` = FR_NO_FILESYSTEM |

The test uses only `f_mount`, `f_opendir`, `f_readdir`, `f_closedir`, and unmounting,
over a custom write-protected driver (`STA_PROTECT`). It does not write, format,
or modify the card. The build rejects SD write/erase/lock commands at SDMMC, HAL,
driver, and FatFs levels; see [FIRMWARE.md](../docs/FIRMWARE.md).

Streaming pauses during the test (typically < 0.5 s). Reads have a five-second
budget plus initialization; the host tolerates up to 20 s. Press counts retain
button presses during the pause. Each test reinitializes the card, supporting swaps.

### ACK, ERR, PONG

See the host-to-firmware command table above.

## Versioning

`proto=1` identifies this specification. A host receiving another major version
shows **Incompatible protocol** and sends no control commands.
