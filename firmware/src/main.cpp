// Daisy Seed3 Desktop Dev Kit - hardware diagnostic firmware.
// Hardware glue only: panel controls through the official desktop_devkit::Hardware
// class, USB CDC on carrier port J7 and a read-only microSD driver. The protocol and
// main-loop logic live in diag_app.* / diag_core.* and are tested on the host.
#include "desktop_devkit.h"
#include "per/sdmmc.h"
#include "usbd_core.h"
#include "ff.h"
#include "ff_gen_drv.h"
#include "diag_app.h"
#include <atomic>
#include <cstring>
#ifdef DIAG_CARD_READER
#include "reader_usb.h"
#endif

extern "C" {
#include "util/bsp_sd_diskio.h"
}

using namespace daisy;

extern "C" USBD_HandleTypeDef hUsbDeviceHS;  // libDaisy src/hid/usb.cpp
extern SD_HandleTypeDef hsd1;                // libDaisy src/per/sdmmc.cpp

namespace {
desktop_devkit::Hardware hw;
UsbHandle usb;

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

// ---- USB CDC transmit -------------------------------------------------------------
// libDaisy's CDC_Transmit_HS() dereferences the class data without a NULL check, and
// a USB reset handled in the OTG_HS interrupt frees that data (pClassData = NULL).
// The readiness check and the start of the transfer therefore run with the USB
// interrupt (priority 1) masked via BASEPRI; the audio interrupt (priority 0) still runs.
constexpr uint32_t kUsbIrqPriority = 1;

class CdcSink final : public diag::UsbSink {
  public:
    diag::SendResult Send(const uint8_t* data, size_t len) override {
        const uint32_t saved = __get_BASEPRI();
        __set_BASEPRI(kUsbIrqPriority << (8u - __NVIC_PRIO_BITS));
        __DSB();
        __ISB();
        diag::SendResult result;
        if(hUsbDeviceHS.dev_state != USBD_STATE_CONFIGURED || hUsbDeviceHS.pClassData == nullptr)
            result = diag::SendResult::NotReady;
        else if(usb.TransmitExternal(const_cast<uint8_t*>(data), len) == UsbHandle::Result::OK)
            result = diag::SendResult::Ok;
        else
            result = diag::SendResult::Busy;
        __set_BASEPRI(saved);
        return result;
    }
};
CdcSink cdc_sink;

// ---- microSD: read-only, time-bounded block driver ------------------------------
// Instead of libDaisy's SD_Driver this firmware links its own FatFs disk driver:
//  * its write entry only returns RES_WRPRT and it always reports STA_PROTECT, so
//    FatFs refuses any write access (FR_WRITE_PROTECTED); no SD write or erase
//    command is linked at all (checked by `make check`);
//  * each read waits at most kSdOpTimeoutMs and a whole test at most kSdBudgetMs,
//    unlike libDaisy's SD_read() with two 30 s waits per operation;
//  * it is re-linked before every test, which resets FatFs' "initialised" flag, so a
//    swapped card or a failed first attempt is initialised again.
// With BOOT_SRAM, .bss lives in DTCM, which SDMMC1's IDMA cannot reach; the FATFS
// object (including its sector window) therefore lives in SDRAM.
constexpr uint32_t kSdOpTimeoutMs = 1000;
constexpr uint32_t kSdBudgetMs = 5000;
constexpr uint32_t kSdBlockSize = 512;
uint32_t sd_deadline = 0;

bool SdBudgetLeft() {
    return static_cast<int32_t>(sd_deadline - HAL_GetTick()) > 0;
}

bool SdWaitTransferState(uint32_t start) {
    while(BSP_SD_GetCardState() != SD_TRANSFER_OK)
        if(HAL_GetTick() - start > kSdOpTimeoutMs || !SdBudgetLeft())
            return false;
    return true;
}

extern "C" DSTATUS RoStatus(BYTE) {
    return static_cast<DSTATUS>(
        (BSP_SD_GetCardState() == SD_TRANSFER_OK ? 0 : STA_NOINIT) | STA_PROTECT);
}

extern "C" DSTATUS RoInitialize(BYTE lun) {
    if(BSP_SD_Init() != MSD_OK)
        return STA_NOINIT | STA_PROTECT;
    return RoStatus(lun);
}

extern "C" DRESULT RoRead(BYTE, BYTE* buff, DWORD sector, UINT count) {
    if(!SdBudgetLeft())
        return RES_ERROR;
    const uint32_t aligned = reinterpret_cast<uint32_t>(buff) & ~0x1Fu;
    const int32_t span = static_cast<int32_t>(count * kSdBlockSize
                                              + (reinterpret_cast<uint32_t>(buff) - aligned));
    SCB_CleanDCache_by_Addr(reinterpret_cast<uint32_t*>(aligned), span);
    const uint32_t start = HAL_GetTick();
    if(!SdWaitTransferState(start))
        return RES_ERROR;
    if(BSP_SD_ReadBlocks_DMA(reinterpret_cast<uint32_t*>(buff), sector, count) != MSD_OK)
        return RES_ERROR;
    while(hsd1.State == HAL_SD_STATE_BUSY) {  // set back to READY by the SDMMC1 IRQ
        if(HAL_GetTick() - start > kSdOpTimeoutMs || !SdBudgetLeft()) {
            HAL_SD_Abort(&hsd1);
            return RES_ERROR;
        }
    }
    if(hsd1.ErrorCode != HAL_SD_ERROR_NONE || !SdWaitTransferState(start))
        return RES_ERROR;
    SCB_InvalidateDCache_by_Addr(reinterpret_cast<uint32_t*>(aligned), span);
    return RES_OK;
}

// Never reaches the card: refuses every write. FatFs does not call it because the
// volume reports STA_PROTECT; it exists so the driver table has no NULL entry.
extern "C" DRESULT RoWrite(BYTE, const BYTE*, DWORD, UINT) {
    return RES_WRPRT;
}

extern "C" DRESULT RoIoctl(BYTE, BYTE cmd, void*) {
    return cmd == CTRL_SYNC ? RES_OK : RES_PARERR;
}

const Diskio_drvTypeDef kReadOnlySd = {
    RoInitialize,
    RoStatus,
    RoRead,
#if _USE_WRITE == 1
    RoWrite,
#endif
#if _USE_IOCTL == 1
    RoIoctl,
#endif
};

SdmmcHandler sdmmc;
bool sdmmc_configured = false;
char sd_path[4] = {};
DSY_SDRAM_BSS alignas(32) FATFS sd_fs;
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
    if(!sdmmc_configured) {
        SdmmcHandler::Config cfg;
        cfg.Defaults();
        cfg.speed = SdmmcHandler::Speed::STANDARD;  // conservative for diagnostics
        sdmmc.Init(cfg);
        sdmmc_configured = true;
    } else if(hsd1.State != HAL_SD_STATE_RESET) {
        HAL_SD_DeInit(&hsd1);  // power the card interface down; Init runs again below
    }
    FATFS_LinkDriver(&kReadOnlySd, sd_path);  // fresh link = FatFs initialises again
    sd_deadline = HAL_GetTick() + kSdBudgetMs;

