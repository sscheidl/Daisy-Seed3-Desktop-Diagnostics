// Host substitute for ST/CMSIS declarations. The actual project transport is
// compiled unchanged apart from this include. ARM builds use the pinned headers.
#pragma once
#include <cstdint>
#include <cstddef>
#define __NVIC_PRIO_BITS 4
inline uint32_t __get_BASEPRI() { return 0; }
inline void __set_BASEPRI_MAX(uint32_t) {}
inline void __set_BASEPRI(uint32_t) {}
inline void __DSB() {}
inline void __ISB() {}
enum USBD_SpeedTypeDef { USBD_SPEED_FULL };
constexpr uint8_t USBD_OK=0, USBD_FAIL=3, USBD_STATE_CONFIGURED=3, USBD_EP_TYPE_BULK=2;
constexpr uint8_t USB_REQ_RECIPIENT_ENDPOINT=2, USB_REQ_RECIPIENT_INTERFACE=1;
constexpr uint8_t USB_REQ_CLEAR_FEATURE=1, USB_REQ_GET_STATUS=0;
constexpr uint8_t USB_REQ_GET_INTERFACE=10, USB_REQ_SET_INTERFACE=11;
constexpr uint8_t DEVICE_HS=1, HAL_OK=0;
struct USBD_SetupReqTypedef { uint8_t bmRequest, bRequest; uint16_t wValue, wIndex, wLength; };
struct USBD_HandleTypeDef;
using Simple = uint8_t (*)(USBD_HandleTypeDef*);
using Endpoint = uint8_t (*)(USBD_HandleTypeDef*, uint8_t);
struct USBD_ClassTypeDef {
    Endpoint Init, DeInit;
    uint8_t (*Setup)(USBD_HandleTypeDef*, USBD_SetupReqTypedef*);
    Simple EP0_TxSent, EP0_RxReady;
    Endpoint DataIn, DataOut;
    Simple SOF;
    Endpoint IsoINIncomplete, IsoOUTIncomplete;
    uint8_t* (*GetHSConfigDescriptor)(uint16_t*);
    uint8_t* (*GetFSConfigDescriptor)(uint16_t*);
    uint8_t* (*GetOtherSpeedConfigDescriptor)(uint16_t*);
    uint8_t* (*GetDeviceQualifierDescriptor)(uint16_t*);
};
using Descriptor = uint8_t* (*)(USBD_SpeedTypeDef, uint16_t*);
struct USBD_DescriptorsTypeDef {
    Descriptor GetDeviceDescriptor, GetLangIDStrDescriptor, GetManufacturerStrDescriptor;
    Descriptor GetProductStrDescriptor, GetSerialStrDescriptor;
    Descriptor GetConfigurationStrDescriptor, GetInterfaceStrDescriptor;
};
struct EndpointInfo { uint8_t is_used = 0; };
struct USBD_HandleTypeDef {
    uint8_t dev_state = 0;
    EndpointInfo ep_in[9], ep_out[9];
};
struct PCD_HandleTypeDef {};
extern USBD_ClassTypeDef USBD_CDC;
extern USBD_DescriptorsTypeDef HS_Desc;
extern int USBD_Interface_fops_HS;
uint8_t USBD_Init(USBD_HandleTypeDef*, USBD_DescriptorsTypeDef*, uint8_t);
uint8_t USBD_RegisterClass(USBD_HandleTypeDef*, USBD_ClassTypeDef*);
uint8_t USBD_CDC_RegisterInterface(USBD_HandleTypeDef*, void*);
uint8_t USBD_Start(USBD_HandleTypeDef*);
uint8_t USBD_LL_Transmit(USBD_HandleTypeDef*, uint8_t, uint8_t*, uint16_t);
uint8_t USBD_LL_PrepareReceive(USBD_HandleTypeDef*, uint8_t, uint8_t*, uint16_t);
uint8_t USBD_LL_OpenEP(USBD_HandleTypeDef*, uint8_t, uint8_t, uint16_t);
uint8_t USBD_LL_CloseEP(USBD_HandleTypeDef*, uint8_t);
uint8_t USBD_LL_StallEP(USBD_HandleTypeDef*, uint8_t);
uint8_t USBD_LL_ClearStallEP(USBD_HandleTypeDef*, uint8_t);
uint32_t USBD_LL_GetRxDataSize(USBD_HandleTypeDef*, uint8_t);
uint8_t USBD_CtlSendData(USBD_HandleTypeDef*, uint8_t*, uint16_t);
void USBD_CtlError(USBD_HandleTypeDef*, USBD_SetupReqTypedef*);
void USBD_GetString(uint8_t*, uint8_t*, uint16_t*);
uint8_t HAL_PCDEx_SetRxFiFo(PCD_HandleTypeDef*, uint16_t);
uint8_t HAL_PCDEx_SetTxFiFo(PCD_HandleTypeDef*, uint8_t, uint16_t);
void HAL_PWREx_EnableUSBVoltageDetector();
