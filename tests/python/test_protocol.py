import binascii

import pytest

from conftest import VECTORS
from daisy_diag import protocol as p


def load_vectors():
    out = []
    for line in VECTORS.read_text(encoding="ascii").splitlines():
        if line and not line.startswith("#"):
            crc, body = line.split("\t", 1)
            out.append((int(crc, 16), body))
    return out


def test_crc_check_value():
    assert p.crc16(b"123456789") == 0x29B1


@pytest.mark.parametrize("crc,body", load_vectors())
def test_vectors_match_crc_and_round_trip(crc, body):
    assert p.crc16(body.encode()) == crc
    # independent reference implementation from the standard library
    assert binascii.crc_hqx(body.encode(), 0xFFFF) == crc
    parser = p.FrameParser()
    assert parser.feed(p.build_frame(body)) == [body]


def test_build_frame_layout_and_rejections():
    assert p.build_frame("123456789") == b"$123456789*29B1\n"
    for bad in ("", "A$B", "A*B", "A\nB", "ä", "x" * (p.MAX_BODY + 1)):
        with pytest.raises(ValueError):
            p.build_frame(bad)
    assert len(p.build_frame("x" * p.MAX_BODY)) == p.MAX_BODY + 7


def test_parser_resynchronises_after_noise_and_truncation():
    parser = p.FrameParser()
    data = b"\x00\xffgarbage\n$ST n=1 b=00" + p.build_frame("PING n=2")
    assert parser.feed(data) == ["PING n=2"]
    assert parser.bad_format == 1


def test_parser_split_delivery_crlf_and_lowercase():
    parser = p.FrameParser()
    frame = p.build_frame("GET").replace(b"\n", b"\r\n")
    got = []
    for i in range(len(frame)):
        got += parser.feed(frame[i:i + 1])
    assert got == ["GET"]
    lower = p.build_frame("BYE")
    lower = lower[:5] + lower[5:9].lower() + lower[9:]
    assert parser.feed(lower) == ["BYE"]


def test_parser_counts_errors():
    parser = p.FrameParser()
    data = (b"$PING n=1*0000\n"        # wrong CRC
            b"$PI\x07NG*1234\n"        # invalid char
            b"$PING n=1\n"             # missing '*'
            b"$PING*12G4\n"            # non-hex CRC
            b"$*FFFF\n"                # empty body
            b"$" + b"a" * (p.MAX_BODY + 3) + b"*0000\n"  # overflow
            + p.build_frame("GET"))
    assert parser.feed(data) == ["GET"]
    assert (parser.bad_crc, parser.bad_format, parser.overflow, parser.ok) == (1, 4, 1, 1)
    assert parser.errors == 6


def test_parse_message_fields():
    msg = p.parse_message("LED m=MASK  mask=8001 br=50 flag")
    assert msg.type == "LED"
    assert msg.fields == {"m": "MASK", "mask": "8001", "br": "50"}
    assert msg.hex4("mask") == 0x8001
    assert msg.int("br", 0, 100) == 50
    with pytest.raises(p.ProtocolError):
        msg.int("missing")
    with pytest.raises(p.ProtocolError):
        msg.int("br", 0, 10)


ST_EXAMPLE = [b for _, b in load_vectors() if b.startswith("ST ")][0]


def test_state_example_round_trip_matches_firmware_layout():
    state = p.parse_state(p.parse_message(ST_EXAMPLE))
    assert state.seq == 1234 and state.time_ms == 56789
    assert state.buttons[0] and not any(state.buttons[1:])
    assert state.press_counts[0] == 1
    assert state.pots[1] == 1.0 and state.pots[2] == 0.5
    assert state.pots_raw[1] == 65535
    assert (state.sw17, state.sw18, state.sd_card, state.jack_left, state.jack_right) == \
        ("U", "C", False, False, True)
    assert state.led_mode == "FOLLOW" and state.leds[0] and state.led_brightness == 100
    # the host formatter produces byte-identical output to the firmware (C++ test)
    assert p.format_state(state) == ST_EXAMPLE


@pytest.mark.parametrize("index", range(p.NUM_BUTTONS))
def test_each_button_and_led_bit(index):
    state = p.BoardState(buttons=[i == index for i in range(16)],
                         leds=[i == index for i in range(16)])
    msg = p.parse_message(p.format_state(state))
    assert int(msg.get("b"), 16) == 1 << index
    assert int(msg.get("l"), 16) == 1 << index
    assert p.parse_state(msg).buttons.index(True) == index


