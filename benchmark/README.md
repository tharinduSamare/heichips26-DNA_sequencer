# Benchmarking with PicoRV32 core

## Results

20 test cases were evaluated with simulation.

- **Type 1:** One S_sequence and multiple T_sequences
- **Type 2:** Multiple S_sequences and multiple T_sequences

The reported values are the corresponding number of clock cycles.
Execution time is measured at a 100 MHz clock (`1 cycle = 10 ns`).

| Configuration | Type 1 (cycles) | Type 2 (cycles) | Type 1 Speedup | Type 2 Speedup |
|---|---:|---:|---:|---:|
| **Custom RISC-V Core + Accelerator** | **887** | **1,225** | **219.4×** | **157.8×** |
| PicoRV32 + Accelerator (`-Os`) | 15,262 | 26,002 | **22.7×** | **13.3×** |
| PicoRV32 + SW only (`-Os`) | 346,034 | 346,046 | — | — |
| PicoRV32 + Accelerator (`-O2`) | 14,876 | 26,010 | **18.8×** | **10.7×** |
| PicoRV32 + SW only (`-O2`) | 279,206 | 279,421 | — | — |
| PicoRV32 + Accelerator (`-O3`) | 5,939 | 9,778 | **32.8×** | **19.8×** |
| PicoRV32 + SW only (`-O3`) | 194,570 | 193,342 | — | — |

> **Accelerator Speedup:** PicoRV32 software-only vs. PicoRV32 + accelerator at the same optimization level.
>
> **Custom Core + Accelerator Speedup:** PicoRV32 software-only (`-O3`) vs. custom RISC-V core + accelerator.


## How to benchmark

```
cd benchmark/
make sw     # PicoRV32 + SW only version
make acc    # PicoRV32 + Accelerator version
make custom # custom RISCV core + Accelerator version
```