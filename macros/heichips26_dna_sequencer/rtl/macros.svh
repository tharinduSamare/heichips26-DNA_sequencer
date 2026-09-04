`ifndef MACROS_SVH
`define MACROS_SVH

`define N 8 // Length of S (= # of PEs)
`define M `N // Length of T

`define MATCH 2
`define MISMATCH -1

`define MAX_SCORE (`N * `MATCH)
`define CHA_SEQ_LENGTH (`N * 2)
`define REG_WIDTH ($clog2(`MAX_SCORE + 1) + 1)
`define SYMBOL_BITS 3
`define S_LEN (`N * `SYMBOL_BITS)
`define T_LEN (`M * `SYMBOL_BITS)

parameter signed [2:0] ALPHA = 2; // Gap open penalty
parameter signed [2:0] BETA  = 1; // Gap extension penalty

`define BASE_IDLE  3'b000
`define BASE_CLEAR 3'b001
`define BASE_A     3'b100
`define BASE_C     3'b101
`define BASE_G     3'b110
`define BASE_T     3'b111

`define FIFO_HIGH_ADDR 1'b1
`define FIFO_LOW_ADDR  1'b0

`define RESULT_ADDR 1'b0
`define STATUS_ADDR 1'b1

`define ACCELERATOR_ADDR_MSB 1'b1
`define MEMORY_ADDR_MSB      1'b0

`endif
