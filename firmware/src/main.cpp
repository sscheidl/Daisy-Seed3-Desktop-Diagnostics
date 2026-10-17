// Daisy Seed3 Desktop Dev Kit - hardware diagnostic firmware.
// Reads all panel controls through the official desktop_devkit::Hardware class and
// talks DDP v1 (diagnostics/protocol/PROTOCOL.md) over USB CDC on carrier port J7.
#include "desktop_devkit.h"
#include "fatfs.h"
#include "usbd_core.h"
#include "ddp.h"
#include "diag_core.h"
#include <atomic>

using namespace daisy;

extern "C" USBD_HandleTypeDef hUsbDeviceHS;  // defined in libDaisy src/hid/usb.cpp

namespace {
desktop_devkit::Hardware hw;
UsbHandle usb;
diag::Session session;

// ---- Control sampling (audio callback, 1 kHz) -----------------------------------
diag::ButtonTracker buttons;
diag::Switch3Debouncer sw18;
diag::Inputs callback_inputs;  // written in the callback, copied with IRQs masked
std::atomic<uint32_t> control_ticks{0};

diag::Sw18 MapSwitch3(int pos) {
    switch(pos) {
        case Switch3::POS_UP: return diag::Sw18::Up;
        case Switch3::POS_DOWN: return diag::Sw18::Down;
        default: return diag::Sw18::Center;
    }
}

void AudioCallback(AudioHandle::InputBuffer, AudioHandle::OutputBuffer out, size_t size) {
    hw.UpdateAllControls();
    for(size_t i = 0; i < diag::kNumButtons; ++i)
        buttons.Update(i, hw.button[i].RisingEdge(), hw.button[i].FallingEdge());
    sw18.Update(MapSwitch3(hw.tog_sw18.Read()));

    callback_inputs.buttons = buttons.Held();
    for(size_t i = 0; i < diag::kNumButtons; ++i)
        callback_inputs.press_count[i] = buttons.PressCount(i);
    callback_inputs.sw17_up = hw.tog_sw17.Pressed();
    callback_inputs.sw18 = sw18.Position();
    callback_inputs.sd_card = hw.sd_detect.Pressed();
    callback_inputs.jack_left = hw.left_detect.Pressed();
    callback_inputs.jack_right = hw.right_detect.Pressed();
    control_ticks.fetch_add(1, std::memory_order_relaxed);

    // Audio is not part of this diagnostic: outputs stay silent.
    for(size_t i = 0; i < size; ++i) {
        out[0][i] = 0.f;
        out[1][i] = 0.f;
    }
}

diag::Inputs SnapshotInputs() {
    diag::Inputs in;
    __disable_irq();
    in = callback_inputs;
    __enable_irq();
    for(size_t i = 0; i < diag::kNumPots; ++i) {
        in.pot_norm[i] = diag::NormalizePot(hw.pot[i].Value());
        in.pot_raw[i] = hw.seed.adc.GetMux(0, static_cast<uint8_t>(i));
    }
    return in;
}

// ---- USB receive: ISR -> lock-free single-producer/single-consumer ring ----------
constexpr uint32_t kRxSize = 1024;  // power of two
uint8_t rx_ring[kRxSize];
std::atomic<uint32_t> rx_head{0}, rx_tail{0};
std::atomic<uint32_t> rx_overflow{0};

void UsbReceive(uint8_t* buf, uint32_t* len) {
    // Runs in the USB interrupt: copy only, never parse or transmit here.
    if(!buf || !len)
        return;
    uint32_t head = rx_head.load(std::memory_order_relaxed);
    const uint32_t tail = rx_tail.load(std::memory_order_acquire);
    for(uint32_t i = 0; i < *len; ++i) {
        if(head - tail >= kRxSize) {
            rx_overflow.fetch_add(*len - i, std::memory_order_relaxed);
            break;
        }
        rx_ring[head % kRxSize] = buf[i];
        ++head;
    }
    rx_head.store(head, std::memory_order_release);
}

// ---- USB transmit: two buffers, never blocks ------------------------------------
// The CDC driver reads the submitted buffer until its IN transfer completes, so new
// frames are collected in the other buffer. A successful submit implies the previous
// transfer has finished (TxState was 0), so the pending buffer is then free again.
class TxQueue {
  public:
    void Append(const char* body, size_t len, diag::Stats& stats) {
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

    void Pump(diag::Stats& stats) {
        if(fill_ == 0)
            return;
        // libDaisy's CDC_Transmit_HS dereferences the class data without a NULL check.
        if(hUsbDeviceHS.dev_state != USBD_STATE_CONFIGURED || hUsbDeviceHS.pClassData == nullptr) {
            Discard(stats);
            return;
        }
        if(usb.TransmitExternal(buf_[active_], fill_) == UsbHandle::Result::OK) {
            ++stats.tx_ok;
            active_ ^= 1;
            fill_ = 0;
        } else {
            ++stats.tx_busy;
        }
    }

    void Discard(diag::Stats& stats) {
        if(fill_) {
            ++stats.tx_drop;
            fill_ = 0;
        }
    }

  private:
    static constexpr size_t kSize = 1536;
    uint8_t buf_[2][kSize];
    size_t active_ = 0;
    size_t fill_ = 0;
};
TxQueue tx;
diag::Stats stats;

void Send(const ddp::Writer& body) {
    if(body.Length() && body.Ok())
        tx.Append(body.CStr(), body.Length(), stats);
    else if(body.Length())
        ++stats.tx_drop;
}

// ---- microSD: read-only mount test ---------------------------------------------
// With BOOT_SRAM, .bss lives in DTCM, which SDMMC1's IDMA cannot reach. The FatFs
// objects (including the sector window) therefore live in SDRAM; libDaisy's
// sd_diskio performs the required D-cache maintenance.
SdmmcHandler sdmmc;
bool sd_hw_ready = false;
DSY_SDRAM_BSS alignas(32) FatFSInterface fsi;
DSY_SDRAM_BSS alignas(32) DIR sd_dir;
FILINFO sd_info;

const char* FsTypeName(BYTE type) {
    switch(type) {
        case FS_FAT12: return "FAT12";
        case FS_FAT16: return "FAT16";
        case FS_FAT32: return "FAT32";
#if _FS_EXFAT
        case FS_EXFAT: return "EXFAT";
#endif
        default: return "?";
    }
}

diag::SdResult RunSdTest(bool card_present) {
    diag::SdResult result;
    if(!card_present)
        return result;  // SdStatus::None: no access attempted
    if(!sd_hw_ready) {
        SdmmcHandler::Config cfg;
        cfg.Defaults();
        cfg.speed = SdmmcHandler::Speed::STANDARD;  // conservative for diagnostics
        sdmmc.Init(cfg);
        FatFSInterface::Config fs_cfg;
        fs_cfg.media = FatFSInterface::Config::MEDIA_SD;
        fsi.Init(fs_cfg);
        sd_hw_ready = true;
    }
    FATFS& fs = fsi.GetSDFileSystem();
    const char* path = fsi.GetSDPath();
    FRESULT res = f_mount(&fs, path, 1);  // read-only use: mount, list root, unmount
    if(res == FR_OK) {
        result.fs_type = FsTypeName(fs.fs_type);
        const uint64_t sectors = static_cast<uint64_t>(fs.n_fatent - 2) * fs.csize;
        result.size_mb = static_cast<uint32_t>(sectors * _MIN_SS / (1024u * 1024u));
        res = f_opendir(&sd_dir, path);
        if(res == FR_OK) {
            while(result.entries < 1000) {
                res = f_readdir(&sd_dir, &sd_info);
                if(res != FR_OK || sd_info.fname[0] == 0)
                    break;
                ++result.entries;
            }
            f_closedir(&sd_dir);
        }
    }
    f_mount(nullptr, path, 0);
    result.status = res == FR_OK ? diag::SdStatus::Mounted : diag::SdStatus::Error;
    result.fresult = static_cast<int>(res);
    return result;
}

const char* BootloaderName(System::BootInfo::Version version) {
    switch(version) {
        case System::BootInfo::Version::LT_v6_0: return "LT_v6_0";
        case System::BootInfo::Version::NONE: return "NONE";
        case System::BootInfo::Version::v6_0: return "v6_0";
        case System::BootInfo::Version::v6_1: return "v6_1";
        default: return "unknown";
    }
}

void ApplyLeds(uint16_t leds, uint8_t brightness_percent) {
    const float on = brightness_percent / 100.f;
    for(size_t i = 0; i < diag::kNumLeds; ++i)
        hw.SetLed(static_cast<int>(i), (leds >> i) & 1u ? on : 0.f);
    hw.UpdateLeds();  // DMA driver may wait for the previous transfer: main loop only
}
} // namespace

int main() {
    hw.Init();
    hw.seed.SetAudioSampleRate(SaiHandle::Config::SampleRate::SAI_48KHZ);
    hw.seed.SetAudioBlockSize(48);  // 1 kHz control rate, matches AnalogControl setup
    session.Init(BootloaderName(System::GetBootloaderVersion()));

    usb.Init(UsbHandle::FS_EXTERNAL);
    // libDaisy configures USB and audio DMA with priority 0; let audio preempt USB.
    NVIC_SetPriority(OTG_HS_IRQn, 1);
    NVIC_SetPriority(OTG_HS_EP1_IN_IRQn, 1);
    NVIC_SetPriority(OTG_HS_EP1_OUT_IRQn, 1);
    usb.SetReceiveCallback(UsbReceive, UsbHandle::FS_EXTERNAL);

    hw.seed.StartAudio(AudioCallback);
    System::Delay(100);  // let the mux ADC and debouncers settle

    ddp::FrameParser parser;
    diag::Inputs last_sent;
    uint32_t seq = 0;
    uint32_t last_state_ms = 0, last_sys_ms = 0, last_led_ms = 0, last_stat_ms = 0;
    uint32_t last_ticks = control_ticks.load();
    uint16_t last_leds = 0;
    uint8_t last_brightness = 0;
    bool leds_dirty = true;
    bool was_active = false;
    const uint32_t start_ms = System::GetNow();

    while(true) {
        const uint32_t now = System::GetNow();
        uint32_t requests = diag::kRequestNone;

        // Commands from the host.
        uint32_t tail = rx_tail.load(std::memory_order_relaxed);
        const uint32_t head = rx_head.load(std::memory_order_acquire);
        while(tail != head) {
            const char c = static_cast<char>(rx_ring[tail % kRxSize]);
            ++tail;
            if(parser.Feed(c)) {
                char reply_buf[ddp::kMaxBody + 1];
                ddp::Writer reply(reply_buf, sizeof(reply_buf));
                requests |= session.Handle(parser.Body(), now, reply);
                Send(reply);
            }
        }
        rx_tail.store(tail, std::memory_order_release);
        stats.rx_ok = parser.ok;
        stats.rx_bad = parser.bad_crc + parser.bad_format + parser.overflow
                       + rx_overflow.load(std::memory_order_relaxed);

        const diag::Inputs inputs = SnapshotInputs();

        // LEDs: commanded state only, there is no optical feedback.
        const uint16_t leds = diag::ComputeLeds(session.settings, now, inputs.buttons);
        if(requests & diag::kRequestLeds)
            leds_dirty = true;
        if((leds_dirty || leds != last_leds || session.settings.led_brightness != last_brightness)
           && now - last_led_ms >= 10) {
            ApplyLeds(leds, session.settings.led_brightness);
            last_leds = leds;
            last_brightness = session.settings.led_brightness;
            last_led_ms = now;
            leds_dirty = false;
        }

        if(now - last_stat_ms >= 1000) {
            const uint32_t ticks = control_ticks.load(std::memory_order_relaxed);
            stats.control_rate_hz = (ticks - last_ticks) * 1000u / (now - last_stat_ms);
            last_ticks = ticks;
            last_stat_ms = now;
            stats.uptime_s = (now - start_ms) / 1000u;
        }

        if(requests & diag::kRequestSdTest) {
            char body[96];
            ddp::Writer out(body, sizeof(body));
            diag::WriteSd(RunSdTest(inputs.sd_card), out);
            Send(out);
        }

        const bool active = session.HostActive(now);
        if(active && !was_active)
            last_sent = diag::Inputs();  // force a full frame on (re)connect
        if(!active && was_active)
            tx.Discard(stats);
        was_active = active;
        if(active) {
            const uint32_t period = 1000u / session.settings.rate_hz;
            const bool periodic = now - last_state_ms >= period;
            const bool changed = diag::DigitalChanged(inputs, last_sent)
                                 && now - last_state_ms >= diag::kMinFrameSpacingMs;
            if(periodic || changed || (requests & diag::kRequestState)) {
                char body[ddp::kMaxBody + 1];
                ddp::Writer out(body, sizeof(body));
                diag::WriteState(inputs, session.settings, last_leds, seq++, now, out);
                Send(out);
                last_sent = inputs;
                last_state_ms = now;
            }
            if(now - last_sys_ms >= 1000 || (requests & diag::kRequestState)) {
                char body[160];
                ddp::Writer out(body, sizeof(body));
                diag::WriteSys(stats, true, session.settings.rate_hz, out);
                Send(out);
                last_sys_ms = now;
            }
        }
        tx.Pump(stats);

        // Seed USR LED: slow blink = waiting for host, fast blink = host connected.
        hw.seed.SetLed(((now / (active ? 125u : 500u)) & 1u) != 0);
    }
}
