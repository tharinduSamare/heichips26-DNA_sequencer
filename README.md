# Heichips 2026 Hackathon - DNA Sequence Aligner

This is a hardware-accelerator for DNA sequence alignment based on the Smith-Waterman algorithm

:metal:: The original README.md file is [here](./README_original.md)

## Architecture

- The design is divided into two parts.
  - DNA alignment accelerator : Implemented in the *ASIC* (This repository)
  - RISC-V core : Implemented in the *eFPGA* (Can be found [here](https://github.com/tharinduSamare/DNA_alignment_with_Smith_Waterman_Algorithm))

- **DNA alignment accelerator**
  - Performs the Smith-Waterman algorithm in hardware
  - This is capable of running at 130MHz with ihp-sg13cmos5l PDK
  - Computes the dynamic programming matrix in parallel using a  systolic array
  - Supports 8-character long DNA sequences.
  - Fully pipelined and capable of receiving a new test sequence while  previous sequence is still being processed.

- **RISC-V (task specialized) processor**
  - A tiny RV32I task specific core runs at 15MHz on the eFPGA.
  - 6-stage multi-cycle core.
  - Supports a subset of RV32I instructions.
    - LW, SW, ADDI, ANDI, AND, OR, BEQ, JAL
  - Drives the accelerator.
  - Feeds sequences from the on-chip memory to the accelerator
  - Stores the alignment results back into memory

## How It Works

1. The RISC-V processor (in eFPGA) loads the encoded DNA sequences from the on-chip memory.
2. The sequences are written to the accelerator through its MMIO interface.
3. The systolic array performs the alignment computation.
4. The processor polls the accelerator status until the result is ready.
5. The alignment score is read from the accelerator.
6. The result is stored back into on-chip memory.

## Testing

- **SystemVerilog testbench**: [accelerator_tb.sv](macros/heichips26_dna_sequencer/testbenches/verilog/accelerator_tb.sv)
- **Cocotb testbench**: [heichips26_dna_sequencer_tb.py](macros/heichips26_dna_sequencer/testbenches/cocotb/heichips26_dna_sequencer_tb.py)

## Hardware Requirements

- We like to have an UART interface to connect the accelerator directly to a PC (skipping the RISC-V processor in the eFPGA).


## License

The code in this repository is licensed under Apache 2.0 WITH SHL-2.1 if not otherwise stated.
