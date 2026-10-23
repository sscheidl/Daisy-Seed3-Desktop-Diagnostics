"""Connection, real-time updates, LED and SD commands, disconnect and reconnect.

Runs the complete host stack (DeviceSession + DDP framing) against the simulated
firmware with a deterministic clock. No hardware involved.
"""
import pytest

from conftest import FakeClock
from daisy_diag import protocol as p
from daisy_diag.session import ConnState, DeviceSession, PortInfo
from daisy_diag.simulator import LinkError, SimulatedCable, SimulatedDevice


def make(device_factory=SimulatedDevice):
    clock = FakeClock()
    cable = SimulatedCable(device_factory)
    session = DeviceSession(cable.ports, lambda port: cable.open(port, clock), clock,
                            simulated=True)
    return clock, cable, session


def run(clock, session, seconds, step=0.005):
    for _ in range(int(round(seconds / step))):
        session.poll()
        clock.advance(step)


@pytest.fixture
def connected():
    clock, cable, session = make()
    run(clock, session, 0.2)
    assert session.state == ConnState.CONNECTED
    return clock, cable, session


def test_handshake_reports_versions(connected):
    _, _, s = connected
    assert s.device.protocol == p.PROTOCOL_VERSION
    assert s.device.firmware == "0.2.0-sim"
    assert s.device.simulated
    events = [k for k, _ in s.drain_events()]
    assert "connected" in events


def test_streaming_rate_and_keepalive(connected):
    clock, _, s = connected
    run(clock, s, 3.0)
    assert 45 <= s.state_rate_hz <= 55
    assert s.frame_errors == 0 and s.lost_frames == 0
    assert s.rtt_ms is not None
    assert s.sys is not None and s.sys.control_rate_hz == 1000
    assert s.state == ConnState.CONNECTED  # PINGs keep the firmware streaming beyond 3 s


@pytest.mark.parametrize("index", range(p.NUM_BUTTONS))
def test_every_button_press_and_release(connected, index):
    clock, cable, s = connected
    cable.device.set_button(index, True)
    run(clock, s, 0.02)
    assert s.board.buttons == [i == index for i in range(16)]
    assert s.board.press_counts[index] == 1
    assert s.board.leds[index]  # default LED mode FOLLOW
    cable.device.set_button(index, False)
    run(clock, s, 0.02)
    assert not any(s.board.buttons) and not any(s.board.leds)


def test_short_press_between_frames_is_counted(connected):
    clock, cable, s = connected
    cable.device.set_button(3, True)
    cable.device.set_button(3, False)
    run(clock, s, 0.05)
    assert not s.board.buttons[3]
    assert s.board.press_counts[3] == 1


@pytest.mark.parametrize("index", range(p.NUM_POTS))
def test_every_pot(connected, index):
    clock, cable, s = connected
    for value in (0.0, 0.25, 1.0):
        cable.device.set_pot(index, value)
        run(clock, s, 0.05)
        assert s.board.pots[index] == pytest.approx(value, abs=1e-4)
        assert s.board.pots_raw[index] == round(value * 65535)
    others = [v for i, v in enumerate(s.board.pots) if i != index]
    assert others == [0.0] * 7


def test_toggle_switches(connected):
    clock, cable, s = connected
    for pos in ("U", "D", "U"):
        cable.device.set_sw17(pos)
        run(clock, s, 0.02)
        assert s.board.sw17 == pos
    for pos in ("U", "C", "D", "C"):
        cable.device.set_sw18(pos)
        run(clock, s, 0.02)
        assert s.board.sw18 == pos


def test_jack_detection(connected):
    clock, cable, s = connected
    cable.device.inputs.jack_left = True
    run(clock, s, 0.02)
    assert (s.board.jack_left, s.board.jack_right) == (True, False)
    cable.device.inputs.jack_right = True
    cable.device.inputs.jack_left = False
    run(clock, s, 0.02)
    assert (s.board.jack_left, s.board.jack_right) == (False, True)


