// Main-loop logic of the diagnostic firmware, independent of libDaisy so that the
// complete command/response/streaming behaviour can be tested on the host.
// main.cpp supplies the hardware through the Board and UsbSink interfaces.
#pragma once
#include "ddp.h"
#include "diag_core.h"
#include "ring_buffer.h"

namespace diag {

enum class SendResult : uint8_t {
    Ok,        // transfer started; the buffer must stay untouched until the next Ok
    Busy,      // previous IN transfer still running, try again later
    NotReady,  // device not configured by a host (no enumeration / USB reset)
};

// USB CDC transmit. Implementations must check readiness and start the transfer
// atomically with respect to the USB interrupt (see CdcSink in main.cpp).
class UsbSink {
  public:
    virtual SendResult Send(const uint8_t* data, size_t len) = 0;

  protected:
    ~UsbSink() = default;
};

class Board {
  public:
    virtual Inputs ReadInputs() = 0;
    virtual uint32_t ControlTicks() = 0;  // number of 1 kHz control updates so far
    virtual void ApplyLeds(uint16_t leds, uint8_t brightness_percent) = 0;
    virtual SdResult RunSdTest(bool card_present) = 0;  // blocking, bounded

  protected:
    ~Board() = default;
};

// Frames waiting for the CDC IN endpoint. The driver reads a submitted buffer until
// its transfer completes, so new frames are collected in the other buffer; a
// successful Send() implies the previous transfer has finished.
class TxQueue {
  public:
    static constexpr size_t kSize = 1536;
    void Append(const char* body, size_t len, Stats& stats);
    void Pump(UsbSink& usb, Stats& stats);
    void Discard(Stats& stats);
    size_t Pending() const { return fill_; }

  private:
    uint8_t buf_[2][kSize] = {};
    size_t active_ = 0;
    size_t fill_ = 0;
};

class App {
  public:
    static constexpr uint32_t kRxSize = 1024;
    static constexpr uint32_t kLedMinIntervalMs = 10;

    App(Board& board, UsbSink& usb, const char* bootloader_name, uint32_t now_ms);

    // USB receive interrupt: copy only.
    void OnUsbReceive(const uint8_t* data, uint32_t len) { rx_.Push(data, len); }

    // One main-loop iteration.
    void Step(uint32_t now_ms);

    bool HostActive(uint32_t now_ms) { return session_.HostActive(now_ms); }
    const Stats& stats() const { return stats_; }
    const Settings& settings() const { return session_.settings; }

  private:
    void Send(const ddp::Writer& body);

    Board& board_;
    UsbSink& usb_;
    Session session_;
    ddp::FrameParser parser_;
    SpscRing<kRxSize> rx_;
    TxQueue tx_;
    Stats stats_;
    Inputs last_sent_;
    uint32_t seq_ = 0;
    uint32_t start_ms_;
    uint32_t last_state_ms_;
    uint32_t last_sys_ms_;
    uint32_t last_led_ms_;
    uint32_t last_stat_ms_;
    uint32_t last_ticks_ = 0;
    uint16_t last_leds_ = 0;
    uint8_t last_brightness_ = 0;
    bool leds_dirty_ = true;
    bool keepalive_after_block_ = false;
};

} // namespace diag
