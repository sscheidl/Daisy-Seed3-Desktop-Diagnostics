// Daisy Diagnostic Protocol (DDP) v1 - framing and field helpers.
// Portable C++17 without libDaisy, heap or exceptions; shared by firmware and host tests.
// Specification: PROTOCOL.md
#pragma once
#include <cstddef>
#include <cstdint>

namespace ddp {

constexpr int kProtocolVersion = 1;
constexpr size_t kMaxBody = 400;
// '$' + body + '*' + 4 CRC digits + '\n'
constexpr size_t kMaxFrame = kMaxBody + 7;

// CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no final XOR.
uint16_t Crc16(const char* data, size_t len);

// True for bytes allowed inside a body.
inline bool IsBodyChar(char c) {
    return c >= 0x20 && c <= 0x7e && c != '$' && c != '*';
}

// Writes "$<body>*XXXX\n" into out. Returns the frame length, or 0 if the body is
// invalid or does not fit (out is then left unterminated).
size_t BuildFrame(const char* body, size_t body_len, char* out, size_t cap);

// Byte-wise frame receiver with resynchronisation, see PROTOCOL.md.
class FrameParser {
  public:
    // Returns true when a complete, valid frame is available via Body().
    // The body stays valid until the next call to Feed().
    bool Feed(char c);
    const char* Body() const { return body_; }
    size_t BodyLength() const { return body_len_; }
    void Reset() { state_ = State::Idle; body_len_ = 0; }

    uint32_t ok = 0;
    uint32_t bad_crc = 0;
    uint32_t bad_format = 0;  // invalid character, missing '*', bad hex digits
    uint32_t overflow = 0;

  private:
    enum class State : uint8_t { Idle, Body, Crc, Cr };
    State state_ = State::Idle;
    char body_[kMaxBody + 1] = {};
    size_t body_len_ = 0;
    char crc_[4] = {};
    size_t crc_len_ = 0;
    bool Finish();
};

// Bounded string builder that never overflows; Ok() turns false if anything was cut.
class Writer {
  public:
    Writer(char* buf, size_t cap) : buf_(buf), cap_(cap) { if(cap_) buf_[0] = 0; }
    Writer& Str(const char* s);
    Writer& Char(char c);
    Writer& U32(uint32_t v);
    Writer& Hex(uint32_t v, int digits);
    const char* CStr() const { return buf_; }
    size_t Length() const { return len_; }
    bool Ok() const { return ok_; }

  private:
    char* buf_;
    size_t cap_;
    size_t len_ = 0;
    bool ok_ = true;
};

// Message type = first token of the body. Copies at most cap-1 characters.
void MessageType(const char* body, char* out, size_t cap);

// Looks up "key=value" in a body (tokens separated by single spaces; the first
// token is the type and never matches). Copies the value; false if absent or too long.
bool FindField(const char* body, const char* key, char* out, size_t cap);

// Strict number parsers for field values; false on empty input, junk or overflow.
bool ParseU32(const char* s, uint32_t& out);
bool ParseHex(const char* s, uint32_t& out);

} // namespace ddp
