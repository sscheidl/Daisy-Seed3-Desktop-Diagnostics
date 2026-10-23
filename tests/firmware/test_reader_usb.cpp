// Runs the actual composite descriptor/dispatch/mailbox adapter against a fake
// HAL. SD callbacks must never execute during the simulated ISR calls.
#include "reader_usb_stub.h"
#include "reader_usb.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <vector>

extern "C" { USBD_HandleTypeDef hUsbDeviceHS; PCD_HandleTypeDef hpcd_USB_OTG_HS; }
USBD_ClassTypeDef USBD_CDC{};
USBD_DescriptorsTypeDef HS_Desc{};
int USBD_Interface_fops_HS = 0;
USBD_ClassTypeDef* klass = nullptr;
USBD_DescriptorsTypeDef* descriptors = nullptr;
uint8_t* rx_pointer = nullptr;
uint16_t rx_expected = 0;
uint32_t rx_actual = 0;
std::vector<std::vector<uint8_t>> sent;
bool halted[256]{};
uint16_t fifo_words = 0;
unsigned cdc_in = 0, cdc_out = 0, cdc_setup = 0, control_errors = 0;
unsigned checks = 0, failures = 0;
#define CHECK(x) do { ++checks; if(!(x)) { ++failures; std::printf("FAIL %d: %s\n", __LINE__, #x); } } while(0)
uint8_t USBD_Init(USBD_HandleTypeDef*, USBD_DescriptorsTypeDef* d, uint8_t) { descriptors = d; return USBD_OK; }
uint8_t USBD_RegisterClass(USBD_HandleTypeDef*, USBD_ClassTypeDef* c) { klass = c; return USBD_OK; }
uint8_t USBD_CDC_RegisterInterface(USBD_HandleTypeDef*, void*) { return USBD_OK; }
uint8_t USBD_Start(USBD_HandleTypeDef*) { return USBD_OK; }
uint8_t USBD_LL_Transmit(USBD_HandleTypeDef*, uint8_t ep, uint8_t* p, uint16_t n) {
    CHECK(ep == 0x83); sent.emplace_back(p, p+n); return USBD_OK;
}
uint8_t USBD_LL_PrepareReceive(USBD_HandleTypeDef*, uint8_t ep, uint8_t* p, uint16_t n) {
    CHECK(ep == 3); rx_pointer = p; rx_expected = n; return USBD_OK;
}
uint8_t USBD_LL_OpenEP(USBD_HandleTypeDef*, uint8_t ep, uint8_t type, uint16_t n) {
    CHECK((ep == 3 || ep == 0x83) && type == 2 && n == 64); return USBD_OK;
}
uint8_t USBD_LL_CloseEP(USBD_HandleTypeDef*, uint8_t) { return USBD_OK; }
uint8_t USBD_LL_StallEP(USBD_HandleTypeDef*, uint8_t ep) { halted[ep] = true; return USBD_OK; }
uint8_t USBD_LL_ClearStallEP(USBD_HandleTypeDef*, uint8_t ep) { halted[ep] = false; return USBD_OK; }
uint32_t USBD_LL_GetRxDataSize(USBD_HandleTypeDef*, uint8_t) { return rx_actual; }
uint8_t USBD_CtlSendData(USBD_HandleTypeDef*, uint8_t* p, uint16_t n) {
    CHECK((n == 1 || n == 2) && p[0] == 0); return USBD_OK;
}
void USBD_CtlError(USBD_HandleTypeDef*, USBD_SetupReqTypedef*) { ++control_errors; }
void USBD_GetString(uint8_t* p, uint8_t* out, uint16_t* n) {
    *n = uint16_t(std::strlen(reinterpret_cast<char*>(p))*2+2);
    out[0] = uint8_t(*n); out[1] = 3;
    for(unsigned i=2; i<*n; i+=2) { out[i] = *p++; out[i+1] = 0; }
}
uint8_t HAL_PCDEx_SetRxFiFo(PCD_HandleTypeDef*, uint16_t n) { fifo_words=n; return HAL_OK; }
uint8_t HAL_PCDEx_SetTxFiFo(PCD_HandleTypeDef*, uint8_t, uint16_t n) { fifo_words+=n; return HAL_OK; }
void HAL_PWREx_EnableUSBVoltageDetector() {}
uint8_t* Device(USBD_SpeedTypeDef, uint16_t* n) { static uint8_t d[18]{}; *n=18; return d; }
uint8_t* Serial(USBD_SpeedTypeDef, uint16_t* n) { static uint8_t d[26]{}; *n=26; return d; }
uint8_t Init(USBD_HandleTypeDef*, uint8_t) { return USBD_OK; }
uint8_t CdcIn(USBD_HandleTypeDef*, uint8_t) { ++cdc_in; return USBD_OK; }
uint8_t CdcOut(USBD_HandleTypeDef*, uint8_t) { ++cdc_out; return USBD_OK; }
uint8_t CdcSetup(USBD_HandleTypeDef*, USBD_SetupReqTypedef*) { ++cdc_setup; return USBD_OK; }
void Setup(uint8_t bm, uint8_t req, uint16_t value, uint16_t index, uint16_t n) {
    USBD_SetupReqTypedef request{bm,req,value,index,n}; klass->Setup(&hUsbDeviceHS,&request);
}
void ResetBus() {
    hUsbDeviceHS.dev_state=0; klass->DeInit(&hUsbDeviceHS,1);
    klass->Init(&hUsbDeviceHS,1); hUsbDeviceHS.dev_state=USBD_STATE_CONFIGURED;
}
class Card : public diag::CardDevice {
  public:
    unsigned reads=0, writes=0;
    bool reset_on_read=false;
    bool Open(uint32_t& n) override { n=8; return true; }
    bool Read(uint32_t, uint8_t* p) override {
        ++reads; std::memset(p,0xab,512);
        if(reset_on_read) ResetBus();
        return true;
    }
    bool Write(uint32_t,const uint8_t*) override { ++writes; return true; }
    bool Sync() override { return true; }
    void Close() override {}
};
void Out(uint8_t opcode, uint32_t n=0) {
    CHECK(rx_expected==31);
    std::array<uint8_t,31> cbw{};
    cbw[0]='U'; cbw[1]='S'; cbw[2]='B'; cbw[3]='C';
    cbw[8]=uint8_t(n); cbw[9]=uint8_t(n>>8); cbw[12]=0x80; cbw[14]=10;
    cbw[15]=opcode; if(opcode==0x28) cbw[23]=1;
    std::memcpy(rx_pointer,cbw.data(),31); rx_actual=31;
    klass->DataOut(&hUsbDeviceHS,3);
}
int main() {
    HS_Desc.GetDeviceDescriptor=Device; HS_Desc.GetSerialStrDescriptor=Serial;
    USBD_CDC.Init=Init; USBD_CDC.DeInit=Init;
    USBD_CDC.DataIn=CdcIn; USBD_CDC.DataOut=CdcOut; USBD_CDC.Setup=CdcSetup;
    Card card; diag::CardReader reader(card);
    CHECK(InitReaderUsb(reader)); CHECK(!reader.Ready());
    uint16_t n=0; auto d=descriptors->GetDeviceDescriptor(USBD_SPEED_FULL,&n);
    CHECK(n==18 && d[4]==0xef && d[5]==2 && d[6]==1);
    d=descriptors->GetSerialStrDescriptor(USBD_SPEED_FULL,&n);
    CHECK(n==30 && d[26]=='A' && d[28]=='1');
    auto cfg=klass->GetFSConfigDescriptor(&n);
    CHECK(n==98 && cfg[2]==98 && cfg[4]==3);
    unsigned interfaces=0, endpoints=0;
    for(unsigned i=0;i<n;i+=cfg[i]) {
        CHECK(cfg[i]>=2 && i+cfg[i]<=n);
        if(cfg[i]<2) break;
        if(cfg[i+1]==4) ++interfaces;
        if(cfg[i+1]==5) ++endpoints;
    }
    CHECK(interfaces==3 && endpoints==5);
    CHECK(klass->Init(&hUsbDeviceHS,1)==USBD_OK);
    hUsbDeviceHS.dev_state=USBD_STATE_CONFIGURED;
    CHECK(fifo_words<=1024); CHECK(rx_pointer==nullptr); // IRQ init did not run BOT/SD
    PollReaderUsb(); CHECK(rx_expected==31);
    Setup(0xa1,0xfe,0,2,1); Setup(0x81,10,0,2,1); Setup(0x81,0,0,2,2);
    Setup(0xa1,0xfe,0,3,1); CHECK(control_errors==1);
    Setup(0x21,0x22,0,0,0); CHECK(cdc_setup==1);
    klass->DataIn(&hUsbDeviceHS,1); klass->DataOut(&hUsbDeviceHS,1);
    CHECK(cdc_in==1 && cdc_out==1 && card.reads==0);
    CHECK(reader.Share(true)); Out(0x00);
    CHECK(sent.empty()); PollReaderUsb(); CHECK(sent.back()[12]==1); // unit attention
    klass->DataIn(&hUsbDeviceHS,3); PollReaderUsb();
    card.reset_on_read=true;
    const size_t previous=sent.size(); Out(0x28,512);
    CHECK(card.reads==0);  // interrupt only posted a mailbox event
    PollReaderUsb(); CHECK(card.reads==1 && sent.size()==previous);
    CHECK(reader.State()==diag::ReaderState::Interrupted); // no stale TX after reset
    PollReaderUsb(); CHECK(ReaderUsbIdle()); CHECK(!reader.Ready());
    // Reset + both clears before the next main-loop iteration: do not re-stall.
    Setup(0x21,0xff,0,2,0);
    USBD_LL_ClearStallEP(&hUsbDeviceHS,0x83); Setup(2,1,0,0x83,0);
    USBD_LL_ClearStallEP(&hUsbDeviceHS,3); Setup(2,1,0,3,0);
    PollReaderUsb(); CHECK(!halted[0x83] && !halted[3]); CHECK(ReaderUsbIdle());
    CHECK(reader.Return()); CHECK(!reader.Ready());
    std::printf("composite USB adapter: %u checks, %u failures\n",checks,failures);
    return failures ? 1 : 0;
}
