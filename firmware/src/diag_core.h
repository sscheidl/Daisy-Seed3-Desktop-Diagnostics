// Hardware-independent diagnostic logic: input state, LED modes and protocol session.
// Contains no libDaisy code so it can be tested on the host (diagnostics/tests/firmware).
#pragma once
#include "ddp.h"
#include <cstddef>
#include <cstdint>

namespace diag {

constexpr const char* kFirmwareVersion = "0.1.0";
constexpr const char* kAppName = "DaisyDiagnostic";
constexpr const char* kLibDaisyCommit = "f715e48";
constexpr size_t kNumButtons = 16;
constexpr size_t kNumLeds = 16;
constexpr size_t kNumPots = 8;
constexpr uint32_t kHostTimeoutMs = 3000;
constexpr uint32_t kMinFrameSpacingMs = 10;

enum class Sw18 : uint8_t { Center, Up, Down };
enum class LedMode : uint8_t { Off, On, Mask, Chase, Follow };

const char* LedModeName(LedMode mode);
bool ParseLedMode(const char* name, LedMode& mode);

// Debounced button state between DigitalControl's rising and falling edges.
// DigitalControl may report a second rising edge after a short contact dropout
// without a falling edge in between; that is not counted as a new press.
class ButtonTracker {
  public:
    void Update(size_t index, bool rising_edge, bool falling_edge);
    uint16_t Held() const { return held_; }
    uint8_t PressCount(size_t index) const { return count_[index]; }

  private:
    uint16_t held_ = 0;
    uint8_t count_[kNumButtons] = {};
};

// libDaisy's Switch3::Read() is an undebounced GPIO read. A new position is
// accepted after it has been read identically `kStableReads` times in a row.
class Switch3Debouncer {
  public:
    static constexpr uint8_t kStableReads = 8;
    Sw18 Update(Sw18 raw);
    Sw18 Position() const { return stable_; }

  private:
    Sw18 stable_ = Sw18::Center;
    Sw18 candidate_ = Sw18::Center;
    uint8_t count_ = 0;
    bool initialised_ = false;
};

struct Settings {
    LedMode led_mode = LedMode::Follow;
    uint16_t led_mask = 0;
    uint8_t led_brightness = 100;  // percent
    uint16_t chase_step_ms = 120;
    uint8_t rate_hz = 50;
};

// Commanded LED target state. There is no electrical LED feedback on the board.
uint16_t ComputeLeds(const Settings& settings, uint32_t now_ms, uint16_t buttons);

struct Inputs {
    uint16_t buttons = 0;
    uint8_t press_count[kNumButtons] = {};
    uint16_t pot_norm[kNumPots] = {};  // 0..10000 == 0.0..1.0
    uint16_t pot_raw[kNumPots] = {};   // ADC 0..65535
    bool sw17_up = false;
    Sw18 sw18 = Sw18::Center;
    bool sd_card = false;
    bool jack_left = false;
    bool jack_right = false;
};

// True when a digital input differs; pots are sent with the periodic frames.
bool DigitalChanged(const Inputs& a, const Inputs& b);

uint16_t NormalizePot(float value);

struct Stats {
    uint32_t uptime_s = 0;
    uint32_t control_rate_hz = 0;
    uint32_t tx_ok = 0;
    uint32_t tx_busy = 0;
    uint32_t tx_drop = 0;
    uint32_t rx_ok = 0;
    uint32_t rx_bad = 0;
};

enum Request : uint32_t {
    kRequestNone = 0,
    kRequestState = 1u << 0,   // send ST (and SYS) immediately
    kRequestSdTest = 1u << 1,  // run the read-only SD test in the main loop
    kRequestLeds = 1u << 2,    // LED settings changed
    kRequestNewSession = 1u << 3,  // HELLO accepted: stale queued output may be dropped
};

// Command handling and host liveness. Streaming starts with HELLO and stops after
// BYE or kHostTimeoutMs without a valid frame; only a new HELLO restarts it.
class Session {
  public:
    void Init(const char* bootloader_name) { bootloader_ = bootloader_name; }
    // Handles one valid frame body. Writes a reply body into `reply` (left empty
    // when there is nothing to answer) and returns a mask of Request flags.
    uint32_t Handle(const char* body, uint32_t now_ms, ddp::Writer& reply);
    bool HostActive(uint32_t now_ms);
    // Counts as host activity: used after a blocking operation the host requested
    // (SD test), during which the host's keep-alive frames could not be processed.
    void KeepAlive(uint32_t now_ms) {
        if(streaming_)
            last_rx_ms_ = now_ms;
    }
    void WriteHello(ddp::Writer& out) const;

    Settings settings;

  private:
    void Expire(uint32_t now_ms);
    const char* bootloader_ = "unknown";
    bool streaming_ = false;
    uint32_t last_rx_ms_ = 0;
};

void WriteState(const Inputs& in, const Settings& settings, uint16_t leds,
                uint32_t seq, uint32_t now_ms, ddp::Writer& out);
void WriteSys(const Stats& stats, bool host, uint8_t rate_hz, ddp::Writer& out);

enum class SdStatus : uint8_t { None, Mounted, Error };
struct SdResult {
    SdStatus status = SdStatus::None;
    int fresult = -1;
    const char* fs_type = "-";
    uint32_t size_mb = 0;
    uint32_t entries = 0;
};
void WriteSd(const SdResult& result, ddp::Writer& out);

} // namespace diag
