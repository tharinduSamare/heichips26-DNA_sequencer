VERILATOR := verilator

BUILD_DIR := build

HW_DIR  := hardware
TB_DIR  := tb
RTL_DIR := ../macros/heichips26_dna_sequencer/rtl

# Include directory for macros.svh
INCLUDE_DIRS := -I$(RTL_DIR)

ACC_RTL_DIR  := $(RTL_DIR)/accelerator
CORE_RTL_DIR := $(RTL_DIR)/riscv_core


# --------------------------------------------------------------------
# Common PicoRV32 RTL
# --------------------------------------------------------------------

COMMON_SRC := \
	$(HW_DIR)/picorv32.v \
	$(HW_DIR)/pico32_memory.sv \
	$(HW_DIR)/riscv_top_module.sv


# --------------------------------------------------------------------
# PicoRV32 + accelerator benchmark
# --------------------------------------------------------------------

ACC_SRC := \
	$(COMMON_SRC) \
	$(HW_DIR)/pico32_fpga_top.sv \
	$(HW_DIR)/pico32_top_module.sv \
	$(wildcard $(ACC_RTL_DIR)/*.sv) \
	$(wildcard $(CORE_RTL_DIR)/*.sv)


# --------------------------------------------------------------------
# PicoRV32 + pure software benchmark
# --------------------------------------------------------------------

SW_SRC := \
	$(COMMON_SRC) \
	$(HW_DIR)/picosoc_pure_sw.sv


# --------------------------------------------------------------------
# Custom RISC-V core + accelerator benchmark
# --------------------------------------------------------------------

CUSTOM_SRC := \
	$(COMMON_SRC) \
	$(wildcard $(ACC_RTL_DIR)/*.sv) \
	$(wildcard $(CORE_RTL_DIR)/*.sv)


# --------------------------------------------------------------------
# Testbenches
# --------------------------------------------------------------------

ACC_TB := $(TB_DIR)/picorv32_dna_alignment_acc_tb.sv
ASM_TB := $(TB_DIR)/picorv32_dna_alignment_acc_asm_tb.sv
SW_TB  := $(TB_DIR)/picorv32_dna_alignment_pure_sw_tb.sv
CUSTOM_TB := $(TB_DIR)/riscv_top_module_tb.sv


# --------------------------------------------------------------------
# Targets
# --------------------------------------------------------------------

.PHONY: all acc picorv32_asm sw custom \
        firmware-acc firmware-asm firmware-sw firmware-custom \
        lint clean


all: acc picorv32_asm sw custom


# --------------------------------------------------------------------
# Firmware targets
# --------------------------------------------------------------------

firmware-acc:
	$(MAKE) -C firmware PROGRAM=acc

firmware-asm:
	$(MAKE) -C firmware PROGRAM=picorv32_asm

firmware-sw:
	$(MAKE) -C firmware PROGRAM=sw

firmware-custom:
	$(MAKE) -C firmware PROGRAM=custom


# --------------------------------------------------------------------
# PicoRV32 + accelerator benchmark
# --------------------------------------------------------------------

acc: firmware-acc
	mkdir -p $(BUILD_DIR)/acc
	$(VERILATOR) \
		--binary \
		--timing \
		--relative-includes \
		-Wno-fatal \
		--top-module picorv32_acc_tb \
		-Mdir $(BUILD_DIR)/acc \
		$(INCLUDE_DIRS) \
		-DACC_FIRMWARE \
		$(ACC_SRC) \
		$(ACC_TB)

	$(BUILD_DIR)/acc/Vpicorv32_acc_tb


# --------------------------------------------------------------------
# PicoRV32 + accelerator + generated assembly benchmark
# --------------------------------------------------------------------

picorv32_asm: firmware-asm
	mkdir -p $(BUILD_DIR)/asm
	$(VERILATOR) \
		--binary \
		--timing \
		--relative-includes \
		-Wno-fatal \
		--top-module picorv32_acc_asm_tb \
		-Mdir $(BUILD_DIR)/asm \
		$(INCLUDE_DIRS) \
		-DASM_FIRMWARE \
		$(ACC_SRC) \
		$(ASM_TB)

	$(BUILD_DIR)/asm/Vpicorv32_acc_asm_tb


# --------------------------------------------------------------------
# PicoRV32 + pure software benchmark
# --------------------------------------------------------------------

sw: firmware-sw
	mkdir -p $(BUILD_DIR)/sw
	$(VERILATOR) \
		--binary \
		--timing \
		--relative-includes \
		-Wno-fatal \
		--top-module picorv32_sw_tb \
		-Mdir $(BUILD_DIR)/sw \
		$(INCLUDE_DIRS) \
		$(SW_SRC) \
		$(SW_TB)

	$(BUILD_DIR)/sw/Vpicorv32_sw_tb


# --------------------------------------------------------------------
# Custom RISC-V core + accelerator benchmark
# --------------------------------------------------------------------

custom: firmware-custom
	mkdir -p $(BUILD_DIR)/custom
	$(VERILATOR) \
		--binary \
		--timing \
		--relative-includes \
		-Wno-fatal \
		--top-module riscv_top_module_tb \
		-Mdir $(BUILD_DIR)/custom \
		$(INCLUDE_DIRS) \
		$(CUSTOM_SRC) \
		$(CUSTOM_TB)

	$(BUILD_DIR)/custom/Vriscv_top_module_tb


# --------------------------------------------------------------------
# Lint
# --------------------------------------------------------------------

lint:
	mkdir -p $(BUILD_DIR)/lint
	$(VERILATOR) \
		--lint-only \
		--timing \
		--relative-includes \
		-Wno-fatal \
		--top-module picorv32_acc_tb \
		$(INCLUDE_DIRS) \
		-DACC_FIRMWARE \
		$(ACC_SRC) \
		$(ACC_TB)


# --------------------------------------------------------------------
# Clean
# --------------------------------------------------------------------

clean:
	rm -rf $(BUILD_DIR)
	$(MAKE) -C firmware clean