// Host tests for the firmware main loop (diag::App) with fake board and USB sink.
// Covers the paths that main.cpp only wires to hardware: command/response flow,
// streaming, BYE, host timeout, RX ring, double-buffered TX and LED/SD requests.
#include "diag_app.h"
#include <cstdio>
#include <cstring>
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

class FakeUsb final : public diag::UsbSink {
  public:
    diag::SendResult mode = diag::SendResult::Ok;
    std::string delivered;
    int sends = 0;
    bool buffer_reused_in_flight = false;

    diag::SendResult Send(const uint8_t* data, size_t len) override {
        ++sends;
        if(mode != diag::SendResult::Ok)
            return mode;
        // The previously submitted buffer must not have been modified meanwhile.
        if(last_ptr_ && std::memcmp(last_ptr_, last_copy_.data(), last_copy_.size()) != 0)
            buffer_reused_in_flight = true;
        last_ptr_ = data;
        last_copy_.assign(data, data + len);
        delivered.append(reinterpret_cast<const char*>(data), len);
        return diag::SendResult::Ok;
    }

  private:
    const uint8_t* last_ptr_ = nullptr;
    std::vector<uint8_t> last_copy_;
};

class FakeBoard final : public diag::Board {
  public:
    diag::Inputs inputs;
    uint32_t ticks = 0;
    std::vector<std::pair<uint16_t, uint8_t>> led_writes;
    std::vector<bool> sd_calls;
    diag::SdResult sd_result;
    uint32_t* clock = nullptr;  // RunSdTest advances it to model a blocking test
    uint32_t sd_block_ms = 0;

    diag::Inputs ReadInputs() override { return inputs; }
    uint32_t ControlTicks() override { return ticks; }
    void ApplyLeds(uint16_t leds, uint8_t br) override { led_writes.emplace_back(leds, br); }
    diag::SdResult RunSdTest(bool card) override {
        sd_calls.push_back(card);
        if(clock)
            *clock += sd_block_ms;
        return sd_result;
    }
};

struct Rig {
    FakeBoard board;
    FakeUsb usb;
    uint32_t now = 1000;
    diag::App app{board, usb, "v6_1", 1000};
    ddp::FrameParser parser;
    size_t consumed = 0;

    void Host(const std::string& body) {
        char frame[ddp::kMaxFrame];
        const size_t n = ddp::BuildFrame(body.data(), body.size(), frame, sizeof(frame));
        app.OnUsbReceive(reinterpret_cast<const uint8_t*>(frame), static_cast<uint32_t>(n));
    }
    // Advances time in 1 ms main-loop steps (control ticks follow at 1 kHz).
    void Run(uint32_t ms) {
        for(uint32_t i = 0; i < ms; ++i) {
            ++now;
            ++board.ticks;
            app.Step(now);
        }
    }
    // Bodies delivered to the host since the previous call.
    std::vector<std::string> Received() {
        std::vector<std::string> out;
        for(; consumed < usb.delivered.size(); ++consumed)
            if(parser.Feed(usb.delivered[consumed]))
                out.emplace_back(parser.Body());
        return out;
    }
};

bool StartsWith(const std::string& s, const char* prefix) {
    return s.rfind(prefix, 0) == 0;
}

int Count(const std::vector<std::string>& bodies, const char* prefix) {
    int n = 0;
    for(const auto& b : bodies)
        n += StartsWith(b, prefix);
    return n;
}

void TestSilentUntilHello() {
    Rig r;
    r.Run(500);
    CHECK(r.Received().empty());
    r.Host("PING n=5");
    r.Run(1);
    auto got = r.Received();
    CHECK(got.size() == 1 && got[0] == "PONG n=5");
    r.Run(100);
    CHECK(r.Received().empty());  // PING alone does not start streaming
}

void TestHandshakeAndRate() {
    Rig r;
    r.Host("HELLO proto=1");
    r.Run(1);
    auto got = r.Received();
    CHECK(got.size() == 3);
    CHECK(got.size() == 3 && StartsWith(got[0], "HELLO proto=1 fw=0.2.0"));
    CHECK(got.size() == 3 && StartsWith(got[1], "ST n=0 "));
    CHECK(got.size() == 3 && StartsWith(got[2], "SYS "));
    for(int k = 0; k < 4; ++k) {  // keep the host alive with PINGs
        r.Run(250);
        r.Host("PING n=1");
    }
    r.Run(1);
    got = r.Received();
    const int st = Count(got, "ST ");
    CHECK(st >= 49 && st <= 51);  // 50 Hz default
    CHECK(Count(got, "SYS ") == 1);
    // sequence numbers are consecutive
    uint32_t expected = 1;
    for(const auto& b : got) {
        if(!StartsWith(b, "ST "))
            continue;
        char n[12];
        uint32_t seq = 0;
        CHECK(ddp::FindField(b.c_str(), "n", n, sizeof(n)) && ddp::ParseU32(n, seq));
        CHECK(seq == expected);
        expected = seq + 1;
    }
    CHECK(r.app.stats().control_rate_hz == 1000);
}

