#pragma once
#include "card_reader.h"

// Only the writable firmware links this transport. CDC stays on interfaces 0/1;
// removable MSC is interface 2, bulk endpoints 0x03/0x83 (FS, 64 bytes).
bool InitReaderUsb(diag::CardReader& reader);
void PollReaderUsb();
bool ReaderUsbIdle();
bool ReaderUsbInterrupted();
