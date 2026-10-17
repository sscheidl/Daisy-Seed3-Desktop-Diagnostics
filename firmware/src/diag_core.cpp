#include "diag_core.h"
#include <cstring>

namespace diag {
namespace {
struct ModeName {
    LedMode mode;
    const char* name;
};
constexpr ModeName kModeNames[] = {
    {LedMode::Off, "OFF"},       {LedMode::On, "ON"},         {LedMode::Mask, "MASK"},
    {LedMode::Chase, "CHASE"},   {LedMode::Follow, "FOLLOW"},
};

char Sw18Char(Sw18 pos) {
    switch(pos) {
        case Sw18::Up: return 'U';
        case Sw18::Down: return 'D';
        default: return 'C';
    }
}

void WriteError(ddp::Writer& reply, const char* type, const char* code) {
    reply.Str("ERR c=").Str(type).Str(" e=").Str(code);
}

bool FieldU32(const char* body, const char* key, uint32_t& value) {
    char text[12];
    return ddp::FindField(body, key, text, sizeof(text)) && ddp::ParseU32(text, value);
}
} // namespace

const char* LedModeName(LedMode mode) {
    for(const auto& entry : kModeNames)
        if(entry.mode == mode)
            return entry.name;
    return "OFF";
}

bool ParseLedMode(const char* name, LedMode& mode) {
    for(const auto& entry : kModeNames) {
        if(std::strcmp(entry.name, name) == 0) {
            mode = entry.mode;
            return true;
        }
    }
    return false;
}

void ButtonTracker::Update(size_t index, bool rising_edge, bool falling_edge) {
    const uint16_t bit = static_cast<uint16_t>(1u << index);
    if(rising_edge && !(held_ & bit)) {
        held_ |= bit;
        ++count_[index];
    }
    if(falling_edge)
        held_ &= static_cast<uint16_t>(~bit);
}

Sw18 Switch3Debouncer::Update(Sw18 raw) {
    if(!initialised_) {
        initialised_ = true;
        stable_ = candidate_ = raw;
        count_ = kStableReads;
        return stable_;
    }
    if(raw != candidate_) {
        candidate_ = raw;
        count_ = 1;
    } else if(count_ < kStableReads) {
        ++count_;
    }
    if(count_ >= kStableReads)
        stable_ = candidate_;
    return stable_;
}

uint16_t ComputeLeds(const Settings& settings, uint32_t now_ms, uint16_t buttons) {
    switch(settings.led_mode) {
        case LedMode::Off: return 0;
        case LedMode::On: return 0xffff;
        case LedMode::Mask: return settings.led_mask;
        case LedMode::Chase: {
            const uint32_t step = settings.chase_step_ms ? settings.chase_step_ms : 1;
            return static_cast<uint16_t>(1u << ((now_ms / step) % kNumLeds));
        }
        case LedMode::Follow: return buttons;
    }
    return 0;
}

bool DigitalChanged(const Inputs& a, const Inputs& b) {
    if(a.buttons != b.buttons || a.sw17_up != b.sw17_up || a.sw18 != b.sw18
       || a.sd_card != b.sd_card || a.jack_left != b.jack_left
       || a.jack_right != b.jack_right)
        return true;
    return std::memcmp(a.press_count, b.press_count, sizeof(a.press_count)) != 0;
}

uint16_t NormalizePot(float value) {
    if(!(value > 0.f))  // also maps NaN to 0
        return 0;
    if(value >= 1.f)
        return 10000;
    return static_cast<uint16_t>(value * 10000.f + 0.5f);
}

void Session::Expire(uint32_t now_ms) {
    if(streaming_ && now_ms - last_rx_ms_ >= kHostTimeoutMs)
        streaming_ = false;
}

bool Session::HostActive(uint32_t now_ms) {
    Expire(now_ms);
    return streaming_;
}

void Session::WriteHello(ddp::Writer& out) const {
    out.Str("HELLO proto=").U32(ddp::kProtocolVersion)
        .Str(" fw=").Str(kFirmwareVersion)
        .Str(" app=").Str(kAppName)
        .Str(" dev=seed3-desktop boot=BOOT_SRAM bl=").Str(bootloader_)
        .Str(" libdaisy=").Str(kLibDaisyCommit)
        .Str(" caps=btn,pot,potraw,sw17,sw18,sd,sdread,jack,led");
}

uint32_t Session::Handle(const char* body, uint32_t now_ms, ddp::Writer& reply) {
    Expire(now_ms);  // a late PING must not revive a timed-out stream
    last_rx_ms_ = now_ms;
    char type[13];
    ddp::MessageType(body, type, sizeof(type));
    uint32_t value = 0;

    if(std::strcmp(type, "HELLO") == 0) {
        if(!FieldU32(body, "proto", value)) {
            WriteError(reply, type, "ARG");
            return kRequestNone;
        }
        if(value != static_cast<uint32_t>(ddp::kProtocolVersion)) {
            WriteError(reply, type, "PROTO");
            return kRequestNone;
        }
        streaming_ = true;
        WriteHello(reply);
        return kRequestState | kRequestNewSession;
    }
    if(std::strcmp(type, "PING") == 0) {
        if(!FieldU32(body, "n", value)) {
            WriteError(reply, type, "ARG");
            return kRequestNone;
        }
        reply.Str("PONG n=").U32(value);
        return kRequestNone;
    }
    if(std::strcmp(type, "GET") == 0)
        return kRequestState;
    if(std::strcmp(type, "RATE") == 0) {
        if(!FieldU32(body, "hz", value) || value < 10 || value > 100) {
            WriteError(reply, type, "ARG");
            return kRequestNone;
        }
        settings.rate_hz = static_cast<uint8_t>(value);
        reply.Str("ACK c=RATE hz=").U32(value);
        return kRequestNone;
    }
    if(std::strcmp(type, "LED") == 0) {
        Settings next = settings;
        char text[12];
        if(!ddp::FindField(body, "m", text, sizeof(text))
           || !ParseLedMode(text, next.led_mode)) {
            WriteError(reply, type, "ARG");
            return kRequestNone;
        }
        // Optional fields: absent keeps the setting, present-but-invalid (including
        // too long to parse) rejects the whole command.
        ddp::Lookup found = ddp::LookupField(body, "mask", text, sizeof(text));
        if(found != ddp::Lookup::Missing) {
            if(found == ddp::Lookup::TooLong || !ddp::ParseHex(text, value) || value > 0xffff) {
                WriteError(reply, type, "ARG");
                return kRequestNone;
            }
            next.led_mask = static_cast<uint16_t>(value);
        }
        found = ddp::LookupField(body, "br", text, sizeof(text));
        if(found != ddp::Lookup::Missing) {
            if(found == ddp::Lookup::TooLong || !ddp::ParseU32(text, value) || value > 100) {
                WriteError(reply, type, "ARG");
                return kRequestNone;
            }
            next.led_brightness = static_cast<uint8_t>(value);
        }
        found = ddp::LookupField(body, "ms", text, sizeof(text));
        if(found != ddp::Lookup::Missing) {
            if(found == ddp::Lookup::TooLong || !ddp::ParseU32(text, value) || value < 20
               || value > 2000) {
                WriteError(reply, type, "ARG");
                return kRequestNone;
            }
            next.chase_step_ms = static_cast<uint16_t>(value);
        }
        settings = next;
        reply.Str("ACK c=LED m=").Str(LedModeName(settings.led_mode))
            .Str(" mask=").Hex(settings.led_mask, 4)
            .Str(" br=").U32(settings.led_brightness)
            .Str(" ms=").U32(settings.chase_step_ms);
        return kRequestLeds;
    }
    if(std::strcmp(type, "SDTEST") == 0)
        return kRequestSdTest;
    if(std::strcmp(type, "BYE") == 0) {
        streaming_ = false;
        reply.Str("ACK c=BYE");
        return kRequestNone;
    }
    WriteError(reply, type[0] ? type : "?", "UNKNOWN");
    return kRequestNone;
}

void WriteState(const Inputs& in, const Settings& settings, uint16_t leds,
                uint32_t seq, uint32_t now_ms, ddp::Writer& out) {
    out.Str("ST n=").U32(seq).Str(" t=").U32(now_ms)
        .Str(" b=").Hex(in.buttons, 4).Str(" pc=");
    for(uint8_t count : in.press_count)
        out.Hex(count, 2);
    out.Str(" p=");
    for(size_t i = 0; i < kNumPots; ++i) {
        if(i)
            out.Char(',');
        out.U32(in.pot_norm[i]);
    }
    out.Str(" r=");
    for(size_t i = 0; i < kNumPots; ++i) {
        if(i)
            out.Char(',');
        out.U32(in.pot_raw[i]);
    }
    out.Str(" s17=").Char(in.sw17_up ? 'U' : 'D')
        .Str(" s18=").Char(Sw18Char(in.sw18))
        .Str(" sd=").Char(in.sd_card ? '1' : '0')
        .Str(" jl=").Char(in.jack_left ? '1' : '0')
        .Str(" jr=").Char(in.jack_right ? '1' : '0')
        .Str(" lm=").Str(LedModeName(settings.led_mode))
        .Str(" l=").Hex(leds, 4)
        .Str(" br=").U32(settings.led_brightness);
}

void WriteSys(const Stats& stats, bool host, uint8_t rate_hz, ddp::Writer& out) {
    out.Str("SYS up=").U32(stats.uptime_s)
        .Str(" cbhz=").U32(stats.control_rate_hz)
        .Str(" txok=").U32(stats.tx_ok)
        .Str(" txbusy=").U32(stats.tx_busy)
        .Str(" txdrop=").U32(stats.tx_drop)
        .Str(" rxok=").U32(stats.rx_ok)
        .Str(" rxbad=").U32(stats.rx_bad)
        .Str(" host=").Char(host ? '1' : '0')
        .Str(" rate=").U32(rate_hz);
}

void WriteSd(const SdResult& result, ddp::Writer& out) {
    out.Str("SD st=");
    switch(result.status) {
        case SdStatus::None: out.Str("NONE res=-1"); return;
        case SdStatus::Mounted: out.Str("MOUNTED res="); break;
        case SdStatus::Error: out.Str("ERROR res="); break;
    }
    out.U32(static_cast<uint32_t>(result.fresult));
    if(result.status == SdStatus::Mounted)
        out.Str(" fs=").Str(result.fs_type)
            .Str(" mb=").U32(result.size_mb)
            .Str(" ent=").U32(result.entries);
}

} // namespace diag
