/* Compile the pinned core's control-request implementation with interface 2
 * admitted. libDaisy's default is 1 and this revision checks <=, not <.
 * Application object overrides the archive member; no submodule edits or ABI
 * changes. The composite class validates the exact interface and request. */
#include "usbd_core.h"
#undef USBD_MAX_NUM_INTERFACES
#define USBD_MAX_NUM_INTERFACES 2U
#include "../../libDaisy/Middlewares/ST/STM32_USB_Device_Library/Core/Src/usbd_ctlreq.c"
