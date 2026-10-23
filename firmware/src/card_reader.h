// Main-loop-only SD ownership. USB transport events are delivered by its mailbox.
#pragma once
#include <cstdint>

namespace diag {
enum class ReaderState : uint8_t { Local, Starting, Shared, Ejected, Interrupted, Error };
const char* ReaderStateName(ReaderState state);

class CardDevice {
  public:
    virtual bool Open(uint32_t& sectors) = 0;
    virtual bool Read(uint32_t lba, uint8_t* block) = 0;
    // Success means programming has completed, not merely DMA completion.
    virtual bool Write(uint32_t lba, const uint8_t* block) = 0;
    virtual bool Sync() = 0;
    virtual void Close() = 0;
    virtual ~CardDevice() = default;
};

class CardReader {
  public:
    explicit CardReader(CardDevice& card) : card_(card) {}
    bool Share(bool present);
    bool Return();  // only after host eject or explicit interruption acknowledgement
    bool Eject();
    void Interrupt();
    void Observe(bool present);
    bool Read(uint32_t lba, uint8_t* block);
    bool Write(uint32_t lba, const uint8_t* block);
    bool Sync();
    bool Ready() const { return state_ == ReaderState::Shared; }
    bool Local() const { return state_ == ReaderState::Local; }
    uint32_t Sectors() const { return sectors_; }
    uint32_t MediaVersion() const { return media_version_; }
    ReaderState State() const { return state_; }
    bool PreventRemoval() const { return prevent_; }
    void PreventRemoval(bool prevent) { prevent_ = prevent; }

  private:
    bool Failed();
    CardDevice& card_;
    ReaderState state_ = ReaderState::Local;
    uint32_t sectors_ = 0;
    uint32_t media_version_ = 0;
    bool prevent_ = false;
};
} // namespace diag
