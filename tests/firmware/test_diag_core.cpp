// Host tests for the firmware's protocol and diagnostic logic (no libDaisy, no hardware).
// Usage: test_diag_core <path to diagnostics/protocol/vectors.txt>
#include "ddp.h"
#include "diag_core.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

namespace {
int failures = 0;
int checks = 0;

#define CHECK(cond)                                                             \
    do {                                                                        \
        ++checks;                                                               \
        if(!(cond)) {                                                           \
            ++failures;                                                         \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);         \
        }                                                                       \
    } while(0)

#define CHECK_STR(actual, expected)                                             \
    do {                                                                        \
        ++checks;                                                               \
        if(std::string(actual) != std::string(expected)) {                      \
            ++failures;                                                         \
            std::printf("FAIL %s:%d:\n  got:      %s\n  expected: %s\n",        \
                        __FILE__, __LINE__, std::string(actual).c_str(),        \
                        std::string(expected).c_str());                         \
        }                                                                       \
    } while(0)

std::string Frame(const std::string& body) {
    char out[ddp::kMaxFrame];
    const size_t n = ddp::BuildFrame(body.data(), body.size(), out, sizeof(out));
    return std::string(out, n);
}

// Feeds bytes and returns all bodies that were accepted.
std::vector<std::string> FeedAll(ddp::FrameParser& p, const std::string& bytes) {
    std::vector<std::string> bodies;
    for(char c : bytes)
        if(p.Feed(c))
            bodies.emplace_back(p.Body(), p.BodyLength());
    return bodies;
}

void TestVectors(const char* path) {
    std::ifstream file(path);
    CHECK(file.good());
    std::string line;
    int count = 0;
    while(std::getline(file, line)) {
        if(line.empty() || line[0] == '#')
            continue;
        if(!line.empty() && line.back() == '\r')
            line.pop_back();
        const size_t tab = line.find('\t');
        CHECK(tab == 4);
        const std::string body = line.substr(tab + 1);
        const unsigned expected = std::stoul(line.substr(0, 4), nullptr, 16);
        CHECK(ddp::Crc16(body.data(), body.size()) == expected);
        // Every vector must also survive a frame round trip.
        ddp::FrameParser p;
        auto got = FeedAll(p, Frame(body));
        CHECK(got.size() == 1 && got[0] == body);
        ++count;
    }
    CHECK(count >= 10);
}

void TestFraming() {
    CHECK_STR(Frame("123456789"), "$123456789*29B1\n");
    char out[32];
    CHECK(ddp::BuildFrame("", 0, out, sizeof(out)) == 0);
    CHECK(ddp::BuildFrame("A$B", 3, out, sizeof(out)) == 0);
    CHECK(ddp::BuildFrame("A*B", 3, out, sizeof(out)) == 0);
    CHECK(ddp::BuildFrame("A\nB", 3, out, sizeof(out)) == 0);
    CHECK(ddp::BuildFrame("ABCDEFGH", 8, out, 14) == 0);  // needs 15
    CHECK(ddp::BuildFrame("ABCDEFGH", 8, out, 15) == 15);
    const std::string max_body(ddp::kMaxBody, 'x');
    CHECK(Frame(max_body).size() == ddp::kMaxFrame);
    const std::string too_long(ddp::kMaxBody + 1, 'x');
    char big[ddp::kMaxFrame + 8];
    CHECK(ddp::BuildFrame(too_long.data(), too_long.size(), big, sizeof(big)) == 0);
}