@pytest.mark.parametrize("mode", p.LED_MODES)
def test_led_modes(connected, mode):
    clock, cable, s = connected
    cable.device.set_button(2, True)
    assert s.set_led(mode, mask=0x8001, brightness=40, step_ms=100)
    run(clock, s, 0.03)
    assert s.board.led_mode == mode
    assert s.board.led_brightness == 40
    expected = {"OFF": [], "ON": list(range(16)), "MASK": [0, 15], "FOLLOW": [2]}
    if mode in expected:
        assert [i for i, on in enumerate(s.board.leds) if on] == expected[mode]
    else:  # CHASE: exactly one LED, moving every 100 ms
        seen = set()
        for _ in range(20):
            assert sum(s.board.leds) == 1
            seen.add(s.board.leds.index(True))
            run(clock, s, 0.1)
        assert len(seen) == 16
    assert any(k == "log" and "ACK c=LED" in str(v) for k, v in s.drain_events())


def test_each_led_individually(connected):
    clock, _, s = connected
    for i in range(p.NUM_LEDS):
        s.set_led("MASK", mask=1 << i)
        run(clock, s, 0.03)
        assert [k for k, on in enumerate(s.board.leds) if on] == [i]


def test_invalid_led_command_reports_error(connected):
    clock, _, s = connected
    s.send("LED m=MASK mask=10000")
    run(clock, s, 0.03)
    logs = [str(v) for k, v in s.drain_events() if k == "log"]
    assert any("ERR c=LED e=ARG" in line for line in logs)
    assert s.state == ConnState.CONNECTED


def test_sd_status_messages(connected):
    clock, cable, s = connected
    s.request_sd_test()
    run(clock, s, 0.03)
    assert s.sd.status == "NONE"
    cable.device.inputs.sd_card = True
    run(clock, s, 0.03)
    assert s.board.sd_card
    s.request_sd_test()
    run(clock, s, 0.03)
    assert (s.sd.status, s.sd.fs_type, s.sd.entries) == ("MOUNTED", "FAT32", 12)
    cable.device.sd_filesystem = None
    s.request_sd_test()
    run(clock, s, 0.03)
    assert (s.sd.status, s.sd.fresult) == ("ERROR", 13)


def test_unplug_and_replug_reconnects(connected):
    clock, cable, s = connected
    cable.device.set_button(0, True)
    run(clock, s, 0.05)
    cable.unplug()
    run(clock, s, 0.05)
    assert s.state == ConnState.SEARCHING
    assert s.board is None
    assert any(k == "disconnected" for k, _ in s.drain_events())
    run(clock, s, 2.0)
    assert s.state == ConnState.SEARCHING  # nothing to find while unplugged
    cable.plug()
    run(clock, s, 1.5)
    assert s.state == ConnState.CONNECTED
    assert s.reconnects == 1
    assert s.board.buttons[0]  # button still held physically
    assert s.board.press_counts[0] == 0  # firmware restarted


def test_hung_firmware_times_out_then_recovers(connected):
    clock, cable, s = connected
    cable.device.responsive = False
    run(clock, s, 1.0)
    assert s.state == ConnState.CONNECTED
    run(clock, s, 0.7)
    assert s.state == ConnState.ERROR
    assert 'Timeout' in s.status_detail
    cable.device.responsive = True
    run(clock, s, 2.0)
    assert s.state == ConnState.CONNECTED


def test_corrupted_frame_is_counted_and_connection_survives(connected):
    clock, cable, s = connected
    cable.device.corrupt_next_frame = True
    run(clock, s, 0.5)
    assert s.frame_errors == 1
    assert s.lost_frames == 1  # the corrupted frame was an ST frame
    assert s.state == ConnState.CONNECTED


def test_incomplete_data_is_ignored(connected):
    clock, cable, s = connected
    original = cable.device.output
    cable.device.output = lambda now: b"$ST n=9 b=00" + original(now)
    run(clock, s, 0.2)
    cable.device.output = original
    assert s.frame_errors > 0
    assert s.state == ConnState.CONNECTED and s.board is not None


def test_invalid_state_content_is_counted_not_fatal(connected):
    clock, cable, s = connected
    original = cable.device.output
    cable.device.output = lambda now: p.build_frame("ST n=1 b=zz") + original(now)
    run(clock, s, 0.05)
    cable.device.output = original
    assert s.content_errors >= 1
    assert s.state == ConnState.CONNECTED


def test_incompatible_protocol_version():
    clock, _, s = make(lambda: SimulatedDevice(protocol_version=2))
    run(clock, s, 0.2)
    assert s.state == ConnState.INCOMPATIBLE
    run(clock, s, 3.0)
    assert s.state == ConnState.INCOMPATIBLE