@pytest.mark.parametrize("index", range(p.NUM_POTS))
def test_each_pot(index):
    state = p.BoardState()
    state.pots[index] = 0.4321
    state.pots_raw[index] = 28318
    back = p.parse_state(p.parse_message(p.format_state(state)))
    assert back.pots[index] == pytest.approx(0.4321)
    assert back.pots_raw[index] == 28318
    assert sum(back.pots) == pytest.approx(0.4321)


@pytest.mark.parametrize("bad", [
    ST_EXAMPLE.replace("p=0,10000,", "p=0,10001,"),
    ST_EXAMPLE.replace("p=0,10000,5000,0,0,0,0,0", "p=0,1"),
    ST_EXAMPLE.replace("s18=C", "s18=X"),
    ST_EXAMPLE.replace("s17=U", "s17=C"),
    ST_EXAMPLE.replace("lm=FOLLOW", "lm=BLINK"),
    ST_EXAMPLE.replace("pc=01", "pc=0"),
    ST_EXAMPLE.replace("sd=0", "sd=2"),
    ST_EXAMPLE.replace(" b=0001", ""),
    ST_EXAMPLE.replace("b=0001", "b=zz"),
    # P11: values int() would accept but the protocol does not
    ST_EXAMPLE.replace("n=1234", "n=-1"),
    ST_EXAMPLE.replace("n=1234", "n=+5"),
    ST_EXAMPLE.replace("n=1234", "n=4294967296"),
    ST_EXAMPLE.replace("t=56789", "t=1_000"),
    ST_EXAMPLE.replace("pc=01", "pc=-1"),
    ST_EXAMPLE.replace("pc=01", "pc=+1"),
    ST_EXAMPLE.replace("br=100", "br=999"),
    ST_EXAMPLE.replace("b=0001", "b=001"),
    ST_EXAMPLE.replace("b=0001", "b=10000"),
    ST_EXAMPLE.replace("l=0001", "l=-001"),
    ST_EXAMPLE.replace("p=0,10000,", "p=0,+10000,"),
    ST_EXAMPLE.replace("r=0,65535,", "r=0,65_535,"),
])
def test_invalid_state_content_is_rejected(bad):
    with pytest.raises(p.ProtocolError):
        p.parse_state(p.parse_message(bad))


def test_pot_rounding_matches_firmware():
    assert p.pot_to_int(float("nan")) == 0
    assert p.pot_to_int(-0.1) == 0
    assert p.pot_to_int(0.5) == 5000
    assert p.pot_to_int(0.99995) == 10000
    assert p.pot_to_int(1.2) == 10000


def test_commands():
    assert p.cmd_hello() == "HELLO proto=1"
    assert p.cmd_led("MASK", mask=0x8001, brightness=50) == "LED m=MASK mask=8001 br=50"
    assert p.cmd_led("CHASE", step_ms=5) == "LED m=CHASE ms=20"
    assert p.cmd_rate(500) == "RATE hz=100"
    with pytest.raises(ValueError):
        p.cmd_led("BLINK")


def test_sd_and_sys_and_hello():
    sd = p.parse_sd(p.parse_message("SD st=MOUNTED res=0 fs=FAT32 mb=30436 ent=12"))
    assert (sd.status, sd.fs_type, sd.size_mb, sd.entries) == ("MOUNTED", "FAT32", 30436, 12)
    assert p.parse_sd(p.parse_message("SD st=ERROR res=13")).fresult == 13
    assert p.parse_sd(p.parse_message("SD st=NONE res=-1")).status == "NONE"
    with pytest.raises(p.ProtocolError):
        p.parse_sd(p.parse_message("SD st=WEIRD res=0"))
    with pytest.raises(p.ProtocolError):
        p.parse_sd(p.parse_message("SD st=MOUNTED res=0 fs=FAT32 mb=-5 ent=1"))
    with pytest.raises(p.ProtocolError):
        p.parse_sys(p.parse_message("SYS up=1 cbhz=1000 txok=1 txbusy=0 txdrop=0 rxok=1 "
                                    "rxbad=0 host=1 rate=500"))
    body = [b for _, b in load_vectors() if b.startswith("SYS ")][0]
    sys_info = p.parse_sys(p.parse_message(body))
    assert sys_info.control_rate_hz == 1000 and sys_info.rate_hz == 50
    hello = [b for _, b in load_vectors() if b.startswith("HELLO proto=1 fw")][0]
    info = p.parse_hello(p.parse_message(hello))
    assert info.protocol == 1 and info.boot == "BOOT_SRAM" and "led" in info.capabilities
    assert not info.simulated
