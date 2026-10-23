#include "reader_usb.h"
#include "msc_bot.h"
#ifdef DIAG_USB_HOST_TEST
#include "reader_usb_stub.h"
#else
#include "usbd_core.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"
#include "usbd_desc.h"
#include "usbd_ctlreq.h"
#include "usbd_ioreq.h"
#include "stm32h7xx_hal.h"
#endif
#include <atomic>
#include <cstring>

extern "C" USBD_HandleTypeDef hUsbDeviceHS;
extern "C" PCD_HandleTypeDef hpcd_USB_OTG_HS;

namespace {
constexpr uint8_t kOut = 3, kIn = 0x83;
struct UsbGuard {
    uint32_t saved = __get_BASEPRI();
    UsbGuard() { __set_BASEPRI_MAX(1u << (8u - __NVIC_PRIO_BITS)); __DSB(); __ISB(); }
    ~UsbGuard() { __set_BASEPRI(saved); }
};
// USB DMA is disabled in the pinned HAL setup. These are CPU/FIFO buffers, not
// SDMMC IDMA buffers. RX is never rearmed until the main loop has consumed it.
alignas(4) uint8_t rx[512], tx[512];
std::atomic<uint32_t> generation{0};
bool configured = false, configure_event = false, disconnect_event = false;
bool reset_event = false, tx_event = false;
uint8_t clear_events = 0;
uint16_t rx_size = 0;
bool rx_event = false;
uint32_t pump_generation = 0;
diag::CardReader* reader = nullptr;
diag::MscBot* bot = nullptr;

// 9 configuration + 8 CDC IAD + 58 CDC function + 23 MSC function = 98 bytes.
alignas(4) uint8_t config[] = {
    9, 2, 98, 0, 3, 1, 0, 0x80, 250,
    8, 11, 0, 2, 2, 2, 1, 0,
    9, 4, 0, 0, 1, 2, 2, 1, 0,
    5, 0x24, 0, 0x10, 1,
    5, 0x24, 1, 0, 1,
    4, 0x24, 2, 2,
    5, 0x24, 6, 0, 1,
    7, 5, 0x82, 3, 8, 0, 16,
    9, 4, 1, 0, 2, 0x0a, 0, 0, 0,
    7, 5, 1, 2, 64, 0, 0,
    7, 5, 0x81, 2, 64, 0, 0,
    9, 4, 2, 0, 2, 8, 6, 0x50, 0,
    7, 5, kOut, 2, 64, 0, 0,
    7, 5, kIn, 2, 64, 0, 0,
};
static_assert(sizeof(config) == 98, "Composite descriptor size");
uint8_t* Config(uint16_t* n) { *n = sizeof(config); return config; }
alignas(4) uint8_t device[18], serial[30];
uint8_t* Device(USBD_SpeedTypeDef speed, uint16_t* n) {
    uint8_t* original = HS_Desc.GetDeviceDescriptor(speed, n);
    std::memcpy(device, original, sizeof(device));
    device[4] = 0xef; device[5] = 2; device[6] = 1;  // IAD composite device
    device[12] = 0; device[13] = 3;  // bcdDevice 3.00, separate Windows instance
    return device;
}
uint8_t* Serial(USBD_SpeedTypeDef speed, uint16_t* n) {
    uint8_t* original = HS_Desc.GetSerialStrDescriptor(speed, n);
    std::memcpy(serial, original, 26);
    serial[0] = sizeof(serial); serial[26] = 'A'; serial[27] = 0;
    serial[28] = '1'; serial[29] = 0; *n = sizeof(serial); // MSC serial stays hexadecimal
    return serial;
}
uint8_t* Product(USBD_SpeedTypeDef, uint16_t* n) {
    static uint8_t text[100];
    USBD_GetString(reinterpret_cast<uint8_t*>(const_cast<char*>("Daisy diagnostics + SD reader")), text, n);
    return text;
}
bool CanSubmit() {
    return configured && generation.load(std::memory_order_relaxed) == pump_generation
           && hUsbDeviceHS.dev_state == USBD_STATE_CONFIGURED;
}
class Port final : public diag::MscPort {
  public:
    void Send(const uint8_t* data, uint16_t size) override {
        UsbGuard guard;
        if(!CanSubmit() || size > sizeof(tx)) return;
        std::memcpy(tx, data, size);
        if(USBD_LL_Transmit(&hUsbDeviceHS, kIn, tx, size) != USBD_OK)
            disconnect_event = true;
    }
    void Receive(uint16_t size) override {
        UsbGuard guard;
        if(CanSubmit() && USBD_LL_PrepareReceive(&hUsbDeviceHS, kOut, rx, size) != USBD_OK)
            disconnect_event = true;
    }
    void Halt(bool in) override {
        UsbGuard guard;
        if(CanSubmit()) USBD_LL_StallEP(&hUsbDeviceHS, in ? kIn : kOut);
    }
};
Port port;

uint8_t Init(USBD_HandleTypeDef* dev, uint8_t cfg) {
    // Reallocate the single 1024-word OTG-HS FIFO across all IN endpoints.
    if(HAL_PCDEx_SetRxFiFo(&hpcd_USB_OTG_HS, 256) != HAL_OK
       || HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_HS, 0, 64) != HAL_OK
       || HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_HS, 1, 128) != HAL_OK
       || HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_HS, 2, 16) != HAL_OK
       || HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_HS, 3, 128) != HAL_OK)
        return USBD_FAIL;
    if(USBD_CDC.Init(dev, cfg) != USBD_OK) return USBD_FAIL;
    if(USBD_LL_OpenEP(dev, kOut, USBD_EP_TYPE_BULK, 64) != USBD_OK
       || USBD_LL_OpenEP(dev, kIn, USBD_EP_TYPE_BULK, 64) != USBD_OK) {
        USBD_CDC.DeInit(dev, cfg);
        return USBD_FAIL;
    }
    dev->ep_out[3].is_used = dev->ep_in[3].is_used = 1;
    configured = configure_event = true;
    generation.fetch_add(1, std::memory_order_relaxed);
    return USBD_OK;
}
uint8_t DeInit(USBD_HandleTypeDef* dev, uint8_t cfg) {
    configured = false;
    disconnect_event = true;
    configure_event = rx_event = tx_event = reset_event = false;
    clear_events = 0;
    generation.fetch_add(1, std::memory_order_relaxed);
    USBD_LL_CloseEP(dev, kIn); USBD_LL_CloseEP(dev, kOut);
    dev->ep_out[3].is_used = dev->ep_in[3].is_used = 0;
    return USBD_CDC.DeInit(dev, cfg);
}
uint8_t Setup(USBD_HandleTypeDef* dev, USBD_SetupReqTypedef* req) {
    const uint8_t recipient = req->bmRequest & 0x1f;
    if(recipient == USB_REQ_RECIPIENT_ENDPOINT && (req->wIndex == kOut || req->wIndex == kIn)
       && req->bmRequest == 2 && req->bRequest == USB_REQ_CLEAR_FEATURE
       && req->wValue == 0 && req->wLength == 0) {
        clear_events |= req->wIndex == kIn ? 1 : 2;
        return USBD_OK;
    }
    if(recipient == USB_REQ_RECIPIENT_INTERFACE && req->wIndex == 2) {
        static uint8_t zero[2] = {};
        if(req->bmRequest == 0xa1 && req->bRequest == 0xfe && req->wValue == 0 && req->wLength == 1)
            return uint8_t(USBD_CtlSendData(dev, zero, 1));  // GET MAX LUN
        if(req->bmRequest == 0x21 && req->bRequest == 0xff && req->wValue == 0 && req->wLength == 0) {
            reset_event = true; clear_events = 0; rx_event = tx_event = false;
            generation.fetch_add(1, std::memory_order_relaxed);
            return USBD_OK;
        }
        if(req->bmRequest == 0x81 && req->bRequest == USB_REQ_GET_INTERFACE
           && req->wValue == 0 && req->wLength == 1)
            return uint8_t(USBD_CtlSendData(dev, zero, 1));
        if(req->bmRequest == 0x81 && req->bRequest == USB_REQ_GET_STATUS
           && req->wValue == 0 && req->wLength == 2)
            return uint8_t(USBD_CtlSendData(dev, zero, 2));
        if(req->bmRequest == 1 && req->bRequest == USB_REQ_SET_INTERFACE
           && req->wValue == 0 && req->wLength == 0) return USBD_OK;
        USBD_CtlError(dev, req); return USBD_FAIL;
    }
    if((recipient == USB_REQ_RECIPIENT_INTERFACE && req->wIndex < 2)
       || (recipient == USB_REQ_RECIPIENT_ENDPOINT
           && (req->wIndex == 1 || req->wIndex == 0x81 || req->wIndex == 0x82)))
        return USBD_CDC.Setup(dev, req);
    USBD_CtlError(dev, req); return USBD_FAIL;
}
uint8_t DataIn(USBD_HandleTypeDef* dev, uint8_t ep) {
    if(ep == 3) { tx_event = true; return USBD_OK; }
    return USBD_CDC.DataIn(dev, ep);
}
uint8_t DataOut(USBD_HandleTypeDef* dev, uint8_t ep) {
    if(ep == 3) {
        rx_size = uint16_t(USBD_LL_GetRxDataSize(dev, ep)); rx_event = true;
        return USBD_OK;  // no parsing, SD access or endpoint rearm in this ISR
    }
    return USBD_CDC.DataOut(dev, ep);
}
USBD_ClassTypeDef composite{};
USBD_DescriptorsTypeDef descriptors{};
}
bool InitReaderUsb(diag::CardReader& card) {
    reader = &card;
    static diag::MscBot transport(card, port);
    bot = &transport;
    composite = USBD_CDC;
    composite.Init = Init; composite.DeInit = DeInit; composite.Setup = Setup;
    composite.DataIn = DataIn; composite.DataOut = DataOut;
    composite.GetFSConfigDescriptor = Config;
    composite.GetHSConfigDescriptor = Config;
    // The physical port is Full Speed only; no other-speed configuration.
    composite.GetOtherSpeedConfigDescriptor = nullptr;
    composite.GetDeviceQualifierDescriptor = nullptr;
    descriptors = HS_Desc;
    descriptors.GetDeviceDescriptor = Device;
    descriptors.GetSerialStrDescriptor = Serial;
    descriptors.GetProductStrDescriptor = Product;
    HAL_PWREx_EnableUSBVoltageDetector();
    return USBD_Init(&hUsbDeviceHS, &descriptors, DEVICE_HS) == USBD_OK
           && USBD_RegisterClass(&hUsbDeviceHS, &composite) == USBD_OK
           && USBD_CDC_RegisterInterface(&hUsbDeviceHS, &USBD_Interface_fops_HS) == USBD_OK
           && USBD_Start(&hUsbDeviceHS) == USBD_OK;
}
bool ReaderUsbIdle() { return bot && bot->Idle(); }
bool ReaderUsbInterrupted() {
    UsbGuard guard;
    return disconnect_event || reset_event || !configured;
}
void PollReaderUsb() {
    bool lost, start, reset, sent, received;
    uint8_t clear;
    uint16_t size;
    alignas(4) uint8_t packet[512];
    {
        UsbGuard guard;
        lost = disconnect_event; start = configure_event; reset = reset_event;
        sent = tx_event; received = rx_event; clear = clear_events; size = rx_size;
        if(received && size <= sizeof(packet)) std::memcpy(packet, rx, size);
        disconnect_event = configure_event = reset_event = tx_event = rx_event = false;
        clear_events = 0;
        pump_generation = generation.load(std::memory_order_relaxed);
    }
    if(lost) bot->Disconnect();
    if(start) bot->Configure();
    if(reset) bot->Reset();
    if(sent) bot->InComplete();
    if(received) bot->Out(packet, size <= sizeof(packet) ? size : 0);
    // Reapply the already-ACKed clear after deferred BOT reset handling. Otherwise
    // a fast reset+clear sequence could be re-stalled by the main-loop reset.
    for(uint8_t bit = 1; bit <= 2; bit <<= 1) {
        if(!(clear & bit)) continue;
        {
            UsbGuard guard;
            if(CanSubmit()) USBD_LL_ClearStallEP(&hUsbDeviceHS, bit == 1 ? kIn : kOut);
        }
        bot->ClearHalt(bit == 1);
    }
    // A bus reset may have happened during a bounded SD operation. Prevent another
    // local/MSC operation until next poll processes that event. Port submission is
    // already blocked by generation mismatch while this iteration unwinds.
    {
        UsbGuard guard;
        if(generation.load(std::memory_order_relaxed) != pump_generation) reader->Interrupt();
    }
}
