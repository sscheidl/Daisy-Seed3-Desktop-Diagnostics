#include "msc_bot.h"
#include <algorithm>
#include <cstring>

namespace diag {
namespace {
uint32_t Le32(const uint8_t* p) {
    return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
}
uint32_t Be32(const uint8_t* p) {
    return uint32_t(p[0]) << 24 | uint32_t(p[1]) << 16 | uint32_t(p[2]) << 8 | p[3];
}
uint16_t Be16(const uint8_t* p) { return uint16_t(uint16_t(p[0]) << 8 | p[1]); }
void PutBe32(uint8_t* p, uint32_t n) {
    for(int i = 3; i >= 0; --i) { p[i] = uint8_t(n); n >>= 8; }
}
void PutLe32(uint8_t* p, uint32_t n) {
    for(unsigned i = 0; i < 4; ++i) { p[i] = uint8_t(n); n >>= 8; }
}
}
void MscBot::Configure() {
    stage_ = Stage::Command;
    phase_error_ = false;
    sense_key_ = sense_asc_ = 0;
    port_.Receive(31);
}
void MscBot::Disconnect() {
    reader_.Interrupt();
    stage_ = Stage::Recovery;
    reset_seen_ = clear_in_ = clear_out_ = false;
}
void MscBot::Invalid() {
    Disconnect();
    port_.Halt(true);
    port_.Halt(false);
}
void MscBot::Reset() {
    Invalid();
    reset_seen_ = true;
}
void MscBot::ClearHalt(bool in) {
    if(stage_ == Stage::Recovery) {
        if(!reset_seen_) { port_.Halt(in); return; }
        (in ? clear_in_ : clear_out_) = true;
        if(clear_in_ && clear_out_)
            Configure();
    } else if(in && stage_ == Stage::HaltIn) {
        Status(pending_status_);
    }
}
void MscBot::Status(uint8_t status) {
    if(status == 2) { phase_error_ = true; reader_.Interrupt(); }
    if(residue_ && in_ && stage_ != Stage::HaltIn) {
        pending_status_ = status;
        stage_ = Stage::HaltIn;
        port_.Halt(true);
        return;
    }
    if(residue_ && !in_) port_.Halt(false);
    std::memset(data_, 0, 13);
    PutLe32(data_, 0x53425355);
    std::memcpy(data_ + 4, tag_, 4);
    PutLe32(data_ + 8, residue_);
    data_[12] = status;
    stage_ = Stage::Status;
    port_.Send(data_, 13);
}
void MscBot::Fail(uint8_t key, uint8_t asc) {
    sense_key_ = key;
    sense_asc_ = asc;
    Status(1);
}
bool MscBot::Transfer(bool in, uint32_t bytes) {
    // BOT 1.0 section 6.7: (2,3,7,8,10,13) phase error; (4,9) may
    // fail the no-data command; (5,11) process device length and stall surplus.
    // Never partially execute a write when the host offers too few bytes.
    if(bytes && (!residue_ || in_ != in || residue_ < bytes)) {
        Status(2);
        return false;
    }
    if(!bytes && residue_) { Fail(5, 0x24); return false; }
    return true;
}
bool MscBot::Ready() {
    if(reader_.Ready())
        return true;
    Fail(2, 0x3a);  // NOT READY / MEDIUM NOT PRESENT
    return false;
}
bool MscBot::Range(uint32_t lba, uint32_t count) {
    if(lba > reader_.Sectors() || count > reader_.Sectors() - lba) {
        Fail(5, 0x21);
        return false;
    }
    return true;
}
void MscBot::Reply(uint16_t size) {
    if(!Transfer(true, size)) return;
    const uint16_t send = size;
    if(!send) { Status(); return; }
    residue_ -= send;
    stage_ = Stage::DataIn;
    port_.Send(data_, send);
}
void MscBot::ReadNext() {
    if(!remaining_) { Status(); return; }
    if(!reader_.Read(lba_, data_)) { Fail(3, 0x11); return; }
    ++lba_;
    --remaining_;
    residue_ -= 512;
    stage_ = Stage::Read;
    port_.Send(data_, 512);
}
void MscBot::Out(const uint8_t* data, size_t size) {
    if(stage_ == Stage::Write) {
        if(size != 512) { Invalid(); return; }
        if(!reader_.Write(lba_, data)) { Fail(3, 0x0c); return; }
        ++lba_;
        --remaining_;
        residue_ -= 512;
        if(remaining_) port_.Receive(512);
        else Status();  // CardDevice::Write waited for programming completion
        return;
    }
    if(stage_ != Stage::Command || size != 31 || Le32(data) != 0x43425355
       || data[13] != 0 || data[14] == 0 || data[14] > 16 || (data[12] & 0x7f)) {
        Invalid();
        return;
    }
    std::memcpy(tag_, data + 4, 4);
    residue_ = Le32(data + 8);
    in_ = (data[12] & 0x80) != 0;
    const uint8_t group = data[15] >> 5;
    const uint8_t required = group == 0 ? 6 : (group == 4 ? 16 : (group == 5 ? 12 : 10));
    if(data[14] < required) { Fail(5, 0x24); return; }
    Command(data + 15);
}
void MscBot::InComplete() {
    if(stage_ == Stage::Status) {
        if(phase_error_) { stage_ = Stage::Recovery; reset_seen_ = clear_in_ = clear_out_ = false; }
        else { stage_ = Stage::Command; port_.Receive(31); }
    }
    else if(stage_ == Stage::DataIn) Status();
    else if(stage_ == Stage::Read) ReadNext();
}
void MscBot::Command(const uint8_t* c) {
    std::memset(data_, 0, sizeof(data_));
    if(reader_.Ready() && media_version_ != reader_.MediaVersion()
       && c[0] != 0x12 && c[0] != 0x03) {
        media_version_ = reader_.MediaVersion();
        Fail(6, 0x28);  // UNIT ATTENTION: medium changed, discard host media caches
        return;
    }
    switch(c[0]) {
        case 0x12: {  // INQUIRY, standard and supported VPD pages
            if(c[1] & 1) {
                if(c[2] == 0) { data_[1] = 0; data_[3] = 1; data_[4] = 0; Reply(std::min<uint16_t>(5, c[4])); }
                else Fail(5, 0x24);
            } else if(c[2]) Fail(5, 0x24);
            else {
                data_[1] = 0x80; data_[2] = 4; data_[3] = 2; data_[4] = 31;
                std::memcpy(data_ + 8, "DAISY   SD CARD READER  0200", 28);
                Reply(std::min<uint16_t>(36, c[4]));
            }
            break;
        }
        case 0x03:  // REQUEST SENSE, fixed format
            data_[0] = 0x70; data_[2] = sense_key_; data_[7] = 10; data_[12] = sense_asc_;
            Reply(std::min<uint16_t>(18, c[4])); sense_key_ = sense_asc_ = 0;
            break;
        case 0x00:  // TEST UNIT READY
            if(Transfer(false, 0) && Ready()) Status();
            break;
        case 0x25:  // READ CAPACITY (10)
            if(Transfer(true, 8) && Ready()) {
                PutBe32(data_, reader_.Sectors() - 1); PutBe32(data_ + 4, 512); Reply(8);
            }
            break;
        case 0x23:  // READ FORMAT CAPACITIES
            if(!Ready()) break;
            data_[3] = 8; PutBe32(data_ + 4, reader_.Sectors());
            data_[8] = 2; data_[10] = 2;
            Reply(std::min<uint16_t>(12, Be16(c + 7)));
            break;
        case 0xa0:  // REPORT LUNS: exactly one logical unit, LUN 0
            if(c[2] != 0 && c[2] != 2) { Fail(5, 0x24); break; }
            data_[3] = 8;
            Reply(uint16_t(std::min<uint32_t>(16, Be32(c + 6))));
            break;
        case 0x1a:  // MODE SENSE (6), caching page says write-through (WCE=0)
        case 0x5a: {
            const bool ten = c[0] == 0x5a;
            if((c[2] & 0x3f) != 0x3f && (c[2] & 0x3f) != 8 && (c[2] & 0x3f) != 0) {
                Fail(5, 0x24); break;
            }
            const uint16_t header = ten ? 8 : 4;
            const uint16_t n = header + ((c[2] & 0x3f) ? 20 : 0);
            data_[ten ? 1 : 0] = uint8_t(n - (ten ? 2 : 1));
            if(n > header) { data_[header] = 8; data_[header + 1] = 18; }
            Reply(std::min<uint16_t>(n, ten ? Be16(c + 7) : c[4]));
            break;
        }
        case 0x28:  // READ (10)
        case 0x2a: {  // WRITE (10), FUA honoured by write-through completion
            lba_ = Be32(c + 2); remaining_ = Be16(c + 7);
            if(!Transfer(c[0] == 0x28, remaining_ * 512) || !Ready() || !Range(lba_, remaining_)) break;
            if(!remaining_) Status();
            else if(c[0] == 0x28) ReadNext();
            else { stage_ = Stage::Write; port_.Receive(512); }
            break;
        }
        case 0x35:  // SYNCHRONIZE CACHE (10), including IMMED: completed before CSW
            if(Transfer(false, 0) && Ready()) {
                if(reader_.Sync()) Status(); else Fail(3, 0x0c);
            }
            break;
        case 0x1e:  // PREVENT/ALLOW MEDIUM REMOVAL
            if(!Transfer(false, 0)) break;
            if(c[4] > 1) Fail(5, 0x24);
            else { reader_.PreventRemoval(c[4] != 0); Status(); }
            break;
        case 0x1b:  // START STOP UNIT: never auto-share on START
            if(!Transfer(false, 0)) break;
            if((c[4] & 3) == 2) {
                if(reader_.PreventRemoval()) Fail(5, 0x53);
                else if(reader_.Eject()) Status();
                else Fail(2, 0x3a);
            } else if(Ready()) Status();
            break;
        // VERIFY, FORMAT, UNMAP and unimplemented commands fail explicitly:
        // range checking alone is not successful media verification.
        default: Fail(5, 0x20); break;
    }
}
} // namespace diag