void TestParserResync() {
    ddp::FrameParser p;
    // Noise before a frame, split delivery, CRLF, lowercase CRC.
    auto got = FeedAll(p, "\x01garbage\n" + Frame("PING n=1"));
    CHECK(got.size() == 1 && got[0] == "PING n=1");
    std::string crlf = Frame("GET");
    crlf.insert(crlf.size() - 1, "\r");
    got = FeedAll(p, crlf);
    CHECK(got.size() == 1 && got[0] == "GET");
    std::string lower = Frame("BYE");
    for(auto& c : lower)
        if(c >= 'A' && c <= 'F' && &c > &lower[4])
            c = static_cast<char>(c - 'A' + 'a');
    got = FeedAll(p, lower);
    CHECK(got.size() == 1 && got[0] == "BYE");

    // Truncated frame followed by a valid one: the partial frame is dropped.
    p = ddp::FrameParser();
    got = FeedAll(p, "$ST n=1 b=00" + Frame("PING n=2"));
    CHECK(got.size() == 1 && got[0] == "PING n=2");
    CHECK(p.bad_format == 1);

    // Wrong CRC.
    p = ddp::FrameParser();
    got = FeedAll(p, "$PING n=1*0000\n" + Frame("PING n=3"));
    CHECK(got.size() == 1 && got[0] == "PING n=3");
    CHECK(p.bad_crc == 1);

    // Invalid characters, missing '*', non-hex CRC, empty body.
    p = ddp::FrameParser();
    got = FeedAll(p, std::string("$PI\x07NG*1234\n") + "$PING n=1\n" + "$PING*12G4\n"
                         + "$*FFFF\n" + Frame("GET"));
    CHECK(got.size() == 1 && got[0] == "GET");
    CHECK(p.bad_format == 4);

    // Missing newline after CRC.
    p = ddp::FrameParser();
    got = FeedAll(p, "$GET*" + Frame("GET").substr(5, 4) + "X" + Frame("BYE"));
    CHECK(got.size() == 1 && got[0] == "BYE");

    // Overflow.
    p = ddp::FrameParser();
    got = FeedAll(p, "$" + std::string(ddp::kMaxBody + 5, 'a') + "*0000\n" + Frame("GET"));
    CHECK(got.size() == 1 && got[0] == "GET");
    CHECK(p.overflow == 1);
    CHECK(p.ok == 1);

    // Many frames back to back, byte by byte.
    p = ddp::FrameParser();
    std::string stream;
    for(int i = 0; i < 50; ++i)
        stream += Frame("PING n=" + std::to_string(i));
    got = FeedAll(p, stream);
    CHECK(got.size() == 50 && got[49] == "PING n=49");
}

void TestFields() {
    char v[16];
    CHECK(ddp::FindField("LED m=MASK mask=8001 br=50", "m", v, sizeof(v)));
    CHECK_STR(v, "MASK");
    CHECK(ddp::FindField("LED m=MASK mask=8001 br=50", "mask", v, sizeof(v)));
    CHECK_STR(v, "8001");
    CHECK(ddp::FindField("LED m=MASK mask=8001 br=50", "br", v, sizeof(v)));
    CHECK_STR(v, "50");
    CHECK(!ddp::FindField("LED m=MASK", "ms", v, sizeof(v)));
    CHECK(!ddp::FindField("m=1 x=2", "m", v, sizeof(v)));  // first token is the type
    CHECK(!ddp::FindField("LED m=0123456789ABCDEFG", "m", v, sizeof(v)));
    CHECK(ddp::FindField("LED  m=ON", "m", v, sizeof(v)));
    CHECK_STR(v, "ON");
    CHECK(ddp::FindField("X e=", "e", v, sizeof(v)));
    CHECK_STR(v, "");

    ddp::MessageType("HELLO proto=1", v, sizeof(v));
    CHECK_STR(v, "HELLO");
    ddp::MessageType("VERYLONGMESSAGETYPE", v, 5);
    CHECK_STR(v, "VERY");

    uint32_t n = 0;
    CHECK(ddp::ParseU32("4294967295", n) && n == 4294967295u);
    CHECK(!ddp::ParseU32("4294967296", n));
    CHECK(!ddp::ParseU32("", n));
    CHECK(!ddp::ParseU32("12a", n));
    CHECK(!ddp::ParseU32("-1", n));
    CHECK(ddp::ParseHex("ffff", n) && n == 0xffff);
    CHECK(ddp::ParseHex("FFFFFFFF", n) && n == 0xffffffffu);
    CHECK(!ddp::ParseHex("100000000", n));
    CHECK(!ddp::ParseHex("0x10", n));

    char small[8];
    ddp::Writer w(small, sizeof(small));
    w.Str("ABCDEFG");
    CHECK(w.Ok() && w.Length() == 7);
    w.Char('H');
    CHECK(!w.Ok() && w.Length() == 7);
    CHECK_STR(w.CStr(), "ABCDEFG");
    char num[16];
    ddp::Writer u(num, sizeof(num));
    u.U32(0).Char(' ').U32(4294967295u).Char(' ').Hex(0x1a, 2);
    CHECK_STR(u.CStr(), "0 4294967295 1A");
}

void TestButtons() {
    diag::ButtonTracker t;
    for(size_t i = 0; i < diag::kNumButtons; ++i) {
        t.Update(i, true, false);
        CHECK(t.Held() == static_cast<uint16_t>((2u << i) - 1));  // S1..S(i+1) held
        CHECK(t.PressCount(i) == 1);
    }
    // Repeated rising edge after a short dropout is not a new press.
    t.Update(3, true, false);
    CHECK(t.PressCount(3) == 1);
    for(size_t i = 0; i < diag::kNumButtons; ++i)
        t.Update(i, false, true);
    CHECK(t.Held() == 0);
    // Counter is modulo 256.
    for(int k = 0; k < 255; ++k) {
        t.Update(15, true, false);
        t.Update(15, false, true);
    }
    CHECK(t.PressCount(15) == 0);
    CHECK(t.PressCount(14) == 1);
}

