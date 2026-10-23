// Exercise reader commands through the real DDP/application stack, including
// ownership gating for commands arriving in one receive batch.
#include "diag_app.h"
#include <cstdio>
#include <cstring>
#include <string>
class Board : public diag::Board {
  public:
    bool local = true;
    unsigned tests = 0;
    diag::Inputs ReadInputs() override { diag::Inputs i; i.sd_card = true; return i; }
    uint32_t ControlTicks() override { return 0; }
    void ApplyLeds(uint16_t, uint8_t) override {}
    diag::SdResult RunSdTest(bool) override { ++tests; return {}; }
    bool SdTestAllowed() override { return local; }
    void ReaderCommand(uint32_t request, ddp::Writer& out) override {
        if(request & diag::kRequestReaderShare) local = false;
        if(request & diag::kRequestReaderReturn) local = true;
        out.Str(local ? "READER state=LOCAL sectors=0 busy=0" : "READER state=SHARED sectors=8 busy=0");
    }
};
class Usb : public diag::UsbSink {
  public:
    std::string data;
    diag::SendResult Send(const uint8_t* p, size_t n) override {
        data.append(reinterpret_cast<const char*>(p), n); return diag::SendResult::Ok;
    }
};
void Send(diag::App& app, const char* body) {
    char frame[ddp::kMaxFrame];
    size_t n = ddp::BuildFrame(body, std::strlen(body), frame, sizeof(frame));
    app.OnUsbReceive(reinterpret_cast<const uint8_t*>(frame), uint32_t(n));
}
int main() {
    Board board; Usb usb; diag::App app(board, usb, "v6_1", 0);
    Send(app, "READER a=SHARE"); app.Step(1);
    if(!board.local || usb.data.find("e=SESSION") == std::string::npos) return 1;
    Send(app, "HELLO proto=1"); app.Step(2);
    if(usb.data.find(",sdmsc") == std::string::npos) return 2;
    Send(app, "SDTEST"); Send(app, "READER a=SHARE"); app.Step(3);
    if(board.tests != 0 || board.local || usb.data.find("ERR c=SDTEST e=BUSY") == std::string::npos) return 3;
    Send(app, "BYE"); app.Step(4); app.Step(4000);
    if(board.local) return 4;  // timeout/BYE never gives the card back
    Send(app, "HELLO proto=1"); Send(app, "READER a=RETURN"); app.Step(4001);
    Send(app, "SDTEST"); app.Step(4002);
    if(board.tests != 1) return 5;
    Send(app, "READER a=INVALID"); app.Step(4003);
    if(usb.data.find("ERR c=READER e=ARG") == std::string::npos) return 6;
    std::puts("reader application: passed"); return 0;
}
