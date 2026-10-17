# Daisy Seed3 Desktop Dev Kit - hardware diagnostic firmware (BOOT_SRAM).
# Build from this directory: make -j4 ; result: build/DaisyDiagnostic.bin
.DEFAULT_GOAL := all
TARGET = DaisyDiagnostic
DEBUG = 0
OPT = -O2
APP_TYPE = BOOT_SRAM
CPP_STANDARD = -std=gnu++17
PROTOCOL_DIR = ../protocol
CPP_SOURCES = src/main.cpp src/diag_app.cpp src/diag_core.cpp $(PROTOCOL_DIR)/ddp.cpp
C_INCLUDES += -Isrc -I$(PROTOCOL_DIR)
# FatFs sources are needed for the optional read-only microSD test.
USE_FATFS = 1
LIBDAISY_DIR = ../libDaisy
SYSTEM_FILES_DIR = $(LIBDAISY_DIR)/core
# Same bootloader variant as the official Desktop template: DFU over carrier port J7.
# The firmware never installs a bootloader; `make program-boot` is not used here.
BOOT_BIN = $(SYSTEM_FILES_DIR)/dsy_bootloader_v6_4-extdfu-2000ms.bin

include $(SYSTEM_FILES_DIR)/Makefile

$(BUILD_DIR)/$(TARGET).elf: $(LIBDAISY_DIR)/build/libdaisy.a
$(LIBDAISY_DIR)/build/libdaisy.a:
	$(MAKE) -C $(LIBDAISY_DIR)

PYTHON ?= python3
# The microSD test must not be able to change a card. Nothing that can issue an SD
# write, erase or lock command may be linked, at any layer: SDMMC commands
# (CMD24/25, CMD32/33/38, CMD42), HAL, libDaisy BSP/disk driver and the FatFs API.
FORBIDDEN_SYMBOLS = \
	SDMMC_CmdWriteSingleBlock SDMMC_CmdWriteMultiBlock SDMMC_CmdSDEraseStartAdd \
	SDMMC_CmdSDEraseEndAdd SDMMC_CmdEraseStartAdd SDMMC_CmdEraseEndAdd SDMMC_CmdErase \
	SDMMC_CmdLockUnlock \
	HAL_SD_WriteBlocks HAL_SD_WriteBlocks_IT HAL_SD_WriteBlocks_DMA HAL_SD_Erase \
	HAL_SDEx_WriteBlocksDMAMultiBuffer \
	BSP_SD_WriteBlocks BSP_SD_WriteBlocks_DMA BSP_SD_Erase SD_write SD_Driver \
	f_open f_write f_mkfs f_unlink f_rename f_mkdir f_truncate f_sync f_chmod \
	f_utime f_expand f_setlabel f_fdisk f_putc f_puts f_printf f_forward
# Guards against a vacuous check (empty or wrong symbol list).
REQUIRED_SYMBOLS = RoRead RoWrite f_mount f_readdir SDMMC_CmdReadSingleBlock
.PHONY: check
check: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).bin
	$(PYTHON) ../scripts/check-firmware.py $(BUILD_DIR)/$(TARGET).bin
	@arm-none-eabi-nm $(BUILD_DIR)/$(TARGET).elf > $(BUILD_DIR)/symbols.txt
	@for s in $(REQUIRED_SYMBOLS); do \
		if ! grep -q " [A-Za-z] $$s$$" $(BUILD_DIR)/symbols.txt; then \
			echo "FAIL: expected symbol $$s missing, check would be meaningless"; exit 1; fi; \
	done
	@for s in $(FORBIDDEN_SYMBOLS); do \
		if grep -q " [A-Za-z] $$s$$" $(BUILD_DIR)/symbols.txt; then \
			echo "FAIL: SD write/erase path $$s is linked"; exit 1; fi; \
	done
	@echo "PASS: no SD write, erase or lock path linked (SDMMC, HAL, BSP, FatFs)"

# Host tests of the hardware-independent logic: protocol, session, LED modes and the
# complete main loop (diag_app) with fake board and USB.
HOST_CXX ?= g++
HOST_FLAGS ?= -std=c++17 -O2 -Wall -Wextra -Werror
HOST_SOURCES = src/diag_app.cpp src/diag_core.cpp $(PROTOCOL_DIR)/ddp.cpp
.PHONY: test test-sanitize
test:
	mkdir -p build/host
	$(HOST_CXX) $(HOST_FLAGS) -Isrc -I$(PROTOCOL_DIR) ../tests/firmware/test_diag_core.cpp \
		$(HOST_SOURCES) -o build/host/test_diag_core
	./build/host/test_diag_core $(PROTOCOL_DIR)/vectors.txt
	$(HOST_CXX) $(HOST_FLAGS) -Isrc -I$(PROTOCOL_DIR) ../tests/firmware/test_diag_app.cpp \
		$(HOST_SOURCES) -o build/host/test_diag_app
	./build/host/test_diag_app

test-sanitize:
	$(MAKE) test HOST_FLAGS="-std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer"