void TestImmediateFrameOnChange() {
    Rig r;
    r.Host("HELLO proto=1");
    r.Run(1);
    r.Received();
    r.Run(5);  // well inside the 20 ms period
    r.board.inputs.buttons = 0x0010;
    r.board.inputs.press_count[4] = 1;
    r.Run(1);  // 6 ms after the last frame
    auto got = r.Received();
    CHECK(Count(got, "ST ") == 0);  // minimum frame spacing of 10 ms is respected
    r.Run(4);  // 10 ms: change frame, well before the periodic one at 20 ms
    got = r.Received();
    CHECK(Count(got, "ST ") == 1);
    CHECK(!got.empty() && got[0].find("b=0010") != std::string::npos);
}

void TestByeIsAcknowledged() {
    Rig r;
    r.Host("HELLO proto=1");
    r.Run(50);
    r.Received();
    r.Host("BYE");
    r.Run(1);
    auto got = r.Received();
    CHECK(!got.empty() && got.back() == "ACK c=BYE");
    CHECK(r.app.stats().tx_drop == 0);
    r.Run(200);
    CHECK(r.Received().empty());
}

void TestTimeoutNeedsNewHello() {
    Rig r;
    r.Host("HELLO proto=1");
    r.Run(2990);
    CHECK(Count(r.Received(), "ST ") > 100);
    r.Run(20);  // 3 s without a host frame
    r.Received();
    r.Run(100);
    CHECK(r.Received().empty());
    r.Host("PING n=9");
    r.Run(100);
    auto got = r.Received();
    CHECK(got.size() == 1 && got[0] == "PONG n=9");  // answered, but no stream
    r.Host("HELLO proto=1");
    r.Run(100);
    got = r.Received();
    CHECK(!got.empty() && StartsWith(got[0], "HELLO "));
    CHECK(Count(got, "ST ") >= 5);
}

void TestNotReadyDiscards() {
    Rig r;
    r.usb.mode = diag::SendResult::NotReady;  // e.g. powered from a charger, no host
    r.Host("PING n=1");
    r.Run(10);
    CHECK(r.usb.delivered.empty());
    CHECK(r.app.stats().tx_drop == 1);
    r.usb.mode = diag::SendResult::Ok;
    r.Host("PING n=2");
    r.Run(1);
    auto got = r.Received();
    CHECK(got.size() == 1 && got[0] == "PONG n=2");
}

void TestBusyEndpointBuffersAndDrops() {
    Rig r;
    r.Host("HELLO proto=1");
    r.Run(1);
    r.Received();
    r.usb.mode = diag::SendResult::Busy;  // host stopped reading
    for(int k = 0; k < 8; ++k) {
        r.Run(250);
        r.Host("PING n=1");
    }
    CHECK(r.usb.delivered.size() == r.consumed);
    CHECK(r.app.stats().tx_busy > 1000);
    CHECK(r.app.stats().tx_drop > 0);  // 1536-byte buffer full
    r.usb.mode = diag::SendResult::Ok;
    r.Run(100);
    auto got = r.Received();
    CHECK(Count(got, "ST ") >= 5);
    for(int k = 0; k < 20; ++k)
        r.Run(50);
    CHECK(!r.usb.buffer_reused_in_flight);
    CHECK(r.parser.bad_crc == 0);
}

void TestNewSessionDropsStaleOutput() {
    Rig r;
    r.Host("HELLO proto=1");
    r.Run(1);
    r.Received();
    r.usb.mode = diag::SendResult::Busy;  // previous host closed the port without BYE
    r.Run(200);
    const uint32_t dropped_before = r.app.stats().tx_drop;
    r.usb.mode = diag::SendResult::Ok;
    r.Host("HELLO proto=1");  // in the same step the stale frames would be sent
    r.Run(1);
    auto got = r.Received();
    CHECK(!got.empty() && StartsWith(got[0], "HELLO proto=1"));
    CHECK(r.app.stats().tx_drop == dropped_before + 1);
}

void TestRxOverflowAndResync() {
    Rig r;
    std::string junk(3000, 'x');
    r.app.OnUsbReceive(reinterpret_cast<const uint8_t*>(junk.data()),
                       static_cast<uint32_t>(junk.size()));
    r.Run(1);
    CHECK(r.app.stats().rx_bad >= 3000 - diag::App::kRxSize);
    r.Host("PING n=77");
    r.Run(1);
    auto got = r.Received();
    CHECK(got.size() == 1 && got[0] == "PONG n=77");
    r.Host("NOPE");
    r.Run(1);
    got = r.Received();
    CHECK(got.size() == 1 && got[0] == "ERR c=NOPE e=UNKNOWN");
}

