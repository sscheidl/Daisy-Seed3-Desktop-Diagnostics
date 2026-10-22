#include "msc_bot.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <vector>

int checks = 0, failures = 0;
#define CHECK(x) do { ++checks; if(!(x)) { ++failures; std::printf("FAIL line %d: %s\n", __LINE__, #x); } } while(0)
class Card : public diag::CardDevice {
  public:
    std::array<uint8_t, 4096> bytes{};
    bool open_ok = true, read_ok = true, write_ok = true, sync_ok = true;
    unsigned reads = 0, writes = 0, syncs = 0, closes = 0;
    bool Open(uint32_t& sectors) override { sectors = 8; return open_ok; }
    bool Read(uint32_t lba, uint8_t* data) override {
        ++reads; if(!read_ok) return false;
        std::memcpy(data, bytes.data() + lba * 512, 512); return true;
    }
    bool Write(uint32_t lba, const uint8_t* data) override {
        ++writes; if(!write_ok) return false;
        std::memcpy(bytes.data() + lba * 512, data, 512); return true;
    }
    bool Sync() override { ++syncs; return sync_ok; }
    void Close() override { ++closes; }
};
class Port : public diag::MscPort {
  public:
    std::vector<std::vector<uint8_t>> packets;
    uint16_t receive = 0;
    bool halt_in = false, halt_out = false;
    void Send(const uint8_t* p, uint16_t n) override { packets.emplace_back(p, p + n); }
    void Receive(uint16_t n) override { receive = n; }
    void Halt(bool in) override { (in ? halt_in : halt_out) = true; }
};
using Command = std::array<uint8_t, 31>;
Command Cbw(uint8_t opcode, uint32_t bytes = 0, bool in = false) {
    Command c{};
    c[0] = 'U'; c[1] = 'S'; c[2] = 'B'; c[3] = 'C';
    c[4] = 0x78; c[5] = 0x56; c[6] = 0x34; c[7] = 0x12;
    for(unsigned i = 0; i < 4; ++i) c[8 + i] = uint8_t(bytes >> (8 * i));
    c[12] = in ? 0x80 : 0; c[14] = 10; c[15] = opcode;
    return c;
}
struct Rig {
    Card card;
    diag::CardReader reader{card};
    Port port;
    diag::MscBot bot{reader, port};
    Rig() { bot.Configure(); }
    void Send(Command c) { bot.Out(c.data(), c.size()); }
    bool Share() {
        if(!reader.Share(true)) return false;
        Send(Cbw(0x00)); Status(1);  // consume UNIT ATTENTION after explicit share
        return true;
    }
    void Status(uint8_t value, uint32_t residue = 0) {
        if(port.halt_in && !port.packets.empty() && port.packets.back().size() != 13) {
            bot.ClearHalt(true); port.halt_in = false;
        }
        CHECK(!port.packets.empty());
        if(port.packets.empty()) return;
        auto p = port.packets.back();
        CHECK(p.size() == 13);
        if(p.size() != 13) return;
        CHECK(p[0] == 'U' && p[1] == 'S' && p[2] == 'B' && p[3] == 'S');
        CHECK(p[4] == 0x78 && p[7] == 0x12);
        CHECK(p[12] == value);
        uint32_t n = uint32_t(p[8]) | uint32_t(p[9]) << 8 | uint32_t(p[10]) << 16 | uint32_t(p[11]) << 24;
        CHECK(n == residue);
        bot.InComplete();
    }
};
void Ownership() {
    Rig r;
    CHECK(r.reader.Local()); CHECK(!r.reader.Share(false)); CHECK(r.reader.Local());
    CHECK(r.Share()); CHECK(!r.reader.Local()); CHECK(!r.reader.Share(true));
    CHECK(!r.reader.Return());  // cannot take the filesystem away from Windows
    r.reader.PreventRemoval(true); CHECK(!r.reader.Eject());
    r.reader.PreventRemoval(false); CHECK(r.reader.Eject()); CHECK(!r.reader.Ready());
    CHECK(r.card.syncs == 1); CHECK(r.reader.Return()); CHECK(r.card.closes == 1);
    CHECK(r.reader.Sectors() == 0); CHECK(r.Share());
    r.reader.Interrupt(); CHECK(r.reader.State() == diag::ReaderState::Interrupted);
    CHECK(!r.reader.Share(true)); CHECK(!r.reader.Eject()); CHECK(r.reader.Return());
    CHECK(r.Share()); r.reader.Observe(false);
    CHECK(r.reader.State() == diag::ReaderState::Interrupted);
    r.reader.Observe(true); CHECK(!r.reader.Ready()); CHECK(r.reader.Return());
    r.card.open_ok = false; CHECK(!r.reader.Share(true));
    CHECK(r.reader.State() == diag::ReaderState::Error); CHECK(r.reader.Return());
    // A new controller (power cycle) always starts unexported.
    diag::CardReader restarted(r.card); CHECK(restarted.Local());
}
void RoundTrip() {
    Rig r;
    CHECK(r.Share());
    std::array<uint8_t, 1024> pattern{};
    for(unsigned i = 0; i < pattern.size(); ++i) pattern[i] = uint8_t(i * 17 + 29);
    auto write = Cbw(0x2a, 1024); write[20] = 2; write[23] = 2;
    r.Send(write); CHECK(r.port.receive == 512); CHECK(!r.bot.Idle());
    r.bot.Out(pattern.data(), 512); CHECK(r.card.writes == 1);
    r.bot.Out(pattern.data() + 512, 512); r.Status(0);
    for(unsigned i = 0; i < 4096; ++i)
        CHECK(r.card.bytes[i] == (i >= 1024 && i < 2048 ? pattern[i - 1024] : 0));
    auto read = Cbw(0x28, 1024, true); read[20] = 2; read[23] = 2;
    r.Send(read); CHECK(r.port.packets.back().size() == 512);
    CHECK(std::memcmp(r.port.packets.back().data(), pattern.data(), 512) == 0);
    r.bot.InComplete();
    CHECK(std::memcmp(r.port.packets.back().data(), pattern.data() + 512, 512) == 0);
    r.bot.InComplete(); r.Status(0); CHECK(r.card.reads == 2);
    r.Send(Cbw(0x35)); r.Status(0); CHECK(r.card.syncs == 1);
    auto prevent = Cbw(0x1e); prevent[19] = 1; r.Send(prevent); r.Status(0);
    auto eject = Cbw(0x1b); eject[19] = 2; r.Send(eject); r.Status(1);
    prevent[19] = 0; r.Send(prevent); r.Status(0);
    r.Send(eject); r.Status(0); CHECK(r.reader.State() == diag::ReaderState::Ejected);
    CHECK(r.reader.Return());
}
void ErrorsAndRecovery() {
    for(bool read : {false, true}) {
        Rig r; CHECK(r.Share());
        auto command = Cbw(read ? 0x28 : 0x2a, 512, read);
        command[20] = 8; command[23] = 1; r.Send(command);
        if(read) { CHECK(r.port.halt_in); r.bot.ClearHalt(true); }
        else CHECK(r.port.halt_out);
        r.Status(1, 512); CHECK(r.card.reads == 0 && r.card.writes == 0);
    }
    {
        Rig r;
        r.Send(Cbw(0x00)); r.Status(1);
        auto sense = Cbw(0x03, 18, true); sense[19] = 18;
        r.Send(sense); CHECK(r.port.packets.back()[2] == 2);
        CHECK(r.port.packets.back()[12] == 0x3a); r.bot.InComplete(); r.Status(0);
    }
    for(unsigned mutation = 0; mutation < 5; ++mutation) {
        Rig r; CHECK(r.Share()); auto c = Cbw(0x00);
        if(mutation == 0) c[0] = 0;
        if(mutation == 1) c[13] = 1;
        if(mutation == 2) c[14] = 0;
        if(mutation == 3) c[14] = 17;
        if(mutation == 4) c[12] = 1;
        r.Send(c);
        CHECK(r.port.halt_in && r.port.halt_out); CHECK(!r.bot.Idle());
        CHECK(r.card.writes == 0); CHECK(!r.reader.Ready());
        r.bot.ClearHalt(true); r.bot.ClearHalt(false); CHECK(!r.bot.Idle());
        r.bot.Reset(); r.bot.ClearHalt(true); CHECK(!r.bot.Idle());
        r.bot.ClearHalt(false); CHECK(r.bot.Idle()); CHECK(!r.reader.Ready());
    }
    for(bool read : {false, true}) {
        Rig r; CHECK(r.Share()); r.card.read_ok = r.card.write_ok = false;
        auto c = Cbw(read ? 0x28 : 0x2a, 512, read); c[23] = 1; r.Send(c);
        uint8_t data[512]{};
        if(read) r.bot.ClearHalt(true); else r.bot.Out(data, 512);
        r.Status(1, 512); CHECK(r.reader.State() == diag::ReaderState::Error);
    }
    {
        Rig r; CHECK(r.Share()); r.card.sync_ok = false;
        auto eject = Cbw(0x1b); eject[19] = 2; r.Send(eject); r.Status(1);
        CHECK(r.reader.State() == diag::ReaderState::Error);
    }
    {
        Rig r; CHECK(r.Share()); auto c = Cbw(0x2a, 1024); c[23] = 2; r.Send(c);
        uint8_t data[512]{}; r.bot.Out(data, 512); CHECK(r.card.writes == 1);
        r.bot.Disconnect(); r.bot.Out(data, 512); CHECK(r.card.writes == 1);
        CHECK(r.reader.State() == diag::ReaderState::Interrupted);
    }
}
void ThirteenCases() {
    struct Case { uint32_t host; bool in; uint8_t command; uint16_t count; uint8_t status; uint32_t residue; };
    const Case cases[] = {
        {0, false, 0x00, 0, 0, 0},     // 1: Hn Dn
        {0, false, 0x28, 1, 2, 0},     // 2: Hn Di
        {0, true,  0x2a, 1, 2, 0},     // 3: Hn Do (direction bit ignored)
        {512, true, 0x00, 0, 1, 512},  // 4: Hi Dn
        {1024, true, 0x28, 1, 0, 512}, // 5: Hi > Di
        {512, true, 0x28, 1, 0, 0},    // 6: Hi = Di
        {256, true, 0x28, 1, 2, 256},  // 7: Hi < Di
        {512, true, 0x2a, 1, 2, 512},  // 8: Hi Do
        {512, false, 0x00, 0, 1, 512}, // 9: Ho Dn
        {512, false, 0x28, 1, 2, 512}, // 10: Ho Di
        {1024, false, 0x2a, 1, 0, 512},// 11: Ho > Do
        {512, false, 0x2a, 1, 0, 0},   // 12: Ho = Do
        {256, false, 0x2a, 1, 2, 256}, // 13: Ho < Do
    };
    for(const auto& c : cases) {
        Rig r; CHECK(r.Share());
        auto cmd = Cbw(c.command, c.host, c.in); cmd[23] = uint8_t(c.count);
        r.Send(cmd);
        if(c.status == 0 && c.command == 0x28) r.bot.InComplete();
        if(c.status == 0 && c.command == 0x2a) { uint8_t block[512]{}; r.bot.Out(block, 512); }
        if(r.port.halt_in) { r.bot.ClearHalt(true); r.port.halt_in = false; }
        r.Status(c.status, c.residue);
        if(c.status == 2) {
            CHECK(!r.bot.Idle()); CHECK(r.card.writes == 0 && r.card.reads == 0);
            r.bot.Reset(); r.bot.ClearHalt(true); r.bot.ClearHalt(false);
            CHECK(r.bot.Idle()); CHECK(!r.reader.Ready());
        }
        if(c.host && c.residue) CHECK(c.in || r.port.halt_out);
    }
}
void Discovery() {
    Rig r;
    auto inquiry = Cbw(0x12, 96, true); inquiry[19] = 96;
    r.Send(inquiry); CHECK(r.port.packets.back().size() == 36);
    CHECK(r.port.packets.back()[1] == 0x80); r.bot.InComplete(); r.Status(0, 60);
    CHECK(r.Share());
    r.Send(Cbw(0x25, 8, true)); CHECK(r.port.packets.back()[3] == 7);
    CHECK(r.port.packets.back()[6] == 2); r.bot.InComplete(); r.Status(0);
    auto mode = Cbw(0x1a, 64, true); mode[17] = 8; mode[19] = 64;
    r.Send(mode); CHECK(r.port.packets.back().size() == 24);
    CHECK((r.port.packets.back()[6] & 4) == 0); r.bot.InComplete(); r.Status(0, 40);
    r.Send(Cbw(0xff, 10, true)); CHECK(r.port.halt_in);
    r.bot.ClearHalt(true); r.Status(1, 10);
    auto verify = Cbw(0x2f); verify[23] = 1; r.Send(verify); r.Status(1);
    CHECK(r.card.reads == 0 && r.card.writes == 0);  // never fabricate verification
    auto range = Cbw(0x28, 512, true);
    range[17] = range[18] = range[19] = range[20] = 0xff; range[23] = 1;
    r.Send(range); r.bot.ClearHalt(true); r.Status(1, 512);
    CHECK(r.card.reads == 0);
    auto zero = Cbw(0x2a); r.Send(zero); r.Status(0); CHECK(r.card.writes == 0);
}
int main() {
    Ownership(); RoundTrip(); ErrorsAndRecovery(); Discovery(); ThirteenCases();
    std::printf("card reader: %d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