void TestSwitch3() {
    diag::Switch3Debouncer d;
    CHECK(d.Update(diag::Sw18::Up) == diag::Sw18::Up);  // first read is adopted
    for(int i = 0; i < diag::Switch3Debouncer::kStableReads - 1; ++i)
        CHECK(d.Update(diag::Sw18::Down) == diag::Sw18::Up);
    CHECK(d.Update(diag::Sw18::Up) == diag::Sw18::Up);  // glitch rejected
    for(int i = 0; i < diag::Switch3Debouncer::kStableReads - 1; ++i)
        d.Update(diag::Sw18::Center);
    CHECK(d.Position() == diag::Sw18::Up);
    CHECK(d.Update(diag::Sw18::Center) == diag::Sw18::Center);
    for(int i = 0; i < diag::Switch3Debouncer::kStableReads; ++i)
        d.Update(diag::Sw18::Down);
    CHECK(d.Position() == diag::Sw18::Down);
}

void TestLeds() {
    diag::Settings s;
    CHECK(s.led_mode == diag::LedMode::Follow);  // default after power-up
    CHECK(diag::ComputeLeds(s, 0, 0x0105) == 0x0105);
    s.led_mode = diag::LedMode::Off;
    CHECK(diag::ComputeLeds(s, 0, 0xffff) == 0);
    s.led_mode = diag::LedMode::On;
    CHECK(diag::ComputeLeds(s, 0, 0) == 0xffff);
    s.led_mode = diag::LedMode::Mask;
    for(size_t i = 0; i < diag::kNumLeds; ++i) {
        s.led_mask = static_cast<uint16_t>(1u << i);
        CHECK(diag::ComputeLeds(s, 12345, 0xffff) == s.led_mask);
    }
    s.led_mode = diag::LedMode::Chase;
    s.chase_step_ms = 100;
    for(uint32_t step = 0; step < 40; ++step)
        CHECK(diag::ComputeLeds(s, step * 100 + 50, 0) == (1u << (step % 16)));

    diag::LedMode m;
    CHECK(diag::ParseLedMode("CHASE", m) && m == diag::LedMode::Chase);
    CHECK(!diag::ParseLedMode("chase", m));
    CHECK_STR(diag::LedModeName(diag::LedMode::Follow), "FOLLOW");
}

std::string Handle(diag::Session& s, const char* body, uint32_t now, uint32_t* req = nullptr) {
    char buf[ddp::kMaxBody + 1];
    ddp::Writer w(buf, sizeof(buf));
    const uint32_t r = s.Handle(body, now, w);
    if(req)
        *req = r;
    return w.CStr();
}

