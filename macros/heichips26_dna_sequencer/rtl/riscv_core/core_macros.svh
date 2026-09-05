`ifndef CORE_MACROS_SVH
`define CORE_MACROS_SVH

typedef enum logic[1:0] { 
    ALU_NONE,
    ALU_AND,
    ALU_OR,
    ALU_ADD
} alu_op_t;

typedef enum logic [3:0] {
    OP_LW,
    OP_SW,
    OP_ADDI,
    OP_ANDI,
    OP_AND,
    OP_OR,
    OP_BEQ,
    OP_JAL,
    OP_UNKNOWN
} operation_t;

`endif