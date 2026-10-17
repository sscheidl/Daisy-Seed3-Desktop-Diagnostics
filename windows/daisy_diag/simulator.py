"""Simulated Seed3 Desktop Dev Kit running the diagnostic firmware's DDP behaviour.

The simulator speaks the real wire protocol (frames with CRC), so the GUI and the
connection logic run exactly the same code paths as with hardware. Every HELLO
from the simulator carries ``sim=1`` and the GUI labels all data as simulated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import protocol as p

HOST_TIMEOUT_S = 3.0
MIN_FRAME_SPACING_S = 0.010


class LinkError(OSError):
    """Raised by links when the device vanished (USB unplugged, port closed)."""


@dataclass
class SimulatedInputs:
    buttons: list[bool] = field(default_factory=lambda: [False] * p.NUM_BUTTONS)
    press_counts: list[int] = field(default_factory=lambda: [0] * p.NUM_BUTTONS)
    pots: list[float] = field(default_factory=lambda: [0.0] * p.NUM_POTS)
    sw17: str = "D"
    sw18: str = "C"
    sd_card: bool = False
    jack_left: bool = False
    jack_right: bool = False

    def copy(self) -> "SimulatedInputs":
        return SimulatedInputs(list(self.buttons), list(self.press_counts), list(self.pots),
                               self.sw17, self.sw18, self.sd_card, self.jack_left,
                               self.jack_right)

    def digital(self) -> tuple:
        return (tuple(self.buttons), tuple(self.press_counts), self.sw17, self.sw18,
                self.sd_card, self.jack_left, self.jack_right)


class SimulatedDevice:
    """Device side of DDP v1, modelled after diagnostics/firmware/src."""

    def __init__(self, protocol_version: int = p.PROTOCOL_VERSION) -> None:
        self.protocol_version = protocol_version
        self.inputs = SimulatedInputs()
        # SD card content for SDTEST: file system type, or None for "no file system".
        self.sd_filesystem: str | None = "FAT32"
        self.sd_size_mb = 30436
        self.sd_entries = 12
        self.led_mode = "FOLLOW"
        self.led_mask = 0
        self.led_brightness = 100
        self.chase_ms = 120
        self.rate_hz = 50
        self.responsive = True  # False: behaves like a hung firmware (no output)
        self.corrupt_next_frame = False
        self.sd_test_duration = 0.0  # seconds the firmware main loop blocks in SDTEST
        self._busy_until = -1e9
        self._parser = p.FrameParser()
        self._out = bytearray()
        self._streaming = False
        self._last_rx = -1e9
        self._last_state = -1e9
        self._last_sys = -1e9
        self._last_sent: tuple | None = None
        self._seq = 0
        self._boot_time: float | None = None
        self.tx_ok = 0

    # ---- control surface used by the GUI / tests --------------------------------
    def set_button(self, index: int, pressed: bool) -> None:
        if pressed and not self.inputs.buttons[index]:
            self.inputs.press_counts[index] = (self.inputs.press_counts[index] + 1) & 0xFF
        self.inputs.buttons[index] = pressed

    def set_pot(self, index: int, value: float) -> None:
        self.inputs.pots[index] = min(1.0, max(0.0, value))

    def set_sw17(self, position: str) -> None:
        assert position in ("U", "D")
        self.inputs.sw17 = position

    def set_sw18(self, position: str) -> None:
        assert position in ("U", "C", "D")
        self.inputs.sw18 = position

    # ---- host <-> device byte streams ----------------------------------------------
    def receive(self, data: bytes, now: float) -> None:
        self._boot(now)
        for body in self._parser.feed(data):
            self._handle(body, now)

    def output(self, now: float) -> bytes:
        """Returns all bytes the device sent since the previous call."""
        self._boot(now)
        if now < self._busy_until:
            return b""  # main loop blocked in the SD driver: nothing is sent
        if self.responsive:
            self._run_main_loop(now)
        data = bytes(self._out)
        self._out.clear()
        return data if self.responsive else b""

    # ---- internals -----------------------------------------------------------------
    def _boot(self, now: float) -> None:
        if self._boot_time is None:
            self._boot_time = now

    def _send(self, body: str) -> None:
        frame = bytearray(p.build_frame(body))
        if self.corrupt_next_frame:
            frame[1] ^= 0x01  # still printable, CRC no longer matches
            self.corrupt_next_frame = False
        self._out += frame
        self.tx_ok += 1

    def host_active(self, now: float) -> bool:
        return self._streaming and now - self._last_rx < HOST_TIMEOUT_S

    def computed_leds(self, now: float) -> int:
        if self.led_mode == "OFF":
            return 0
        if self.led_mode == "ON":
            return 0xFFFF
        if self.led_mode == "MASK":
            return self.led_mask
        if self.led_mode == "CHASE":
            elapsed_ms = int((now - (self._boot_time or now)) * 1000)
            return 1 << (elapsed_ms // self.chase_ms % p.NUM_LEDS)
        return sum(1 << i for i, b in enumerate(self.inputs.buttons) if b)

    def _handle(self, body: str, now: float) -> None:
        self._last_rx = now
        msg = p.parse_message(body)
        t = msg.type
        if t == "HELLO":
            proto = msg.get("proto")
            if proto is None or not proto.isdigit():
                self._send(f"ERR c={t} e=ARG")
            elif int(proto) != self.protocol_version:
                self._send(f"ERR c={t} e=PROTO")
            else:
                self._streaming = True
                self._last_sent = None
                self._send(
                    f"HELLO proto={self.protocol_version} fw=0.1.0-sim app=DaisyDiagnostic "
                    "dev=seed3-desktop boot=BOOT_SRAM bl=v6_1 libdaisy=f715e48 "
                    "caps=btn,pot,potraw,sw17,sw18,sd,sdread,jack,led sim=1")
                self._send_state(now)
        elif t == "PING":
            n = msg.get("n")
            self._send(f"PONG n={n}" if n and n.isdigit() else f"ERR c={t} e=ARG")
        elif t == "GET":
            self._send_state(now)
        elif t == "RATE":
            hz = msg.get("hz")
            if hz and hz.isdigit() and 10 <= int(hz) <= 100:
                self.rate_hz = int(hz)
                self._send(f"ACK c=RATE hz={self.rate_hz}")
            else:
                self._send(f"ERR c={t} e=ARG")
        elif t == "LED":
            self._handle_led(msg)
        elif t == "SDTEST":
            if self.inputs.sd_card:
                self._busy_until = now + self.sd_test_duration
            self._send(self._sd_result())
        elif t == "BYE":
            self._streaming = False
            self._send("ACK c=BYE")
        else:
            self._send(f"ERR c={t[:12]} e=UNKNOWN")

    def _handle_led(self, msg: p.Message) -> None:
        mode = msg.get("m")
        try:
            if mode not in p.LED_MODES:
                raise ValueError
            mask = int(msg.get("mask"), 16) if msg.get("mask") is not None else self.led_mask
            br = int(msg.get("br")) if msg.get("br") is not None else self.led_brightness
            ms = int(msg.get("ms")) if msg.get("ms") is not None else self.chase_ms
            if not (0 <= mask <= 0xFFFF and 0 <= br <= 100 and 20 <= ms <= 2000):
                raise ValueError
        except ValueError:
            self._send("ERR c=LED e=ARG")
            return
        self.led_mode, self.led_mask, self.led_brightness, self.chase_ms = mode, mask, br, ms
        self._send(f"ACK c=LED m={mode} mask={mask:04X} br={br} ms={ms}")

    def _sd_result(self) -> str:
        if not self.inputs.sd_card:
            return "SD st=NONE res=-1"
        if self.sd_filesystem is None:
            return "SD st=ERROR res=13"
        return (f"SD st=MOUNTED res=0 fs={self.sd_filesystem} mb={self.sd_size_mb} "
                f"ent={self.sd_entries}")

    def state(self, now: float) -> p.BoardState:
        boot = self._boot_time or now
        leds = self.computed_leds(now)
        return p.BoardState(
            seq=self._seq,
            time_ms=int((now - boot) * 1000) & 0xFFFFFFFF,
            buttons=list(self.inputs.buttons),
            press_counts=list(self.inputs.press_counts),
            pots=list(self.inputs.pots),
            pots_raw=[min(65535, int(v * 65535 + 0.5)) for v in self.inputs.pots],
            sw17=self.inputs.sw17,
            sw18=self.inputs.sw18,
            sd_card=self.inputs.sd_card,
            jack_left=self.inputs.jack_left,
            jack_right=self.inputs.jack_right,
            led_mode=self.led_mode,
            leds=[bool(leds >> i & 1) for i in range(p.NUM_LEDS)],
            led_brightness=self.led_brightness,
        )

    def _send_state(self, now: float) -> None:
        self._send(p.format_state(self.state(now)))
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        self._last_state = now
        self._last_sent = self.inputs.digital()
        boot = self._boot_time or now
        self._send(f"SYS up={int(now - boot)} cbhz=1000 txok={self.tx_ok} txbusy=0 "
                   f"txdrop=0 rxok={self._parser.ok} rxbad={self._parser.errors} host=1 "
                   f"rate={self.rate_hz}")
        self._last_sys = now

    def _run_main_loop(self, now: float) -> None:
        if not self.host_active(now):
            return
        period = 1.0 / self.rate_hz
        changed = (self._last_sent != self.inputs.digital()
                   and now - self._last_state >= MIN_FRAME_SPACING_S)
        if now - self._last_state >= period - 1e-6 or changed:
            self._send(p.format_state(self.state(now)))
            self._seq = (self._seq + 1) & 0xFFFFFFFF
            # Keep the nominal rate even if the host polls with a coarse timer.
            behind = now - self._last_state
            self._last_state = now if changed or behind >= 2 * period else self._last_state + period
            self._last_sent = self.inputs.digital()
        if now - self._last_sys >= 1.0 - 1e-6:
            boot = self._boot_time or now
            self._send(f"SYS up={int(now - boot)} cbhz=1000 txok={self.tx_ok} txbusy=0 "
                       f"txdrop=0 rxok={self._parser.ok} rxbad={self._parser.errors} "
                       f"host=1 rate={self.rate_hz}")
            self._last_sys = now


class SimulatedLink:
    """Link to a SimulatedDevice; behaves like an opened serial port."""

    def __init__(self, device: SimulatedDevice, clock, cable: "SimulatedCable") -> None:
        self.device = device
        self._clock = clock
        self._cable = cable
        self._generation = cable.generation
        self.closed = False

    def _check(self) -> None:
        if self.closed or not self._cable.plugged or self._generation != self._cable.generation:
            raise LinkError("simulated USB device disconnected")

    def read(self) -> bytes:
        self._check()
        return self.device.output(self._clock())

    def write(self, data: bytes) -> None:
        self._check()
        self.device.receive(data, self._clock())

    def close(self) -> None:
        self.closed = True


class SimulatedCable:
    """Models the J7 USB cable. Unplugging also powers the board down (J7 supplies it)."""

    PORT_NAME = "SIM"

    def __init__(self, device_factory=SimulatedDevice) -> None:
        self._factory = device_factory
        self.device = device_factory()
        self.plugged = True
        self.generation = 0

    def unplug(self) -> None:
        self.plugged = False
        self.generation += 1

    def plug(self) -> None:
        if not self.plugged:
            # The firmware restarts: inputs keep their physical position, state resets.
            old = self.device.inputs
            self.device = self._factory()
            self.device.inputs = old.copy()
            self.device.inputs.press_counts = [0] * p.NUM_BUTTONS
            self.plugged = True

    def ports(self):
        from .session import PortInfo
        if not self.plugged:
            return []
        return [PortInfo(self.PORT_NAME, p.USB_VID, p.USB_PID, "Simulierter Daisy Seed3 (J7)")]

    def open(self, port: str, clock) -> SimulatedLink:
        if port != self.PORT_NAME or not self.plugged:
            raise LinkError(f"cannot open {port}")
        return SimulatedLink(self.device, clock, self)


def demo_pattern(device: SimulatedDevice, t: float) -> None:
    """Optional animated input pattern for demonstrations ("Demo" in the GUI)."""
    for i in range(p.NUM_POTS):
        device.set_pot(i, 0.5 + 0.5 * math.sin(t * 0.7 + i * 0.6))
    active = int(t * 4) % p.NUM_BUTTONS
    for i in range(p.NUM_BUTTONS):
        device.set_button(i, i == active)
