# Heichips 2026 Hackathon - DNA Sequence Aligner

This is a hardware-accelerator for DNA sequence alignment based on the Smith-Waterman algorithm

:metal: The original README.md file is [here](./README_original.md)

## Architecture

![DNA_SEQUENCE_ALIGN_SOC](/images/DNA_Sequence_Align_SOC_block_diagram.png)

The design is divided into two parts.
1. DNA alignment accelerator : Implemented in the *ASIC* ([accelerator.sv](macros/heichips26_dna_sequencer/rtl/accelerator/accelerator.sv))
2. RISC-V core               : Implemented in the *eFPGA* ([fpga_top.sv](macros/heichips26_dna_sequencer/rtl/riscv_core/fpga_top.sv))

- (Optional) UART-controller : Implemented in the *eFPGA* ([fpga_top_module.sv](macros/heichips26_dna_sequencer/rtl/uart_controller/fpga_top_module.sv))
  - This is designed to directly drive the accelerator using a PC via UART instead of connecting to the RISC-V core.

### **DNA Alignment Accelerator**
  - Performs the Smith-Waterman algorithm in hardware.
  - This is capable of running at 130MHz with ihp-sg13cmos5l PDK.
  - Computes the dynamic programming matrix in parallel using a  systolic array.
  - Supports 8-character long DNA sequences.
  - Fully pipelined and capable of receiving a new test sequence while  previous sequence is still being processed.

#### ASIC Implementation

| Metric | Result |
|---|---:|
| 🎯 Target Frequency | **100 MHz** |
| 📐 Die Area | 100,000 µm² (500 × 200 µm) |
| ▫️ Core Area | 93,350.9 µm² |
| 📊 Cell Utilization | 83.53% |
| 🔲 Standard Cells | 4,777 |
| 🧩 Total Cell Instances | 7,436 |
| ⚡ Total Power | 7.14 mW |
| ⏱️ Setup WNS | 3.82 ns |
| ⏱️ Setup TNS | 0 ns |
| 🔒 Hold WNS | 0 ns |
| 🔒 Hold TNS | 0 ns |
| ✅ Setup Violations | 0 |
| ✅ Hold Violations | 0 |
| 🛠️ Routing DRC Errors | 0 |
| 🔍 LVS Errors | 0 |


  ![ASIC_implementation](macros/heichips26_dna_sequencer/final/render/heichips26_dna_sequencer.png)

### **RISC-V (Task Specialized) Processor**
  - A tiny RV32I task specific core runs at 15MHz implemented in the eFPGA.
  - 6-stage multi-cycle core.
  - Supports a subset of RV32I instructions.
    - LW, SW, ADDI, ANDI, AND, OR, BEQ, JAL
  - Drives the accelerator.
  - Feeds sequences from the on-chip memory to the accelerator
  - Stores the alignment results back into memory

### eFPGA Resource Utilization

- The eFPGA contains:
  1. A tiny RV32I core
  2. A memory controller to route traffic to / from on-chip memory and accelerator.

| Resource | Used | Available | Utilisation |
|---|---:|---:|---:|
| FABULOUS_LC | 246 | 288 | 85% |
| IOBUF | 20 | 32 | 62% |
| TT_PROJECT | 0 | 11 | 0% |
| TT_PROJECT_LARGE | 0 | 2 | 0% |
| TT_PROJECT_MUX | 0 | 1 | 0% |
| IHP_SRAM_1024x32_1RW | 1 | 1 | 100% |
| GBUF | 1 | 4 | 25% |
| SYS_RESET | 0 | 1 | 0% |

## How It Works

1. The RISC-V processor (in eFPGA) loads the encoded DNA sequences from the on-chip memory.
2. The sequences are written to the accelerator through its MMIO interface.
3. The systolic array performs the alignment computation.
4. The processor polls the accelerator status until the result is ready.
5. The alignment score is read from the accelerator.
6. The result is stored back into on-chip memory.

## Testing

- **SystemVerilog testbench**: [heichips26_dna_sequencer_tb.sv](macros/heichips26_dna_sequencer/testbenches/verilog/heichips26_dna_sequencer_tb.sv)
- **Cocotb testbench**: [heichips26_dna_sequencer_tb.py](macros/heichips26_dna_sequencer/testbenches/cocotb/heichips26_dna_sequencer_tb.py)

```
nix-shell
export PDK_ROOT=$(pwd)/IHP-Open-PDK && export PDK=ihp-sg13cmos5l
cd macros/heichips26_dna_sequencer/
cd scripts/
python3 ./data_gen_and_validation.py --type 2 --N 20
cd ..
make sim-rtl-verilog CELL=heichips26_dna_sequencer
make sim-rtl-cocotb CELL=heichips26_dna_sequencer
make sim-gl-cocotb CELL=heichips26_dna_sequencer
```

## Hardware Requirements

- We would like to have an UART interface in the SOC to connect the accelerator directly to a PC (skipping the RISC-V processor in the eFPGA).

## Benchmarking

20 test cases were evaluated with simulation.

- **Type 1:** One S_sequence and multiple T_sequences
- **Type 2:** Multiple S_sequences and multiple T_sequences

The reported values are the corresponding number of clock cycles.
Execution time is measured at a 100 MHz clock (`1 cycle = 10 ns`).

| Configuration | Type 1 (cycles) | Type 2 (cycles) | Type 1 Speedup | Type 2 Speedup |
|---|---:|---:|---:|---:|
| **Custom RISC-V Core + Accelerator** | **887** | **1,225** | **219.4×** | **157.8×** |
| PicoRV32 + Accelerator (`custom assembly`) | 1,765 | 2,269 | **110.2×** | **85.2×** |
| PicoRV32 + Accelerator (`-Os`) | 15,262 | 26,002 | **22.7×** | **13.3×** |
| PicoRV32 + SW only (`-Os`) | 346,034 | 346,046 | — | — |
| PicoRV32 + Accelerator (`-O2`) | 14,876 | 26,010 | **18.8×** | **10.7×** |
| PicoRV32 + SW only (`-O2`) | 279,206 | 279,421 | — | — |
| PicoRV32 + Accelerator (`-O3`) | 5,939 | 9,778 | **32.8×** | **19.8×** |
| PicoRV32 + SW only (`-O3`) | 194,570 | 193,342 | — | — |

> **Accelerator Speedup:** PicoRV32 software-only vs. PicoRV32 + accelerator at the same optimization level.
>
> **Custom Core + Accelerator Speedup:** PicoRV32 software-only (`-O3`) vs. custom RISC-V core + accelerator.

- Benchmarking sources can be found [here](./benchmark/)

## License

The code in this repository is licensed under Apache 2.0 WITH SHL-2.1 if not otherwise stated.