    FRESULT res = f_mount(&sd_fs, sd_path, 1);  // mount, list root, unmount
    if(res == FR_OK) {
        result.fs_type = FsTypeName(sd_fs.fs_type);
        const uint64_t sectors = static_cast<uint64_t>(sd_fs.n_fatent - 2) * sd_fs.csize;
        result.size_mb = static_cast<uint32_t>(sectors * kSdBlockSize / (1024u * 1024u));
        res = f_opendir(&sd_dir, sd_path);
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
    f_mount(nullptr, sd_path, 0);
    FATFS_UnLinkDriver(sd_path);
    result.status = res == FR_OK ? diag::SdStatus::Mounted : diag::SdStatus::Error;
    result.fresult = static_cast<int>(res);
    return result;
}

#ifdef DIAG_CARD_READER
bool CardPresent() {
    const uint32_t saved = __get_PRIMASK();
    __disable_irq();
    const bool present = callback_inputs.sd_card;
    __set_PRIMASK(saved);
    return present;
}
// MSC uses polling SD I/O in the MAIN LOOP, never in the USB interrupt. This
// avoids IDMA/cache ownership entirely on the MSC path: aligned DTCM buffers are
// accessed by the CPU, not SDMMC DMA. The original read-only FatFs DMA path above
// is unchanged and is unreachable while MSC owns the card.
class ReaderCard final : public diag::CardDevice {
  public:
    bool Open(uint32_t& sectors) override {
        if(hsd1.State != HAL_SD_STATE_RESET) HAL_SD_DeInit(&hsd1);
        SdmmcHandler::Config cfg; cfg.Defaults();
        cfg.speed = SdmmcHandler::Speed::STANDARD;
        sdmmc.Init(cfg); sdmmc_configured = true;
        if(BSP_SD_Init() != MSD_OK || ReaderUsbInterrupted()) return false;
        NVIC_SetPriority(SDMMC1_IRQn, 2);  // audio=0, USB=1; MSC never waits in an ISR
        HAL_SD_CardInfoTypeDef info{};
        if(HAL_SD_GetCardInfo(&hsd1, &info) != HAL_OK || info.LogBlockSize != 512)
            return false;
        sectors = info.LogBlockNbr;
        return sectors != 0;
    }
    bool Read(uint32_t lba, uint8_t* block) override {
        if(!Available() || HAL_SD_ReadBlocks(&hsd1, bounce_, lba, 1, kSdOpTimeoutMs) != HAL_OK)
            return Abort();
        if(!Sync()) return false;
        std::memcpy(block, bounce_, 512);
        return true;
    }
    bool Write(uint32_t lba, const uint8_t* block) override {
        if(!Available()) return false;
        std::memcpy(bounce_, block, 512);
        if(HAL_SD_WriteBlocks(&hsd1, bounce_, lba, 1, kSdOpTimeoutMs) != HAL_OK)
            return Abort();
        return Sync();  // includes card programming; no write cache in firmware
    }
    bool Sync() override {
        const uint32_t start = HAL_GetTick();
        do {
            if(!Available() || HAL_GetTick() - start >= kSdOpTimeoutMs) return Abort();
            if(HAL_SD_GetCardState(&hsd1) == HAL_SD_CARD_TRANSFER) return true;
        } while(true);
    }
    void Close() override { HAL_SD_Abort(&hsd1); HAL_SD_DeInit(&hsd1); }
  private:
    bool Available() { return CardPresent() && !ReaderUsbInterrupted(); }
    bool Abort() { HAL_SD_Abort(&hsd1); return false; }
    alignas(4) uint8_t bounce_[512] = {};
};
ReaderCard reader_card;
diag::CardReader card_reader(reader_card);
#endif

// ---- Board implementation ---------------------------------------------------------
class DevkitBoard final : public diag::Board {
  public:
    diag::Inputs ReadInputs() override {
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

    uint32_t ControlTicks() override { return control_ticks.load(std::memory_order_relaxed); }

    void ApplyLeds(uint16_t leds, uint8_t brightness_percent) override {
        const float on = brightness_percent / 100.f;
        for(size_t i = 0; i < diag::kNumLeds; ++i)
            hw.SetLed(static_cast<int>(i), (leds >> i) & 1u ? on : 0.f);
        hw.UpdateLeds();  // DMA driver may wait for the previous transfer: main loop only
    }

    diag::SdResult RunSdTest(bool card_present) override { return ::RunSdTest(card_present); }
#ifdef DIAG_CARD_READER
    bool SdTestAllowed() override { return card_reader.Local(); }
    void ReaderCommand(uint32_t command, ddp::Writer& out) override {
        bool ok = true;
        if(command & diag::kRequestReaderShare)
            ok = ReaderUsbIdle() && card_reader.Share(CardPresent());
        if(command & diag::kRequestReaderReturn)
            ok = ReaderUsbIdle() && card_reader.Return();
        if(!ok) out.Str("ERR c=READER e=STATE");
        else out.Str("READER state=").Str(diag::ReaderStateName(card_reader.State()))
            .Str(" sectors=").U32(card_reader.Sectors()).Str(" busy=").U32(!ReaderUsbIdle())
            .Str(" a=").Str(command & diag::kRequestReaderShare ? "SHARE" :
                            command & diag::kRequestReaderReturn ? "RETURN" : "STATUS");
    }
#endif
};
DevkitBoard board;

const char* BootloaderName(System::BootInfo::Version version) {
    switch(version) {
        case System::BootInfo::Version::LT_v6_0: return "LT_v6_0";
        case System::BootInfo::Version::NONE: return "NONE";
        case System::BootInfo::Version::v6_0: return "v6_0";
        case System::BootInfo::Version::v6_1: return "v6_1";
        default: return "unknown";
    }
}

diag::App* app = nullptr;

void UsbReceive(uint8_t* buf, uint32_t* len) {
    // USB interrupt: copy only, never parse or transmit here.
    if(app && buf && len)
        app->OnUsbReceive(buf, *len);
}
} // namespace

int main() {
    hw.Init();
    hw.seed.SetAudioSampleRate(SaiHandle::Config::SampleRate::SAI_48KHZ);
    hw.seed.SetAudioBlockSize(48);  // 1 kHz control rate, matches AnalogControl setup

    static diag::App diagnostic(board, cdc_sink,
                                BootloaderName(System::GetBootloaderVersion()),
                                System::GetNow());
    app = &diagnostic;

#ifdef DIAG_CARD_READER
    if(!InitReaderUsb(card_reader)) while(true) { hw.seed.SetLed(true); }
#else
    usb.Init(UsbHandle::FS_EXTERNAL);
#endif
    // libDaisy configures USB and audio DMA with priority 0; let audio preempt USB.
    NVIC_SetPriority(OTG_HS_IRQn, kUsbIrqPriority);
    NVIC_SetPriority(OTG_HS_EP1_IN_IRQn, kUsbIrqPriority);
    NVIC_SetPriority(OTG_HS_EP1_OUT_IRQn, kUsbIrqPriority);
    usb.SetReceiveCallback(UsbReceive, UsbHandle::FS_EXTERNAL);

    hw.seed.StartAudio(AudioCallback);
    System::Delay(100);  // let the mux ADC and debouncers settle

    while(true) {
        const uint32_t now = System::GetNow();
#ifdef DIAG_CARD_READER
        PollReaderUsb();
        card_reader.Observe(CardPresent());
#endif
        diagnostic.Step(now);
        // Seed USR LED: slow blink = waiting for host, fast blink = host connected.
        hw.seed.SetLed(((now / (diagnostic.HostActive(now) ? 125u : 500u)) & 1u) != 0);
    }
}
