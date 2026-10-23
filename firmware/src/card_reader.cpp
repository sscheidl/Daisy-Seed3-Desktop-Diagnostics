#include "card_reader.h"

namespace diag {
const char* ReaderStateName(ReaderState state) {
    switch(state) {
        case ReaderState::Local: return "LOCAL";
        case ReaderState::Starting: return "STARTING";
        case ReaderState::Shared: return "SHARED";
        case ReaderState::Ejected: return "EJECTED";
        case ReaderState::Interrupted: return "INTERRUPTED";
        case ReaderState::Error: return "ERROR";
    }
    return "ERROR";
}
bool CardReader::Share(bool present) {
    if(!Local() || !present)
        return false;
    state_ = ReaderState::Starting;
    prevent_ = false;
    if(!card_.Open(sectors_) || sectors_ == 0)
        return Failed();
    state_ = ReaderState::Shared;
    ++media_version_;
    return true;
}
bool CardReader::Failed() {
    state_ = ReaderState::Error;
    return false;
}
bool CardReader::Return() {
    if(state_ != ReaderState::Ejected && state_ != ReaderState::Interrupted
       && state_ != ReaderState::Error)
        return false;
    card_.Close();
    state_ = ReaderState::Local;
    sectors_ = 0;
    prevent_ = false;
    return true;
}
bool CardReader::Eject() {
    if(!Ready() || prevent_ || !Sync())
        return false;
    state_ = ReaderState::Ejected;
    return true;
}
void CardReader::Interrupt() {
    // Never claim a clean eject after transport loss or a reset recovery.
    if(state_ == ReaderState::Shared || state_ == ReaderState::Starting)
        state_ = ReaderState::Interrupted;
    prevent_ = false;
}
void CardReader::Observe(bool present) {
    if(!present)
        Interrupt();
}
bool CardReader::Read(uint32_t lba, uint8_t* block) {
    if(!Ready() || lba >= sectors_)
        return false;
    return card_.Read(lba, block) || Failed();
}
bool CardReader::Write(uint32_t lba, const uint8_t* block) {
    if(!Ready() || lba >= sectors_)
        return false;
    return card_.Write(lba, block) || Failed();
}
bool CardReader::Sync() {
    return Ready() && (card_.Sync() || Failed());
}
} // namespace diag
