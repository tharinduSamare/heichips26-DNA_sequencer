# ============================================================
# PicoRV32 DNA Alignment Accelerator
# ============================================================

CROSS   ?= riscv64-unknown-elf-

CC      := $(CROSS)gcc
OBJCOPY := $(CROSS)objcopy
OBJDUMP := $(CROSS)objdump
SIZE    := $(CROSS)size

TARGET  := dna_alignment

# ============================================================
# Build selection
#
# Usage:
#   make                  -> accelerator version
#   make PROGRAM=acc      -> accelerator version
#   make PROGRAM=sw       -> software-only version
# ============================================================

PROGRAM ?= acc

ifeq ($(PROGRAM),acc)
    MAIN_C      := dna_alignment_acc.c
    MAIN_NAME   := dna_alignment_acc
else ifeq ($(PROGRAM),sw)
    MAIN_C      := dna_alignment_sw.c
    MAIN_NAME   := dna_alignment_sw
else
    $(error Unknown PROGRAM='$(PROGRAM)'. Use PROGRAM=acc or PROGRAM=sw)
endif

MAIN_OBJ := $(MAIN_NAME).o
MAIN_S   := $(MAIN_NAME).s

# ============================================================
# RISC-V configuration
# ============================================================

ARCH := rv32i
ABI  := ilp32

# ============================================================
# Compiler flags
# ============================================================

CFLAGS := \
	-march=$(ARCH) \
	-mabi=$(ABI) \
	-Os \
	-ffreestanding \
	-fno-builtin \
	-nostdlib \
	-nostartfiles \
	-Wall \
	-Wextra

# Debug information is used for source-level disassembly.
# It is NOT used when generating the clean .s file.
DEBUG_CFLAGS := $(CFLAGS) -g

# ============================================================
# Linker flags
# ============================================================

LDFLAGS := \
	-march=$(ARCH) \
	-mabi=$(ABI) \
	-nostdlib \
	-nostartfiles \
	-T linker.ld

# ============================================================
# Source files
# ============================================================

OBJS := $(MAIN_OBJ) start.o

# ============================================================
# Default target
# ============================================================

all: firmware.hex $(MAIN_S) dna_accel.dis dna_accel.lst

	@echo
	@echo "========================================"
	@echo "Build complete"
	@echo "========================================"
	@echo
	@echo "Program : $(PROGRAM)"
	@echo "Source  : $(MAIN_C)"
	@echo "ELF     : dna_accel.elf"
	@echo "BIN     : firmware.bin"
	@echo "HEX     : firmware.hex"
	@echo "ASM     : $(MAIN_S)"
	@echo "DIS     : dna_accel.dis"
	@echo "LST     : dna_accel.lst"
	@echo
	@$(SIZE) dna_accel.elf
	@echo

# ============================================================
# Compile selected C file
#
# -g is enabled here so the ELF contains DWARF source
# information for the source-level disassembly (.lst).
# ============================================================

$(MAIN_OBJ): $(MAIN_C)
	$(CC) $(DEBUG_CFLAGS) -c $< -o $@

# ============================================================
# Generate clean assembly from selected C file
#
# No -g here, so the .s file remains clean and does not
# contain .loc, .cfi, .LFB, .LBB, etc.
# ============================================================

$(MAIN_S): $(MAIN_C)
	$(CC) $(CFLAGS) -S $< -o $@

# ============================================================
# Compile startup assembly
#
# Debug information is included in the object file so that
# source-level disassembly can also identify start.S.
# ============================================================

start.o: start.S
	$(CC) $(DEBUG_CFLAGS) -c $< -o $@

# ============================================================
# Link
# ============================================================

dna_accel.elf: $(OBJS) linker.ld
	$(CC) $(LDFLAGS) $(OBJS) -o $@

# ============================================================
# ELF -> BIN
# ============================================================

firmware.bin: dna_accel.elf
	$(OBJCOPY) -O binary $< $@

# ============================================================
# BIN -> HEX
# ============================================================

firmware.hex: firmware.bin gen_mem_init.py
	python3 gen_mem_init.py

# ============================================================
# Normal disassembly
#
# Shows only the final RISC-V instructions.
# ============================================================

dna_accel.dis: dna_accel.elf
	$(OBJDUMP) -d -M numeric $< > $@

# ============================================================
# Source-level disassembly
#
# Shows:
#   - C source
#   - RISC-V assembly
#   - instruction addresses
#   - machine code
#
# Requires debug information in the ELF.
# ============================================================

dna_accel.lst: dna_accel.elf
	$(OBJDUMP) -S -d -M numeric $< > $@

# ============================================================
# Build disassembly files
# ============================================================

dis: dna_accel.dis dna_accel.lst

# ============================================================
# Build assembly
# ============================================================

asm: $(MAIN_S)

# ============================================================
# Clean
# ============================================================

clean:
	rm -f *.o *.elf *.bin *.hex *.dis *.lst *.s

# ============================================================
# Phony targets
# ============================================================

.PHONY: all clean dis asm