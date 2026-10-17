#include "ddp.h"

namespace ddp {
namespace {
constexpr char kHexDigits[] = "0123456789ABCDEF";

int HexValue(char c) {
    if(c >= '0' && c <= '9')
        return c - '0';
    if(c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    if(c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}
} // namespace

uint16_t Crc16(const char* data, size_t len) {
    uint16_t crc = 0xffff;
    for(size_t i = 0; i < len; ++i) {
        crc ^= static_cast<uint16_t>(static_cast<uint8_t>(data[i]) << 8);
        for(int bit = 0; bit < 8; ++bit)
            crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021)
                                 : static_cast<uint16_t>(crc << 1);
    }
    return crc;
}

size_t BuildFrame(const char* body, size_t body_len, char* out, size_t cap) {
    if(body_len == 0 || body_len > kMaxBody || cap < body_len + 7)
        return 0;
    size_t n = 0;
    out[n++] = '$';
    for(size_t i = 0; i < body_len; ++i) {
        if(!IsBodyChar(body[i]))
            return 0;
        out[n++] = body[i];
    }
    const uint16_t crc = Crc16(body, body_len);
    out[n++] = '*';
    for(int shift = 12; shift >= 0; shift -= 4)
        out[n++] = kHexDigits[(crc >> shift) & 0xf];
    out[n++] = '\n';
    return n;
}

bool FrameParser::Feed(char c) {
    if(c == '$') {
        // A start marker always begins a new frame; a pending one was incomplete.
        if(state_ != State::Idle)
            ++bad_format;
        state_ = State::Body;
        body_len_ = 0;
        return false;
    }
    switch(state_) {
        case State::Idle: return false;
        case State::Body:
            if(c == '*') {
                state_ = State::Crc;
                crc_len_ = 0;
            } else if(!IsBodyChar(c)) {
                ++bad_format;
                state_ = State::Idle;
            } else if(body_len_ >= kMaxBody) {
                ++overflow;
                state_ = State::Idle;
            } else {
                body_[body_len_++] = c;
            }
            return false;
        case State::Crc:
            if(crc_len_ < 4) {
                if(HexValue(c) < 0) {
                    ++bad_format;
                    state_ = State::Idle;
                } else {
                    crc_[crc_len_++] = c;
                }
                return false;
            }
            if(c == '\r') {
                state_ = State::Cr;
                return false;
            }
            if(c == '\n')
                return Finish();
            ++bad_format;
            state_ = State::Idle;
            return false;
        case State::Cr:
            if(c == '\n')
                return Finish();
            ++bad_format;
            state_ = State::Idle;
            return false;
    }
    return false;
}

bool FrameParser::Finish() {
    state_ = State::Idle;
    uint16_t received = 0;
    for(char d : crc_) {
        const int v = HexValue(d);
        if(v < 0) {
            ++bad_format;
            return false;
        }
        received = static_cast<uint16_t>((received << 4) | v);
    }
    if(body_len_ == 0) {
        ++bad_format;
        return false;
    }
    if(received != Crc16(body_, body_len_)) {
        ++bad_crc;
        return false;
    }
    body_[body_len_] = 0;
    ++ok;
    return true;
}

Writer& Writer::Char(char c) {
    if(len_ + 1 < cap_) {
        buf_[len_++] = c;
        buf_[len_] = 0;
    } else {
        ok_ = false;
    }
    return *this;
}

Writer& Writer::Str(const char* s) {
    while(*s)
        Char(*s++);
    return *this;
}

Writer& Writer::U32(uint32_t v) {
    char tmp[10];
    int n = 0;
    do {
        tmp[n++] = static_cast<char>('0' + v % 10);
        v /= 10;
    } while(v);
    while(n)
        Char(tmp[--n]);
    return *this;
}

Writer& Writer::Hex(uint32_t v, int digits) {
    for(int shift = (digits - 1) * 4; shift >= 0; shift -= 4)
        Char(kHexDigits[(v >> shift) & 0xf]);
    return *this;
}

void MessageType(const char* body, char* out, size_t cap) {
    size_t n = 0;
    while(body[n] && body[n] != ' ' && n + 1 < cap) {
        out[n] = body[n];
        ++n;
    }
    out[n] = 0;
}

Lookup LookupField(const char* body, const char* key, char* out, size_t cap) {
    const char* p = body;
    while(*p && *p != ' ')
        ++p;  // skip message type
    while(*p) {
        while(*p == ' ')
            ++p;
        const char* k = key;
        const char* t = p;
        while(*k && *t == *k) {
            ++k;
            ++t;
        }
        if(*k == 0 && *t == '=') {
            ++t;
            size_t n = 0;
            while(t[n] && t[n] != ' ') {
                if(n + 1 >= cap) {
                    if(cap)
                        out[0] = 0;
                    return Lookup::TooLong;
                }
                out[n] = t[n];
                ++n;
            }
            out[n] = 0;
            return Lookup::Found;
        }
        while(*p && *p != ' ')
            ++p;
    }
    return Lookup::Missing;
}

bool ParseU32(const char* s, uint32_t& out) {
    if(!*s)
        return false;
    uint64_t v = 0;
    for(; *s; ++s) {
        if(*s < '0' || *s > '9')
            return false;
        v = v * 10 + static_cast<uint64_t>(*s - '0');
        if(v > 0xffffffffull)
            return false;
    }
    out = static_cast<uint32_t>(v);
    return true;
}

bool ParseHex(const char* s, uint32_t& out) {
    if(!*s)
        return false;
    uint64_t v = 0;
    for(; *s; ++s) {
        const int d = HexValue(*s);
        if(d < 0)
            return false;
        v = (v << 4) | static_cast<uint64_t>(d);
        if(v > 0xffffffffull)
            return false;
    }
    out = static_cast<uint32_t>(v);
    return true;
}

} // namespace ddp