void TestSession() {
    diag::Session s;
    s.Init("v6_1");
    uint32_t req = 0;
    CHECK(!s.HostActive(0));
    CHECK_STR(Handle(s, "PING n=7", 10), "PONG n=7");
    CHECK(!s.HostActive(10));  // ping alone does not start streaming
    CHECK_STR(Handle(s, "HELLO", 20), "ERR c=HELLO e=ARG");
    CHECK_STR(Handle(s, "HELLO proto=2", 20), "ERR c=HELLO e=PROTO");
    CHECK(!s.HostActive(20));
    CHECK_STR(Handle(s, "HELLO proto=1", 100, &req),
              "HELLO proto=1 fw=0.1.0 app=DaisyDiagnostic dev=seed3-desktop boot=BOOT_SRAM "
              "bl=v6_1 libdaisy=f715e48 caps=btn,pot,potraw,sw17,sw18,sd,sdread,jack,led");
    CHECK(req == diag::kRequestState);
    CHECK(s.HostActive(100));
    CHECK(s.HostActive(100 + diag::kHostTimeoutMs - 1));
    CHECK(!s.HostActive(100 + diag::kHostTimeoutMs));
    Handle(s, "PING n=1", 3000);
    CHECK(s.HostActive(5999));
    CHECK(!s.HostActive(6000));
    // Millisecond counter wrap-around.
    Handle(s, "PING n=2", 0xffffff00u);
    CHECK(s.HostActive(0x100));

    CHECK_STR(Handle(s, "GET", 1, &req), "");
    CHECK(req == diag::kRequestState);
    CHECK_STR(Handle(s, "SDTEST", 1, &req), "");
    CHECK(req == diag::kRequestSdTest);

    CHECK_STR(Handle(s, "RATE hz=20", 1), "ACK c=RATE hz=20");
    CHECK(s.settings.rate_hz == 20);
    CHECK_STR(Handle(s, "RATE hz=9", 1), "ERR c=RATE e=ARG");
    CHECK_STR(Handle(s, "RATE hz=101", 1), "ERR c=RATE e=ARG");
    CHECK_STR(Handle(s, "RATE", 1), "ERR c=RATE e=ARG");
    CHECK(s.settings.rate_hz == 20);

    CHECK_STR(Handle(s, "LED m=MASK mask=8001 br=50", 1, &req),
              "ACK c=LED m=MASK mask=8001 br=50 ms=120");
    CHECK(req == diag::kRequestLeds);
    CHECK_STR(Handle(s, "LED m=CHASE ms=20", 1), "ACK c=LED m=CHASE mask=8001 br=50 ms=20");
    CHECK_STR(Handle(s, "LED m=OFF", 1), "ACK c=LED m=OFF mask=8001 br=50 ms=20");
    // Invalid arguments leave all settings untouched.
    const diag::Settings before = s.settings;
    CHECK_STR(Handle(s, "LED m=BLINK", 1), "ERR c=LED e=ARG");
    CHECK_STR(Handle(s, "LED", 1), "ERR c=LED e=ARG");
    CHECK_STR(Handle(s, "LED m=ON mask=10000", 1), "ERR c=LED e=ARG");
    CHECK_STR(Handle(s, "LED m=ON mask=zz", 1), "ERR c=LED e=ARG");
    CHECK_STR(Handle(s, "LED m=ON br=101", 1), "ERR c=LED e=ARG");
    CHECK_STR(Handle(s, "LED m=ON ms=19", 1), "ERR c=LED e=ARG");
    CHECK_STR(Handle(s, "LED m=ON ms=2001", 1), "ERR c=LED e=ARG");
    CHECK(s.settings.led_mode == before.led_mode && s.settings.led_mask == before.led_mask
          && s.settings.led_brightness == before.led_brightness
          && s.settings.chase_step_ms == before.chase_step_ms);

    CHECK_STR(Handle(s, "FORMAT", 1), "ERR c=FORMAT e=UNKNOWN");
    CHECK_STR(Handle(s, "WRITE x=1", 1), "ERR c=WRITE e=UNKNOWN");

    Handle(s, "HELLO proto=1", 10);
    CHECK(s.HostActive(11));
    CHECK_STR(Handle(s, "BYE", 12), "ACK c=BYE");
    CHECK(!s.HostActive(13));
}

