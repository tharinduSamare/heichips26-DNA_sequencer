`include "core_macros.svh"

module alu #(
    parameter DATA_WIDTH = 32
)(
    input logic [DATA_WIDTH-1:0]a,
    input logic [DATA_WIDTH-1:0]b,
    input alu_op_t alu_op,
    output logic [DATA_WIDTH-1:0]y,
    output logic alu_eqz
);

always_comb begin
    case (alu_op)
        ALU_NONE: begin
            y = '0;
        end

        ALU_AND: begin
            y = a & b;
        end

        ALU_OR: begin
            y = a | b;
        end

        ALU_ADD: begin
            y = a + b;
        end

        default: begin
            y = '0;
        end
    endcase
end

assign alu_eqz = (a == '0)? 1'b1:1'b0;

endmodule
