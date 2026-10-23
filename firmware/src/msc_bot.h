// USB MSC Bulk-Only Transport. No HAL dependency; called only by the main loop.
#pragma once
#include "card_reader.h"
#include <cstddef>

namespace diag {
class MscPort {
  public:
    virtual void Send(const uint8_t* data, uint16_t size) = 0;
    virtual void Receive(uint16_t size) = 0;
    virtual void Halt(bool in) = 0;
    virtual ~MscPort() = default;
};

class MscBot {
  public:
    MscBot(CardReader& reader, MscPort& port) : reader_(reader), port_(port) {}
    void Configure();
    void Disconnect();
    void Reset();  // BOT reset recovery also requires clearing BOTH endpoint halts
    void ClearHalt(bool in);
    void Out(const uint8_t* data, size_t size);
    void InComplete();
    bool Idle() const { return stage_ == Stage::Command; }

  private:
    enum class Stage { Command, DataIn, Read, Write, Status, HaltIn, Recovery };
    void Command(const uint8_t* cbw);
    void Reply(uint16_t size);
    void Status(uint8_t status = 0);
    void Fail(uint8_t key, uint8_t asc);
    void Invalid();
    bool Transfer(bool in, uint32_t bytes);
    bool Ready();
    bool Range(uint32_t lba, uint32_t count);
    void ReadNext();
    CardReader& reader_;
    MscPort& port_;
    Stage stage_ = Stage::Recovery;
    uint8_t data_[512] = {};  // USB transport copies to its dedicated TX buffer
    uint8_t tag_[4] = {};
    uint32_t residue_ = 0;
    uint32_t lba_ = 0;
    uint32_t remaining_ = 0;
    uint32_t media_version_ = 0;
    uint8_t sense_key_ = 0;
    uint8_t sense_asc_ = 0;
    bool in_ = false;
    bool reset_seen_ = false;
    bool clear_in_ = false;
    bool clear_out_ = false;
    uint8_t pending_status_ = 0;
    bool phase_error_ = false;
};
} // namespace diag