void TestStateFormat() {
    diag::Inputs in;
    in.buttons = 0x0001;
    in.press_count[0] = 1;
    in.pot_norm[1] = 10000;
    in.pot_norm[2] = 5000;
    in.pot_raw[1] = 65535;
    in.pot_raw[2] = 32768;
    in.sw17_up = true;
    in.sw18 = diag::Sw18::Center;
    in.jack_right = true;
    diag::Settings s;
    char buf[ddp::kMaxBody + 1];
    ddp::Writer w(buf, sizeof(buf));
    diag::WriteState(in, s, 0x0001, 1234, 56789, w);
    // Must equal the ST example in PROTOCOL.md / vectors.txt.
    CHECK_STR(w.CStr(),
              "ST n=1234 t=56789 b=0001 pc=01000000000000000000000000000000 "
              "p=0,10000,5000,0,0,0,0,0 r=0,65535,32768,0,0,0,0,0 s17=U s18=C sd=0 "
              "jl=0 jr=1 lm=FOLLOW l=0001 br=100");

    // Worst case length stays within one frame.
    diag::Inputs max;
    max.buttons = 0xffff;
    for(auto& c : max.press_count)
        c = 0xff;
    for(size_t i = 0; i < diag::kNumPots; ++i) {
        max.pot_norm[i] = 10000;
        max.pot_raw[i] = 65535;
    }
    s.led_mode = diag::LedMode::Follow;
    ddp::Writer wm(buf, sizeof(buf));
    diag::WriteState(max, s, 0xffff, 0xffffffffu, 0xffffffffu, wm);
    CHECK(wm.Ok());
    CHECK(wm.Length() < 300);

    // Every button, pot and switch is reflected in its own field.
    for(size_t i = 0; i < diag::kNumButtons; ++i) {
        diag::Inputs one;
        one.buttons = static_cast<uint16_t>(1u << i);
        ddp::Writer wb(buf, sizeof(buf));
        diag::WriteState(one, s, 0, 0, 0, wb);
        char field[8];
        CHECK(ddp::FindField(buf, "b", field, sizeof(field)));
        uint32_t mask = 0;
        CHECK(ddp::ParseHex(field, mask) && mask == (1u << i));
    }
    for(size_t i = 0; i < diag::kNumPots; ++i) {
        diag::Inputs one;
        one.pot_norm[i] = static_cast<uint16_t>(1000 + i);
        ddp::Writer wp(buf, sizeof(buf));
        diag::WriteState(one, s, 0, 0, 0, wp);
        char field[64];
        CHECK(ddp::FindField(buf, "p", field, sizeof(field)));
        std::string expected;
        for(size_t k = 0; k < diag::kNumPots; ++k)
            expected += (k ? "," : "") + std::to_string(k == i ? 1000 + i : 0);
        CHECK_STR(field, expected);
    }
    const struct {
        diag::Sw18 pos;
        const char* text;
    } sw18[] = {{diag::Sw18::Up, "U"}, {diag::Sw18::Center, "C"}, {diag::Sw18::Down, "D"}};
    for(const auto& c : sw18) {
        diag::Inputs one;
        one.sw18 = c.pos;
        ddp::Writer ws(buf, sizeof(buf));
        diag::WriteState(one, s, 0, 0, 0, ws);
        char field[4];
        CHECK(ddp::FindField(buf, "s18", field, sizeof(field)));
        CHECK_STR(field, c.text);
        CHECK(ddp::FindField(buf, "s17", field, sizeof(field)));
        CHECK_STR(field, "D");
    }

    diag::Inputs a, b;
    CHECK(!diag::DigitalChanged(a, b));
    b.pot_norm[3] = 99;  // pots alone do not trigger an immediate frame
    CHECK(!diag::DigitalChanged(a, b));
    b.press_count[7] = 1;
    CHECK(diag::DigitalChanged(a, b));
    b = a;
    b.sd_card = true;
    CHECK(diag::DigitalChanged(a, b));
    b = a;
    b.sw18 = diag::Sw18::Down;
    CHECK(diag::DigitalChanged(a, b));
}

void TestMisc() {
    CHECK(diag::NormalizePot(0.f) == 0);
    CHECK(diag::NormalizePot(-0.1f) == 0);
    CHECK(diag::NormalizePot(std::nanf("")) == 0);
    CHECK(diag::NormalizePot(0.5f) == 5000);
    CHECK(diag::NormalizePot(0.99995f) == 10000);
    CHECK(diag::NormalizePot(1.2f) == 10000);

    char buf[128];
    diag::Stats st;
    st.uptime_s = 123;
    st.control_rate_hz = 1000;
    st.tx_ok = 6150;
    st.tx_busy = 3;
    st.rx_ok = 250;
    ddp::Writer w(buf, sizeof(buf));
    diag::WriteSys(st, true, 50, w);
    CHECK_STR(buf, "SYS up=123 cbhz=1000 txok=6150 txbusy=3 txdrop=0 rxok=250 rxbad=0 host=1 rate=50");

    diag::SdResult sd;
    ddp::Writer w1(buf, sizeof(buf));
    diag::WriteSd(sd, w1);
    CHECK_STR(buf, "SD st=NONE res=-1");
    sd.status = diag::SdStatus::Mounted;
    sd.fresult = 0;
    sd.fs_type = "FAT32";
    sd.size_mb = 30436;
    sd.entries = 12;
    ddp::Writer w2(buf, sizeof(buf));
    diag::WriteSd(sd, w2);
    CHECK_STR(buf, "SD st=MOUNTED res=0 fs=FAT32 mb=30436 ent=12");
    sd.status = diag::SdStatus::Error;
    sd.fresult = 13;
    ddp::Writer w3(buf, sizeof(buf));
    diag::WriteSd(sd, w3);
    CHECK_STR(buf, "SD st=ERROR res=13");
}
} // namespace

int main(int argc, char** argv) {
    if(argc < 2) {
        std::printf("usage: %s <vectors.txt>\n", argv[0]);
        return 2;
    }
    TestVectors(argv[1]);
    TestFraming();
    TestParserResync();
    TestFields();
    TestButtons();
    TestSwitch3();
    TestLeds();
    TestSession();
    TestStateFormat();
    TestMisc();
    std::printf("%s: %d checks, %d failures\n", failures ? "FAIL" : "PASS", checks, failures);
    return failures ? 1 : 0;
}
