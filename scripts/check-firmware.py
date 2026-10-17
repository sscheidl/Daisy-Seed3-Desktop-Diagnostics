#!/usr/bin/env python3
"""Sanity-check the BOOT_SRAM image's vector table (does not replace a hardware test)."""
import pathlib
import struct
import sys

image = pathlib.Path(sys.argv[1]).read_bytes()
assert 8 <= len(image) <= 480 * 1024, "Image exceeds official BOOT_SRAM linker region"
stack, reset = struct.unpack_from('<II', image)
assert 0x20000000 < stack <= 0x20020000, f"Unexpected DTCM stack: {stack:#x}"
assert reset & 1, "Reset vector must select Thumb mode"
assert 0x24000000 <= (reset & ~1) < 0x24000000 + len(image), "Reset vector outside SRAM image"
print(f"PASS: {len(image)} bytes, stack={stack:#010x}, reset={reset:#010x}, BOOT_SRAM vectors")
