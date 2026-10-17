#include "diag_app.h"

namespace diag {

void TxQueue::Append(const char* body, size_t len, Stats& stats) {
    char frame[ddp::kMaxFrame];
    const size_t n = ddp::BuildFrame(body, len, frame, sizeof(frame));
    if(n == 0 || fill_ + n > kSize) {
        ++stats.tx_drop;
        return;
    }
    for(size_t i = 0; i < n; ++i)
        buf_[active_][fill_ + i] = static_cast<uint8_t>(frame[i]);
    fill_ += n;
}

void TxQueue::Pump(UsbSink& usb, Stats& stats) {
    if(fill_ == 0)
        return;
    switch(usb.Send(buf_[active_], fill_)) {
        case SendResult::Ok:
            ++stats.tx_ok;
            active_ ^= 1;
            fill_ = 0;
            break;
        case SendResult::Busy: ++stats.tx_busy; break;
        case SendResult::NotReady: Discard(stats); break;  // nobody is listening
    }
}

void TxQueue::Discard(Stats& stats) {
    if(fill_) {
        ++stats.tx_drop;
        fill_ = 0;
    }
}

App::App(Board& board, UsbSink& usb, const char* bootloader_name, uint32_t now_ms)
    : board_(board), usb_(usb), start_ms_(now_ms), last_state_ms_(now_ms),
      last_sys_ms_(now_ms), last_led_ms_(now_ms - kLedMinIntervalMs), last_stat_ms_(now_ms) {
    session_.Init(bootloader_name);
    last_ticks_ = board_.ControlTicks();
}

void App::Send(const ddp::Writer& body) {
    if(body.Length() && body.Ok())
        tx_.Append(body.CStr(), body.Length(), stats_);
    else if(body.Length())
        ++stats_.tx_drop;
}

void App::Step(uint32_t now) {
    uint32_t requests = kRequestNone;
    if(keepalive_after_block_) {
        // The previous step blocked in the SD test; keep-alives queued meanwhile are
        // processed only now, so the blocked time must not count as host silence.
        session_.KeepAlive(now);
        keepalive_after_block_ = false;
    }

    // Commands from the host.
    uint8_t byte;
    while(rx_.Pop(byte)) {
        if(!parser_.Feed(static_cast<char>(byte)))
            continue;
        char reply_buf[ddp::kMaxBody + 1];
        ddp::Writer reply(reply_buf, sizeof(reply_buf));
        const uint32_t r = session_.Handle(parser_.Body(), now, reply);
        if(r & kRequestNewSession) {
            // Output queued for a previous host (e.g. one that closed the port without
            // BYE) is stale; start the new session with a clean buffer.
            tx_.Discard(stats_);
            last_sent_ = Inputs();
        }
        requests |= r;
        Send(reply);
    }
    stats_.rx_ok = parser_.ok;
    stats_.rx_bad = parser_.bad_crc + parser_.bad_format + parser_.overflow + rx_.Overflow();

    const Inputs inputs = board_.ReadInputs();

    // LEDs: commanded state only, there is no optical feedback.
    const uint16_t leds = ComputeLeds(session_.settings, now, inputs.buttons);
    if(requests & kRequestLeds)
        leds_dirty_ = true;
    if((leds_dirty_ || leds != last_leds_ || session_.settings.led_brightness != last_brightness_)
       && now - last_led_ms_ >= kLedMinIntervalMs) {
        board_.ApplyLeds(leds, session_.settings.led_brightness);
        last_leds_ = leds;
        last_brightness_ = session_.settings.led_brightness;
        last_led_ms_ = now;
        leds_dirty_ = false;
    }

    if(now - last_stat_ms_ >= 1000) {
        const uint32_t ticks = board_.ControlTicks();
        stats_.control_rate_hz = (ticks - last_ticks_) * 1000u / (now - last_stat_ms_);
        last_ticks_ = ticks;
        last_stat_ms_ = now;
        stats_.uptime_s = (now - start_ms_) / 1000u;
    }

    if(requests & kRequestSdTest) {
        char body[96];
        ddp::Writer out(body, sizeof(body));
        WriteSd(board_.RunSdTest(inputs.sd_card), out);
        Send(out);
        keepalive_after_block_ = true;
    }

    // Replies (including the ACK for BYE) stay queued after the stream stops.
    if(session_.HostActive(now)) {
        const uint32_t period = 1000u / session_.settings.rate_hz;
        const bool periodic = now - last_state_ms_ >= period;
        const bool changed = DigitalChanged(inputs, last_sent_)
                             && now - last_state_ms_ >= kMinFrameSpacingMs;
        if(periodic || changed || (requests & kRequestState)) {
            char body[ddp::kMaxBody + 1];
            ddp::Writer out(body, sizeof(body));
            WriteState(inputs, session_.settings, last_leds_, seq_++, now, out);
            Send(out);
            last_sent_ = inputs;
            last_state_ms_ = now;
        }
        if(now - last_sys_ms_ >= 1000 || (requests & kRequestState)) {
            char body[160];
            ddp::Writer out(body, sizeof(body));
            WriteSys(stats_, true, session_.settings.rate_hz, out);
            Send(out);
            last_sys_ms_ = now;
        }
    }
    tx_.Pump(usb_, stats_);
}

} // namespace diag
