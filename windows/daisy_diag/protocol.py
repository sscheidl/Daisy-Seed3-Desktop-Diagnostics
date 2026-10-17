"""Daisy Diagnostic Protocol (DDP) v1 - host implementation.

Specification: diagnostics/protocol/PROTOCOL.md. Mirrors diagnostics/protocol/ddp.cpp.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PROTOCOL_VERSION = 1
MAX_BODY = 400
NUM_BUTTONS = 16
NUM_LEDS = 16
NUM_POTS = 8
LED_MODES = ("OFF", "ON", "MASK", "CHASE", "FOLLOW")
USB_VID = 0x0483
USB_PID = 0x5740


class ProtocolError(ValueError):
    """A frame was valid but its content could not be interpreted."""


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no final XOR)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def is_body_char(byte: int) -> bool:
    return 0x20 <= byte <= 0x7E and byte not in (0x24, 0x2A)  # '$', '*'


def build_frame(body: str) -> bytes:
    raw = body.encode("ascii")
    if not raw or len(raw) > MAX_BODY or not all(is_body_char(b) for b in raw):
        raise ValueError(f"invalid DDP body: {body!r}")
    return b"$" + raw + b"*" + f"{crc16(raw):04X}".encode("ascii") + b"\n"


class FrameParser:
    """Byte-wise receiver with resynchronisation (see PROTOCOL.md, 'Empfaengerregeln')."""

    _HEX = frozenset(b"0123456789ABCDEFabcdef")

    def __init__(self) -> None:
        self.ok = 0
        self.bad_crc = 0
        self.bad_format = 0
        self.overflow = 0
        self._state = "idle"
        self._body = bytearray()
        self._crc = bytearray()

    @property
    def errors(self) -> int:
        return self.bad_crc + self.bad_format + self.overflow

    def feed(self, data: bytes) -> list[str]:
        bodies: list[str] = []
        for byte in data:
            body = self._feed_byte(byte)
            if body is not None:
                bodies.append(body)
        return bodies

    def _feed_byte(self, byte: int) -> str | None:
        if byte == 0x24:  # '$'
            if self._state != "idle":
                self.bad_format += 1
            self._state = "body"
            self._body.clear()
            return None
        state = self._state
        if state == "idle":
            return None
        if state == "body":
            if byte == 0x2A:  # '*'
                self._state = "crc"
                self._crc.clear()
            elif not is_body_char(byte):
                self.bad_format += 1
                self._state = "idle"
            elif len(self._body) >= MAX_BODY:
                self.overflow += 1
                self._state = "idle"
            else:
                self._body.append(byte)
            return None
        if state == "crc":
            if len(self._crc) < 4:
                if byte in self._HEX:
                    self._crc.append(byte)
                else:
                    self.bad_format += 1
                    self._state = "idle"
                return None
            if byte == 0x0D:
                self._state = "cr"
                return None
            if byte == 0x0A:
                return self._finish()
            self.bad_format += 1
            self._state = "idle"
            return None
        # state == "cr"
        if byte == 0x0A:
            return self._finish()
        self.bad_format += 1
        self._state = "idle"
        return None

    def _finish(self) -> str | None:
        self._state = "idle"
        if not self._body:
            self.bad_format += 1
            return None
        if int(self._crc.decode("ascii"), 16) != crc16(bytes(self._body)):
            self.bad_crc += 1
            return None
        self.ok += 1
        return self._body.decode("ascii")


@dataclass
class Message:
    type: str
    fields: dict[str, str]

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.fields.get(key, default)

    def int(self, key: str, base: int = 10) -> int:
        try:
            return int(self.fields[key], base)
        except (KeyError, ValueError) as exc:
            raise ProtocolError(f"{self.type}: field {key!r} missing or invalid") from exc


def parse_message(body: str) -> Message:
    tokens = [t for t in body.split(" ") if t]
    if not tokens:
        raise ProtocolError("empty message")
    fields: dict[str, str] = {}
    for token in tokens[1:]:
        key, sep, value = token.partition("=")
        if sep:
            fields[key] = value
    return Message(tokens[0], fields)


def format_message(msg_type: str, **fields: object) -> str:
    parts = [msg_type] + [f"{k}={v}" for k, v in fields.items()]
    return " ".join(parts)


@dataclass
class BoardState:
    """Complete panel state as reported by an ST message."""

    seq: int = 0
    time_ms: int = 0
    buttons: list[bool] = field(default_factory=lambda: [False] * NUM_BUTTONS)
    press_counts: list[int] = field(default_factory=lambda: [0] * NUM_BUTTONS)
    pots: list[float] = field(default_factory=lambda: [0.0] * NUM_POTS)  # 0.0 .. 1.0
    pots_raw: list[int] = field(default_factory=lambda: [0] * NUM_POTS)  # 0 .. 65535
    sw17: str = "D"  # 'U' / 'D'
    sw18: str = "C"  # 'U' / 'C' / 'D'
    sd_card: bool = False
    jack_left: bool = False
    jack_right: bool = False
    led_mode: str = "FOLLOW"
    leds: list[bool] = field(default_factory=lambda: [False] * NUM_LEDS)
    led_brightness: int = 100


def _mask_bits(mask: int, count: int) -> list[bool]:
    return [bool(mask >> i & 1) for i in range(count)]


def _int_list(msg: Message, key: str, count: int, low: int, high: int) -> list[int]:
    raw = msg.get(key)
    if raw is None:
        raise ProtocolError(f"ST: field {key!r} missing")
    try:
        values = [int(v) for v in raw.split(",")]
    except ValueError as exc:
        raise ProtocolError(f"ST: field {key!r} invalid") from exc
    if len(values) != count or any(not low <= v <= high for v in values):
        raise ProtocolError(f"ST: field {key!r} must have {count} values in {low}..{high}")
    return values


def _flag(msg: Message, key: str) -> bool:
    value = msg.get(key)
    if value not in ("0", "1"):
        raise ProtocolError(f"ST: field {key!r} must be 0 or 1")
    return value == "1"


def parse_state(msg: Message) -> BoardState:
    if msg.type != "ST":
        raise ProtocolError(f"expected ST, got {msg.type}")
    pc = msg.get("pc", "")
    if len(pc) != 2 * NUM_BUTTONS:
        raise ProtocolError("ST: field 'pc' must have 32 hex digits")
    try:
        counts = [int(pc[i:i + 2], 16) for i in range(0, len(pc), 2)]
    except ValueError as exc:
        raise ProtocolError("ST: field 'pc' invalid") from exc
    sw17 = msg.get("s17")
    sw18 = msg.get("s18")
    if sw17 not in ("U", "D") or sw18 not in ("U", "C", "D"):
        raise ProtocolError("ST: invalid switch position")
    led_mode = msg.get("lm")
    if led_mode not in LED_MODES:
        raise ProtocolError(f"ST: unknown LED mode {led_mode!r}")
    buttons = msg.int("b", 16)
    leds = msg.int("l", 16)
    if not 0 <= buttons <= 0xFFFF or not 0 <= leds <= 0xFFFF:
        raise ProtocolError("ST: mask out of range")
    return BoardState(
        seq=msg.int("n"),
        time_ms=msg.int("t"),
        buttons=_mask_bits(buttons, NUM_BUTTONS),
        press_counts=counts,
        pots=[v / 10000.0 for v in _int_list(msg, "p", NUM_POTS, 0, 10000)],
        pots_raw=_int_list(msg, "r", NUM_POTS, 0, 65535),
        sw17=sw17,
        sw18=sw18,
        sd_card=_flag(msg, "sd"),
        jack_left=_flag(msg, "jl"),
        jack_right=_flag(msg, "jr"),
        led_mode=led_mode,
        leds=_mask_bits(leds, NUM_LEDS),
        led_brightness=msg.int("br"),
    )


def format_state(state: BoardState) -> str:
    """Inverse of parse_state; produces exactly the firmware's ST layout."""
    def mask(bits: list[bool]) -> str:
        return f"{sum(1 << i for i, on in enumerate(bits) if on):04X}"

    return (
        f"ST n={state.seq} t={state.time_ms} b={mask(state.buttons)} "
        f"pc={''.join(f'{c & 0xFF:02X}' for c in state.press_counts)} "
        f"p={','.join(str(pot_to_int(v)) for v in state.pots)} "
        f"r={','.join(str(v) for v in state.pots_raw)} "
        f"s17={state.sw17} s18={state.sw18} sd={int(state.sd_card)} "
        f"jl={int(state.jack_left)} jr={int(state.jack_right)} "
        f"lm={state.led_mode} l={mask(state.leds)} br={state.led_brightness}"
    )


