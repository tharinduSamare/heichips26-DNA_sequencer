`include "core_macros.svh"

/*
LW 
    opcode = 0000011 
    funct3 = 010 

SW 
    opcode = 0100011 
    funct3 = 010 

ADDI 
    opcode = 0010011 
    funct3 = 000 

ANDI
    opcode = 0010011 
    funct3 = 111 

AND 
    opcode = 0110011 
    funct3 = 111 
    funct7 = 0000000 

OR 
    opcode = 0110011 
    funct3 = 110 
    funct7 = 0000000 

BEQ 
    opcode = 1100011 
    funct3 = 000 

JAL 
    opcode = 1101111 
*/

module decode_unit #(
    parameter IMM_WIDTH = 32
) (
    input logic [31:0] instr,
    output logic [IMM_WIDTH-1:0]imm,
    output operation_t operation
);

logic [6:0] opcode;
logic [2:0] funct3;
logic [6:0] funct7;

assign opcode = instr[6:0];
assign funct3 = instr[14:12];
assign funct7 = instr[31:25];


// find operation
always_comb begin
    case (opcode)
        7'b0000011: begin
            if (funct3 == 3'b010) begin
                operation = OP_LW;
            end
            else begin
                operation = OP_UNKNOWN;
            end
        end
        7'b0100011: begin
            if (funct3 == 3'b010) begin
                operation = OP_SW;
            end
            else begin
                operation = OP_UNKNOWN;
            end
        end
        7'b0010011: begin // ADDI or ANDI
            if (funct3 == 3'b000) begin
                operation = OP_ADDI;
            end else if (funct3 == 3'b111) begin
                operation = OP_ANDI;
            end else begin
                operation = OP_UNKNOWN;
            end
        end
        7'b0110011: begin // AND or OR
            if (funct3 == 3'b111 && funct7 == 7'b0000000) begin
                operation = OP_AND;
            end else if (funct3 == 3'b110 && funct7 == 7'b0000000) begin
                operation = OP_OR;
            end else begin
                operation = OP_UNKNOWN;
            end
        end
        7'b1100011: begin
            if (funct3 == 3'b000) begin
                operation = OP_BEQ;
            end
            else begin
                operation = OP_UNKNOWN;
            end
        end
        7'b1101111: begin // JAL
            operation = OP_JAL;
        end
        default: begin
            operation = OP_UNKNOWN;
        end
    endcase
end

// immediate
logic [31:0] imm_i_ext, imm_s_ext, imm_b_ext, imm_j_ext;
logic [IMM_WIDTH-1:0] imm_i, imm_s, imm_b, imm_j;

assign imm_i_ext = unsigned'(32'(signed'(instr[31:20])));
assign imm_s_ext = unsigned'(32'(signed'({instr[31:25], instr[11:7]})));
assign imm_b_ext = unsigned'(32'(signed'({instr[31], instr[7], instr[30:25], instr[11:8], 1'b0})));
assign imm_j_ext = unsigned'(32'(signed'({instr[31], instr[19:12], instr[20], instr[30:21], 1'b0})));

assign imm_i = imm_i_ext[IMM_WIDTH-1:0];
assign imm_s = imm_s_ext[IMM_WIDTH-1:0];
assign imm_b = imm_b_ext[IMM_WIDTH-1:0];
assign imm_j = imm_j_ext[IMM_WIDTH-1:0];


always_comb begin
    imm = '0;

    case(operation)
        OP_LW, OP_ADDI, OP_ANDI: begin
            imm = imm_i;
        end
        OP_SW: begin
            imm = imm_s;
        end
        OP_BEQ: begin
            imm = imm_b;
        end
        OP_JAL: begin
            imm = imm_j;
        end
        default: begin
            imm = '0;
        end
    endcase
end


endmodule