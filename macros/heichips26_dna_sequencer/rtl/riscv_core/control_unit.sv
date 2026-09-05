`include "core_macros.svh"

module control_unit(
    input clk, rstn,
    input operation_t operation,

    output alu_op_t alu_op,
    output logic alu_src_imm,
    output logic reg_write,
    output logic dmem_read,
    output logic imem_read,
    output logic dmem_write,
    output logic branch,
    output logic jump,
    output logic mem_to_regFile,
    output logic load_instr,
    output logic pc_inc,
    output logic execute
);

typedef enum logic [2:0]{
    FETCH_STATE,
    FETCH_WAIT_STATE,
    EXECUTE_STATE,
    MEMORY_WRITE_STATE,
    MEMORY_READ_STATE,
    // MEMORY_READ_WAIT_STATE,
    WRITEBACK_STATE
}state_t;

state_t state;

always_ff @(posedge clk) begin
    if(!rstn) begin
        state <= FETCH_STATE;
    end
    else begin
        case (state)
            FETCH_STATE: begin
                state <= FETCH_WAIT_STATE;
            end

            FETCH_WAIT_STATE: begin
                state <= EXECUTE_STATE;
            end

            EXECUTE_STATE: begin
                case(operation)
                    OP_ADDI, OP_ANDI, OP_AND, OP_OR: begin
                        state <= WRITEBACK_STATE;
                    end

                    OP_LW: begin
                        state <= MEMORY_READ_STATE;
                    end

                    OP_SW: begin
                        state <= MEMORY_WRITE_STATE;
                    end

                    OP_BEQ, OP_JAL: begin
                        state <= FETCH_STATE;
                    end
                    default: begin // for OP_UNKNOWN
                        state <= FETCH_STATE;
                    end
                endcase
            end

            MEMORY_READ_STATE: begin
                state <= WRITEBACK_STATE;
            end

            // MEMORY_READ_WAIT_STATE: begin
            //     state <= WRITEBACK_STATE;
            // end

            MEMORY_WRITE_STATE, WRITEBACK_STATE: begin
                state <= FETCH_STATE;
            end

            default: begin
                state <= FETCH_STATE;
            end
        endcase
    end
end

assign imem_read      = (state == FETCH_STATE);
assign dmem_read      = (state == MEMORY_READ_STATE);
assign dmem_write     = (state == MEMORY_WRITE_STATE);
assign reg_write      = (state == WRITEBACK_STATE);
assign branch         = ((state == EXECUTE_STATE) && (operation == OP_BEQ));
assign jump           = ((state == EXECUTE_STATE) && (operation == OP_JAL));
assign mem_to_regFile = ((state == WRITEBACK_STATE) && (operation == OP_LW));
assign load_instr     = (state == FETCH_WAIT_STATE);
assign pc_inc         = (state == EXECUTE_STATE);
assign execute        = (state == EXECUTE_STATE);

always_comb begin

    // Defaults
    alu_src_imm = 1'b0;
    alu_op      = ALU_NONE;

    case (operation)

        OP_LW, OP_SW, OP_ADDI: begin
            alu_src_imm = 1'b1;
            alu_op      = ALU_ADD;
        end

        OP_ANDI: begin
            alu_src_imm = 1'b1;
            alu_op      = ALU_AND;
        end

        OP_AND: begin
            alu_op    = ALU_AND;
        end

        OP_OR: begin
            alu_op    = ALU_OR;
        end

        default: begin
            alu_src_imm = 1'b0;
            alu_op      = ALU_NONE;
        end

    endcase
end



endmodule