def pot_to_int(value: float) -> int:
    """Same rounding as diag::NormalizePot in the firmware."""
    if not value > 0.0:
        return 0
    if value >= 1.0:
        return 10000
    return int(value * 10000.0 + 0.5)


@dataclass
class DeviceInfo:
    protocol: int
    firmware: str
    app: str
    device: str
    boot: str
    bootloader: str
    libdaisy: str
    capabilities: list[str]
    simulated: bool = False


def parse_hello(msg: Message) -> DeviceInfo:
    return DeviceInfo(
        protocol=msg.int("proto"),
        firmware=msg.get("fw", "?"),
        app=msg.get("app", "?"),
        device=msg.get("dev", "?"),
        boot=msg.get("boot", "?"),
        bootloader=msg.get("bl", "?"),
        libdaisy=msg.get("libdaisy", "?"),
        capabilities=[c for c in msg.get("caps", "").split(",") if c],
        simulated=msg.get("sim") == "1",
    )


@dataclass
class SdInfo:
    status: str  # NONE / MOUNTED / ERROR
    fresult: int
    fs_type: str = "-"
    size_mb: int = 0
    entries: int = 0


FRESULT_TEXT = {
    0: "FR_OK",
    1: "FR_DISK_ERR (Lesefehler)",
    2: "FR_INT_ERR",
    3: "FR_NOT_READY (Karte antwortet nicht)",
    4: "FR_NO_FILE",
    5: "FR_NO_PATH",
    9: "FR_INVALID_OBJECT",
    11: "FR_INVALID_DRIVE",
    12: "FR_NOT_ENABLED",
    13: "FR_NO_FILESYSTEM (kein FAT/exFAT)",
    15: "FR_TIMEOUT",
}