class SilentLink:
    """Another STM32 virtual COM port with the same VID/PID that never answers DDP."""

    def __init__(self):
        self.written = b""
        self.closed = False

    def read(self):
        return b"random text\r\n"

    def write(self, data):
        self.written += data

    def close(self):
        self.closed = True


def test_foreign_device_with_same_vid_pid_is_skipped():
    clock = FakeClock()
    cable = SimulatedCable()
    foreign = SilentLink()

    def ports():
        return [PortInfo("COM9", p.USB_VID, p.USB_PID, "STM32 VCP")] + cable.ports()

    def open_link(name):
        return foreign if name == "COM9" else cable.open(name, clock)

    s = DeviceSession(ports, open_link, clock)
    run(clock, s, 0.5)
    assert s.state == ConnState.HANDSHAKE and s.port == "COM9"
    assert foreign.written.startswith(b"$HELLO proto=1*")
    run(clock, s, 2.0)
    assert foreign.closed
    assert s.state == ConnState.CONNECTED and s.port == "SIM"


def test_non_daisy_ports_are_not_opened():
    clock = FakeClock()
    opened = []

    def ports():
        return [PortInfo("COM3", 0x17CC, 0x2110, "Native Instruments"),
                PortInfo("COM6", None, None, "Bluetooth")]

    s = DeviceSession(ports, opened.append, clock)
    run(clock, s, 3.0)
    assert opened == []
    assert s.state == ConnState.SEARCHING


def test_port_override_and_open_failure():
    clock = FakeClock()

    def fail(name):
        raise LinkError('Access denied')

    s = DeviceSession(lambda: [PortInfo("COM7", None, None, "USB Serial")], fail, clock,
                      port_override="COM7")
    run(clock, s, 0.1)
    assert s.state == ConnState.ERROR
    assert 'Access denied' in s.status_detail


def test_user_disconnect_sends_bye(connected):
    clock, cable, s = connected
    s.disconnect()
    assert s.state == ConnState.SEARCHING
    assert not cable.device.host_active(clock())


def test_firmware_stops_streaming_without_host():
    clock = FakeClock()
    dev = SimulatedDevice()
    dev.receive(p.build_frame("HELLO proto=1"), clock())
    assert dev.output(clock()).count(b"$ST ") == 1
    clock.advance(1.0)
    assert dev.output(clock()).count(b"$ST ") == 1
    clock.advance(2.5)  # more than 3 s since the last host frame
    assert dev.output(clock()) == b""


def test_slow_sd_card_does_not_drop_connection(connected):
    clock, cable, s = connected
    cable.device.inputs.sd_card = True
    cable.device.sd_test_duration = 6.0  # firmware blocked in SD_read for 6 s
    run(clock, s, 0.05)
    assert s.request_sd_test()
    assert s.sd_test_pending
    run(clock, s, 3.0)
    assert s.state == ConnState.CONNECTED  # longer than RX_TIMEOUT_S, but tolerated
    run(clock, s, 3.5)
    assert s.sd.status == "MOUNTED" and not s.sd_test_pending
    run(clock, s, 0.5)
    assert s.state == ConnState.CONNECTED and s.state_rate_hz > 0


def test_commands_wait_while_firmware_is_blocked(connected):
    # P6: during the SD block the simulated firmware queues bytes like its RX ring.
    clock, cable, s = connected
    dev = cable.device
    dev.inputs.sd_card = True
    dev.sd_test_duration = 2.0
    run(clock, s, 0.05)
    assert s.request_sd_test()
    run(clock, s, 0.05)
    s.set_led("ON")
    run(clock, s, 0.05)
    assert dev.led_mode == "FOLLOW"  # not processed yet: main loop blocked
    run(clock, s, 2.5)
    assert dev.led_mode == "ON"
    assert s.board.led_mode == "ON"
    assert s.state == ConnState.CONNECTED