void TestRingWrapAndFull() {
    diag::SpscRing<16> ring(0xfffffff0u);  // free-running indices wrap during the test
    uint8_t value = 0;
    uint8_t expect = 0;
    for(int round = 0; round < 40; ++round) {
        uint8_t block[5];
        for(auto& b : block)
            b = value++;
        CHECK(ring.Push(block, sizeof(block)) == sizeof(block));
        uint8_t out = 0;
        for(int k = 0; k < 5; ++k) {
            CHECK(ring.Pop(out));
            CHECK(out == expect);
            ++expect;
        }
        CHECK(ring.Size() == 0);
    }
    uint8_t many[20] = {};
    CHECK(ring.Push(many, sizeof(many)) == 16);
    CHECK(ring.Size() == 16 && ring.Overflow() == 4);
    CHECK(ring.Push(many, 1) == 0);
    CHECK(ring.Overflow() == 5);
    uint8_t out;
    int popped = 0;
    while(ring.Pop(out))
        ++popped;
    CHECK(popped == 16 && !ring.Pop(out));
}

void TestLeds() {
    Rig r;
    r.Run(1);
    CHECK(r.board.led_writes.size() == 1 && r.board.led_writes[0].first == 0);  // initial
    r.board.inputs.buttons = 0x0001;  // FOLLOW is the power-up default
    r.Run(1);
    CHECK(r.board.led_writes.size() == 1);  // rate limited to one write per 10 ms
    r.Run(10);
    CHECK(r.board.led_writes.size() == 2 && r.board.led_writes.back().first == 0x0001);
    r.Host("LED m=MASK mask=8001 br=40");
    r.Run(20);
    CHECK(r.board.led_writes.back() == std::make_pair(uint16_t{0x8001}, uint8_t{40}));
    const size_t writes = r.board.led_writes.size();
    r.Run(500);
    CHECK(r.board.led_writes.size() == writes);  // unchanged state is not rewritten
    r.Host("LED m=CHASE ms=20");
    r.Run(400);
    CHECK(r.board.led_writes.size() >= writes + 19);
    r.Host("LED m=ON br=100000000000");  // rejected as a whole
    r.Run(20);
    CHECK(r.app.settings().led_mode == diag::LedMode::Chase);
}

void TestSdRequest() {
    Rig r;
    r.Host("SDTEST");
    r.Run(1);
    CHECK(r.board.sd_calls.size() == 1 && !r.board.sd_calls[0]);
    auto got = r.Received();
    CHECK(got.size() == 1 && got[0] == "SD st=NONE res=-1");  // answered without HELLO
    r.board.inputs.sd_card = true;
    r.board.sd_result.status = diag::SdStatus::Mounted;
    r.board.sd_result.fresult = 0;
    r.board.sd_result.fs_type = "FAT32";
    r.board.sd_result.size_mb = 100;
    r.board.sd_result.entries = 3;
    r.Host("SDTEST");
    r.Run(1);
    CHECK(r.board.sd_calls.size() == 2 && r.board.sd_calls[1]);
    got = r.Received();
    CHECK(got.size() == 1 && got[0] == "SD st=MOUNTED res=0 fs=FAT32 mb=100 ent=3");
}
void TestBlockingSdTestKeepsStream() {
    // The main loop is blocked for 6 s inside the SD test. Keep-alives sent by the host
    // meanwhile are queued and processed afterwards; the stream must continue.
    Rig r;
    r.board.clock = &r.now;
    r.board.sd_block_ms = 6000;
    r.board.inputs.sd_card = true;
    r.Host("HELLO proto=1");
    r.Run(100);
    r.Received();
    r.Host("SDTEST");
    r.Run(1);  // blocks: now jumps by 6 s
    for(int k = 0; k < 12; ++k)
        r.Host("PING n=1");  // queued in the RX ring while blocked
    r.Run(200);
    auto got = r.Received();
    CHECK(Count(got, "SD st=") == 1);
    CHECK(Count(got, "PONG ") == 12);
    CHECK(Count(got, "ST ") >= 9);
    CHECK(r.app.HostActive(r.now));
}
} // namespace

int main() {
    TestSilentUntilHello();
    TestHandshakeAndRate();
    TestImmediateFrameOnChange();
    TestByeIsAcknowledged();
    TestTimeoutNeedsNewHello();
    TestNotReadyDiscards();
    TestBusyEndpointBuffersAndDrops();
    TestNewSessionDropsStaleOutput();
    TestRxOverflowAndResync();
    TestRingWrapAndFull();
    TestLeds();
    TestSdRequest();
    TestBlockingSdTestKeepsStream();
    std::printf("%s: %d checks, %d failures\n", failures ? "FAIL" : "PASS", checks, failures);
    return failures ? 1 : 0;
}