def parse_sd(msg: Message) -> SdInfo:
    status = msg.get("st")
    if status not in ("NONE", "MOUNTED", "ERROR"):
        raise ProtocolError(f"SD: unknown status {status!r}")
    info = SdInfo(status=status, fresult=msg.int("res"))
    if status == "MOUNTED":
        info.fs_type = msg.get("fs", "?")
        info.size_mb = msg.int("mb")
        info.entries = msg.int("ent")
    return info


@dataclass
class SysInfo:
    uptime_s: int
    control_rate_hz: int
    tx_ok: int
    tx_busy: int
    tx_drop: int
    rx_ok: int
    rx_bad: int
    rate_hz: int


def parse_sys(msg: Message) -> SysInfo:
    return SysInfo(
        uptime_s=msg.int("up"),
        control_rate_hz=msg.int("cbhz"),
        tx_ok=msg.int("txok"),
        tx_busy=msg.int("txbusy"),
        tx_drop=msg.int("txdrop"),
        rx_ok=msg.int("rxok"),
        rx_bad=msg.int("rxbad"),
        rate_hz=msg.int("rate"),
    )


# ---- Host -> firmware commands ---------------------------------------------------

def cmd_hello() -> str:
    return f"HELLO proto={PROTOCOL_VERSION}"


def cmd_ping(n: int) -> str:
    return f"PING n={n & 0xFFFFFFFF}"


def cmd_led(mode: str, mask: int | None = None, brightness: int | None = None,
            step_ms: int | None = None) -> str:
    if mode not in LED_MODES:
        raise ValueError(f"unknown LED mode {mode!r}")
    body = f"LED m={mode}"
    if mask is not None:
        body += f" mask={mask & 0xFFFF:04X}"
    if brightness is not None:
        body += f" br={max(0, min(100, int(brightness)))}"
    if step_ms is not None:
        body += f" ms={max(20, min(2000, int(step_ms)))}"
    return body


def cmd_rate(hz: int) -> str:
    return f"RATE hz={max(10, min(100, int(hz)))}"