def test_rx_ring_overflow_while_blocked_is_counted():
    clock = FakeClock()
    dev = SimulatedDevice()
    dev.inputs.sd_card = True
    dev.sd_test_duration = 5.0
    dev.receive(p.build_frame("HELLO proto=1"), clock())
    dev.output(clock())
    dev.receive(p.build_frame("SDTEST"), clock())
    flood = p.build_frame("PING n=1") * 100  # ~1.5 KiB > 1 KiB ring
    dev.receive(flood, clock())
    assert dev.rx_overflow == len(flood) - (dev.RX_RING_SIZE)
    clock.advance(5.1)
    out = dev.output(clock())
    assert out.count(b"$SD st=") == 1
    assert out.count(b"$PONG") == dev.RX_RING_SIZE // len(p.build_frame("PING n=1"))
    assert b"rxbad=" in out


def test_ping_after_timeout_does_not_restart_stream():
    # P9, simulator side (firmware side is covered by the C++ tests).
    clock = FakeClock()
    dev = SimulatedDevice()
    dev.receive(p.build_frame("HELLO proto=1"), clock())
    dev.output(clock())
    clock.advance(3.5)
    dev.receive(p.build_frame("PING n=4"), clock())
    out = dev.output(clock())
    assert b"$PONG n=4*" in out and b"$ST " not in out
    clock.advance(0.5)
    assert b"$ST " not in dev.output(clock())


def test_simulator_clock_starting_at_zero():
    # P12: a start time of 0.0 is a valid time, not "unset".
    clock = FakeClock(start=0.0)
    dev = SimulatedDevice()
    dev.receive(p.build_frame("HELLO proto=1"), clock())
    dev.receive(p.build_frame("LED m=CHASE ms=100"), clock())
    dev.output(clock())
    clock.advance(1.0)
    state = dev.state(clock())
    assert state.time_ms == 1000
    assert state.leds.index(True) == 10


def test_large_sequence_gap_is_counted(connected):
    # P8: a gap of 1000 or more ST frames used to be ignored.
    clock, cable, s = connected
    dev = cable.device
    run(clock, s, 0.1)
    before = s.lost_frames
    dev._seq += 1000
    run(clock, s, 0.1)
    assert s.lost_frames == before + 1000


def test_sequence_gap_rules():
    clock, _, s = make()
    assert s._sequence_gap(5, 6) == 0
    assert s._sequence_gap(0, 1001) == 1000
    assert s._sequence_gap(0xFFFFFFFE, 1) == 2  # wrap-around
    assert s._sequence_gap(10, 10) == 0
    assert s._sequence_gap(10, 3) == 0
    assert any("Unexpected sequence number" in str(v) for k, v in s.drain_events())


class FailingLink:
    def __init__(self, fail_write=False, fail_read=False):
        self.fail_write, self.fail_read = fail_write, fail_read
        self.closed = False

    def read(self):
        if self.fail_read:
            raise LinkError("read failed")
        return b""

    def write(self, data):
        if self.fail_write:
            raise LinkError("write failed")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("failure", ["write", "read"])
def test_handshake_io_error_backs_off_and_tries_next_port(failure):
    # P3: a broken first port must not block a working Daisy behind it.
    clock = FakeClock()
    cable = SimulatedCable()
    opened = []

    def ports():
        return [PortInfo("COM2", p.USB_VID, p.USB_PID, "kaputt")] + cable.ports()

    def open_link(name):
        opened.append(name)
        if name == "COM2":
            return FailingLink(fail_write=failure == "write", fail_read=failure == "read")
        return cable.open(name, clock)

    s = DeviceSession(ports, open_link, clock)
    run(clock, s, 2.5)
    assert s.state == ConnState.CONNECTED and s.port == "SIM"
    assert opened.count("COM2") == 1


def test_stream_loss_without_sd_test_still_times_out(connected):
    clock, cable, s = connected
    cable.device.inputs.sd_card = True
    cable.device.sd_test_duration = 6.0
    cable.device.receive(p.build_frame("SDTEST"), clock())  # not requested by the session
    run(clock, s, 2.0)
    assert s.state == ConnState.ERROR


def test_hello_is_repeated_if_first_one_is_lost():
    clock, cable, s = make()
    original = cable.device.receive
    dropped = []

    def lossy(data, now):
        if not dropped:
            dropped.append(data)  # first HELLO lost during firmware start-up
            return
        original(data, now)

    cable.device.receive = lossy
    run(clock, s, 0.6)
    assert dropped and dropped[0].startswith(b"$HELLO")
    assert s.state == ConnState.CONNECTED
    assert s.reconnects == 0
    events = [k for k, _ in s.drain_events()]
    assert events.count("connected") == 1
