"""Reader DDP/session tests. No USB MSC emulation and no physical card access."""
import pytest

from conftest import FakeClock
from daisy_diag import protocol as p
from daisy_diag.session import DeviceSession, ConnState
from daisy_diag.simulator import SimulatedCable, SimulatedDevice


def advance(clock, session, seconds=0.1):
    for _ in range(round(seconds / 0.005)):
        clock.advance(0.005)
        session.poll()


def setup(reader=True):
    clock = FakeClock()
    cable = SimulatedCable(lambda: SimulatedDevice(reader_supported=reader))
    session = DeviceSession(cable.ports, lambda port: cable.open(port, clock), clock, simulated=True)
    advance(clock, session)
    cable.device.inputs.sd_card = True
    advance(clock, session)
    return clock, cable, session


@pytest.mark.parametrize("state", ["LOCAL", "STARTING", "SHARED", "EJECTED", "INTERRUPTED", "ERROR"])
def test_reader_status_parser(state):
    info = p.parse_reader(p.parse_message(f"READER state={state} sectors=123 busy=0 a=STATUS"))
    assert info == p.ReaderInfo(state, 123, False)


@pytest.mark.parametrize("body", [
    "READER state=INVALID sectors=0 busy=0", "READER state=LOCAL busy=0",
    "READER state=LOCAL sectors=-1 busy=0", "READER state=LOCAL sectors=4294967296 busy=0",
    "READER state=LOCAL sectors=0 busy=2", "READER state=LOCAL sectors=0 busy=oops",
])
def test_bad_reader_fields(body):
    with pytest.raises(p.ProtocolError):
        p.parse_reader(p.parse_message(body + " a=STATUS"))


def test_status_requires_a_recognized_action():
    for suffix in ("", " a=INVALID"):
        with pytest.raises(p.ProtocolError):
            p.parse_reader(p.parse_message("READER state=LOCAL sectors=0 busy=0" + suffix))


def test_exclusive_handoff_eject_and_return():
    clock, cable, s = setup()
    assert s.reader_supported and s.reader.state == "LOCAL"
    assert s.request_reader("SHARE")
    assert not s.request_sd_test() and not s.request_reader("SHARE")
    advance(clock, s)
    assert s.reader.state == "SHARED" and not s.reader_pending
    assert not s.request_reader("RETURN") and not s.request_sd_test()
    # Firmware also refuses a raw command bypassing the GUI/session gate.
    assert s.send("SDTEST")
    advance(clock, s)
    assert any("ERR c=SDTEST e=BUSY" in str(v) for _, v in s.drain_events())
    cable.device.reader_eject()
    advance(clock, s)
    assert s.reader.state == "EJECTED"
    assert not s.request_sd_test()
    assert s.request_reader("RETURN")
    advance(clock, s)
    assert s.reader.state == "LOCAL" and s.reader.sectors == 0
    assert s.request_sd_test()
    advance(clock, s)
    assert s.sd.status == "MOUNTED"


def test_legacy_firmware_has_no_reader_controls():
    clock, cable, s = setup(reader=False)
    assert not s.reader_supported and s.reader is None
    assert not s.request_reader("SHARE")
    assert s.request_sd_test()
    advance(clock, s)
    assert s.sd.status == "MOUNTED"
    s.send("READER a=SHARE")
    advance(clock, s)
    assert cable.device.reader_state == "LOCAL"
    assert any("UNSUPPORTED" in str(v) for _, v in s.drain_events())


def test_slow_initialization_does_not_drop_cdc():
    clock, cable, s = setup()
    cable.device.reader_init_duration = 6
    assert s.request_reader("SHARE")
    advance(clock, s, 4)
    assert s.connected and s.reader_pending
    advance(clock, s, 3)
    assert s.connected and not s.reader_pending and s.reader.state == "SHARED"


def test_slow_shared_block_operation_has_bounded_receive_tolerance():
    clock, cable, s = setup()
    assert s.request_reader("SHARE")
    advance(clock, s)
    # Model a main-loop stall, not USB/block media emulation.
    cable.device._busy_until = clock() + 3.0
    cable.device._keepalive_after_block = True
    advance(clock, s, 2.5)
    assert s.connected
    advance(clock, s, 1)
    assert s.connected and s.reader.state == "SHARED"


def test_busy_transport_prevents_return_even_after_eject():
    clock, _, s = setup()
    s._handle("READER state=EJECTED sectors=8 busy=1 a=STATUS", clock())
    assert not s.request_reader("RETURN")
    s._handle("READER state=EJECTED sectors=8 busy=0 a=STATUS", clock())
    assert s.request_reader("RETURN")


def test_app_close_and_reconnect_do_not_revoke_windows_ownership():
    clock, cable, s = setup()
    s.request_reader("SHARE")
    advance(clock, s)
    s.disconnect()
    assert s.reader is None
    advance(clock, s, 4)
    assert s.connected and s.reader.state == "SHARED"
    assert not s.request_reader("RETURN")


@pytest.mark.parametrize("failure", ["remove", "reset"])
def test_interruption_requires_explicit_acknowledgement(failure):
    clock, cable, s = setup()
    s.request_reader("SHARE")
    advance(clock, s)
    if failure == "remove":
        cable.device.inputs.sd_card = False
        advance(clock, s, 1.1)
        cable.device.inputs.sd_card = True
    else:
        cable.device.reader_bus_reset()
    advance(clock, s, 1.1)
    assert s.reader.state == "INTERRUPTED"
    assert not s.request_sd_test() and not s.request_reader("SHARE")
    assert s.request_reader("RETURN")
    advance(clock, s)
    assert s.reader.state == "LOCAL"


def test_power_cycle_starts_unexported():
    clock, cable, s = setup()
    s.request_reader("SHARE")
    advance(clock, s)
    cable.unplug()
    advance(clock, s)
    assert s.reader is None
    cable.plug()
    advance(clock, s, 2)
    assert s.reader.state == "LOCAL" and not s.reader_pending


def test_timeout_never_reports_successful_eject():
    clock, cable, s = setup()
    s.request_reader("SHARE")
    advance(clock, s)
    cable.device.responsive = False
    assert s.request_reader("STATUS")
    advance(clock, s, 21)
    assert s.state != ConnState.CONNECTED
    assert s.reader is None
    assert cable.device.reader_state == "SHARED"


def test_periodic_status_cannot_acknowledge_a_different_pending_action():
    clock, _, s = setup()
    assert s.request_reader("SHARE")
    s._handle("READER state=LOCAL sectors=0 busy=0 a=STATUS", clock())
    assert s.reader_pending
    assert not s.request_sd_test()
    advance(clock, s)
    assert not s.reader_pending and s.reader.state == "SHARED"


def test_pending_sd_test_blocks_share_and_missing_card_blocks_share():
    clock, cable, s = setup()
    assert s.request_sd_test()
    assert not s.request_reader("SHARE")
    advance(clock, s)
    cable.device.inputs.sd_card = False
    advance(clock, s)
    assert not s.request_reader("SHARE")
    with pytest.raises(ValueError):
        s.request_reader("INVALID")
