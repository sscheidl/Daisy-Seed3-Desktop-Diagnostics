"""Connection management: discovery, handshake, keep-alive, timeout and reconnect.

Qt-free and clock-injected so it can be driven deterministically by tests. The GUI
calls ``DeviceSession.poll()`` from a 10 ms timer; nothing here blocks for long.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Protocol

from . import protocol as p
from .simulator import LinkError

HANDSHAKE_TIMEOUT_S = 1.0
HELLO_RETRY_S = 0.3
RX_TIMEOUT_S = 1.5
PING_INTERVAL_S = 0.5
SCAN_INTERVAL_S = 1.0
FAILED_PORT_BACKOFF_S = 5.0
ERROR_DISPLAY_S = 3.0
# libDaisy's SD_read() busy-waits up to SD_TIMEOUT (30 s) in the firmware main loop,
# which also pauses the data stream. Tolerate that while an SD test is pending.
SD_TEST_TIMEOUT_S = 35.0


@dataclass(frozen=True)
class PortInfo:
    device: str
    vid: int | None
    pid: int | None
    description: str

    @property
    def is_daisy_candidate(self) -> bool:
        return self.vid == p.USB_VID and self.pid == p.USB_PID


class Link(Protocol):
    def read(self) -> bytes: ...
    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...


class ConnState(Enum):
    SEARCHING = "Getrennt – suche Gerät"
    HANDSHAKE = "Verbinde …"
    CONNECTED = "Verbunden"
    INCOMPATIBLE = "Protokoll inkompatibel"
    ERROR = "Verbindungsfehler"


class SerialLink:
    """pyserial-based link. Reads are non-blocking."""

    def __init__(self, port: str) -> None:
        import serial  # imported lazily so tests and simulation need no pyserial

        self._serial_mod = serial
        try:
            self._serial = serial.Serial(port=port, baudrate=115200, timeout=0,
                                         write_timeout=0.2)
            self._serial.dtr = True
        except (serial.SerialException, ValueError) as exc:
            raise LinkError(str(exc)) from exc

    def read(self) -> bytes:
        try:
            waiting = self._serial.in_waiting
            return self._serial.read(waiting) if waiting else b""
        except (self._serial_mod.SerialException, OSError) as exc:
            raise LinkError(str(exc)) from exc

    def write(self, data: bytes) -> None:
        try:
            self._serial.write(data)
        except (self._serial_mod.SerialException, OSError) as exc:
            raise LinkError(str(exc)) from exc

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:  # closing a vanished port must never crash the GUI
            pass


def list_serial_ports() -> list[PortInfo]:
    from serial.tools import list_ports

    return [PortInfo(port.device, port.vid, port.pid, port.description or port.device)
            for port in list_ports.comports()]


class DeviceSession:
    """Owns one link at a time and turns DDP traffic into state and events."""

    def __init__(self,
                 scan_ports: Callable[[], Iterable[PortInfo]],
                 open_link: Callable[[str], Link],
                 clock: Callable[[], float] = time.monotonic,
                 port_override: str | None = None,
                 simulated: bool = False) -> None:
        self._scan_ports = scan_ports
        self._open_link = open_link
        self._clock = clock
        self.port_override = port_override
        self.simulated = simulated

        self.state = ConnState.SEARCHING
        self.status_detail = ""
        self.port: str | None = None
        self.device: p.DeviceInfo | None = None
        self.board: p.BoardState | None = None
        self.sys: p.SysInfo | None = None
        self.sd: p.SdInfo | None = None

        self.frames_ok = 0
        self.frame_errors = 0
        self.content_errors = 0
        self.lost_frames = 0
        self.reconnects = 0
        self.state_rate_hz = 0.0
        self.rtt_ms: float | None = None

        self._link: Link | None = None
        self._parser = p.FrameParser()
        self._next_scan = 0.0
        self._handshake_deadline = 0.0
        self._next_hello = 0.0
        self._last_rx = 0.0
        self._last_ping = 0.0
        self._ping_n = 0
        self._ping_sent: dict[int, float] = {}
        self._failed_ports: dict[str, float] = {}
        self._state_times: deque[float] = deque()
        self._events: deque[tuple[str, object]] = deque(maxlen=500)
        self._ever_connected = False
        self._error_until = 0.0
        self._sd_deadline: float | None = None

    # ---- public API ------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.state == ConnState.CONNECTED

    def drain_events(self) -> list[tuple[str, object]]:
        events = list(self._events)
        self._events.clear()
        return events

    def send(self, body: str) -> bool:
        """Sends a command while connected. Returns False if it could not be sent."""
        if self._link is None or self.state != ConnState.CONNECTED:
            return False
        return self._write(body)

    def set_led(self, mode: str, mask: int | None = None, brightness: int | None = None,
                step_ms: int | None = None) -> bool:
        return self.send(p.cmd_led(mode, mask, brightness, step_ms))

    @property
    def sd_test_pending(self) -> bool:
        return self._sd_deadline is not None

    def request_sd_test(self) -> bool:
        if not self.send("SDTEST"):
            return False
        self._sd_deadline = self._clock() + SD_TEST_TIMEOUT_S
        return True

    def disconnect(self, reason: str = "vom Benutzer getrennt") -> None:
        if self._link is not None:
            try:
                if self.state == ConnState.CONNECTED:
                    self._link.write(p.build_frame("BYE"))
            except LinkError:
                pass
        self._drop_link(reason, ConnState.SEARCHING)

    def poll(self) -> None:
        now = self._clock()
        if self._link is None:
            if now >= self._next_scan:
                self._next_scan = now + SCAN_INTERVAL_S
                self._try_connect(now)
            return
        try:
            data = self._link.read()
        except LinkError as exc:
            self._drop_link(f"USB-Verbindung getrennt ({exc})", ConnState.SEARCHING)
            return
        if data:
            errors_before = self._parser.errors
            for body in self._parser.feed(data):
                self._last_rx = now
                self.frames_ok += 1
                self._handle(body, now)
                if self._link is None:
                    return
            self.frame_errors += self._parser.errors - errors_before

        if self.state == ConnState.HANDSHAKE:
            if now >= self._handshake_deadline:
                self._failed_ports[self.port or ""] = now + FAILED_PORT_BACKOFF_S
                self._drop_link(f"{self.port}: keine DDP-Antwort auf HELLO",
                                ConnState.SEARCHING)
                return
            if now >= self._next_hello:  # the first HELLO may arrive while firmware boots
                self._next_hello = now + HELLO_RETRY_S
                self._write(p.cmd_hello())
        if self.state == ConnState.CONNECTED:
            if self._sd_deadline is not None and now > self._sd_deadline:
                self._sd_deadline = None
                self._event("log", "microSD-Test: keine Antwort der Firmware")
            if now - self._last_rx > RX_TIMEOUT_S and self._sd_deadline is None:
                self._drop_link("Zeitüberschreitung: keine Daten seit "
                                f"{RX_TIMEOUT_S:.1f} s", ConnState.ERROR)
                return
            if now - self._last_ping >= PING_INTERVAL_S:
                self._last_ping = now
                self._ping_n = (self._ping_n + 1) & 0xFFFFFFFF
                self._ping_sent[self._ping_n] = now
                if len(self._ping_sent) > 20:
                    self._ping_sent.pop(next(iter(self._ping_sent)))
                self._write(p.cmd_ping(self._ping_n))
        while self._state_times and now - self._state_times[0] > 1.0:
            self._state_times.popleft()
        self.state_rate_hz = float(len(self._state_times))

    # ---- internals --------------------------------------------------------------------
    def _event(self, kind: str, payload: object = None) -> None:
        self._events.append((kind, payload))

    def _set_state(self, state: ConnState, detail: str = "") -> None:
        if state == ConnState.ERROR:
            self._error_until = self._clock() + ERROR_DISPLAY_S
        if state != self.state or detail != self.status_detail:
            self.state = state
            self.status_detail = detail
            self._event("state", (state, detail))

    def _candidates(self) -> list[PortInfo]:
        try:
            ports = list(self._scan_ports())
        except Exception as exc:  # e.g. driver enumeration failure
            self._set_state(ConnState.ERROR, f"Portsuche fehlgeschlagen: {exc}")
            return []
        if self.port_override:
            return [port for port in ports if port.device == self.port_override]
        return [port for port in ports if port.is_daisy_candidate]

    def _try_connect(self, now: float) -> None:
        candidates = self._candidates()
        for port in candidates:
            if self._failed_ports.get(port.device, 0.0) > now:
                continue
            try:
                link = self._open_link(port.device)
            except LinkError as exc:
                self._failed_ports[port.device] = now + FAILED_PORT_BACKOFF_S
                self._set_state(ConnState.ERROR, f"{port.device} lässt sich nicht öffnen: {exc}")
                self._event("log", f"{port.device}: Öffnen fehlgeschlagen ({exc})")
                continue
            self._link = link
            self.port = port.device
            self._parser = p.FrameParser()
            self._handshake_deadline = now + HANDSHAKE_TIMEOUT_S
            self._last_rx = now
            self._set_state(ConnState.HANDSHAKE, f"{port.device}: HELLO gesendet")
            self._next_hello = now + HELLO_RETRY_S
            self._write(p.cmd_hello())
            return
        # Keep an error visible for a moment, and an incompatible device while present.
        if self.state == ConnState.INCOMPATIBLE and candidates:
            return
        if self.state == ConnState.ERROR and now < self._error_until:
            return
        self._set_state(ConnState.SEARCHING,
                            f"Port {self.port_override} nicht gefunden" if self.port_override
                            else "Kein Daisy (VID 0483 / PID 5740) gefunden")

    def _write(self, body: str) -> bool:
        if self._link is None:
            return False
        try:
            self._link.write(p.build_frame(body))
            return True
        except LinkError as exc:
            self._drop_link(f"Senden fehlgeschlagen ({exc})", ConnState.ERROR)
            return False

    def _drop_link(self, reason: str, state: ConnState) -> None:
        if self._link is not None:
            self._link.close()
        was_connected = self.state == ConnState.CONNECTED
        self._link = None
        self.board = None
        self.sys = None
        self._sd_deadline = None
        self._state_times.clear()
        self.state_rate_hz = 0.0
        self._next_scan = self._clock() + SCAN_INTERVAL_S
        self._set_state(state, reason)
        self._event("log", reason)
        if was_connected:
            self._event("disconnected", reason)

    def _handle(self, body: str, now: float) -> None:
        try:
            msg = p.parse_message(body)
            if msg.type == "HELLO":
                info = p.parse_hello(msg)
                self.device = info
                if info.protocol != p.PROTOCOL_VERSION:
                    self._failed_ports[self.port or ""] = now + FAILED_PORT_BACKOFF_S
                    self._drop_link(f"Gerät meldet Protokoll {info.protocol}, erwartet "
                                    f"{p.PROTOCOL_VERSION}", ConnState.INCOMPATIBLE)
                    return
                if self.state == ConnState.CONNECTED:
                    return  # answer to a repeated HELLO
                if self._ever_connected:
                    self.reconnects += 1
                self._ever_connected = True
                self._last_ping = now
                self._set_state(ConnState.CONNECTED, f"{self.port}")
                self._event("connected", info)
            elif msg.type == "ST":
                if self.state != ConnState.CONNECTED:
                    return
                state = p.parse_state(msg)
                if self.board is not None:
                    gap = (state.seq - self.board.seq - 1) & 0xFFFFFFFF
                    if 0 < gap < 1000:
                        self.lost_frames += gap
                self.board = state
                self._state_times.append(now)
                self._event("board", state)
            elif msg.type == "SYS":
                self.sys = p.parse_sys(msg)
            elif msg.type == "SD":
                self.sd = p.parse_sd(msg)
                self._sd_deadline = None
                self._event("sd", self.sd)
            elif msg.type == "PONG":
                sent = self._ping_sent.pop(msg.int("n"), None)
                if sent is not None:
                    self.rtt_ms = (now - sent) * 1000.0
            elif msg.type == "ACK":
                self._event("log", f"Bestätigt: {body}")
            elif msg.type == "ERR":
                if self.state == ConnState.HANDSHAKE and msg.get("e") == "PROTO":
                    self._failed_ports[self.port or ""] = now + FAILED_PORT_BACKOFF_S
                    self._drop_link("Firmware unterstützt Protokoll "
                                    f"{p.PROTOCOL_VERSION} nicht", ConnState.INCOMPATIBLE)
                    return
                self._event("log", f"Fehlermeldung der Firmware: {body}")
            # unknown message types are ignored (forward compatibility)
        except p.ProtocolError as exc:
            self.content_errors += 1
            self._event("log", f"Ungültige Nachricht verworfen: {exc}")
