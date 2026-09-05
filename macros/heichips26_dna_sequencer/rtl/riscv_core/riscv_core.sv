module riscv_core #(
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter INSTR_WIDTH = 32
)(
    input logic clk, rstn,

    input logic [31:0] mem_rdata,
    output logic [ADDR_WIDTH-1:0] mem_addr,
    output logic [31:0] mem_wdata,
    output logic mem_ren, mem_wen
);

localparam DATA_WIRE_WIDTH = (DATA_WIDTH > ADDR_WIDTH)? DATA_WIDTH : ADDR_WIDTH;

// CONTROL_UNIT
operation_t operation;
alu_op_t alu_op;
logic alu_src_imm, reg_write, imem_read, dmem_read, branch, jump, mem_to_regFile, load_instr, pc_inc, execute;

control_unit control_unit_inst(
    .clk(clk), .rstn(rstn),
    .operation(operation),
    .alu_op(alu_op),
    .alu_src_imm(alu_src_imm),
    .reg_write(reg_write),
    .imem_read(imem_read),
    .dmem_read(dmem_read),
    .dmem_write(mem_wen),
    .branch(branch),
    .jump(jump),
    .mem_to_regFile(mem_to_regFile),
    .load_instr(load_instr),
    .pc_inc(pc_inc),
    .execute(execute)
);

logic alu_eqz;

// PC
logic [ADDR_WIDTH-1:0] branch_offset, pc;

pc #(.ADDR_WIDTH(ADDR_WIDTH)) pc_inst(
    .clk(clk), .rstn(rstn),
    .pc_inc(pc_inc),
    .branch(branch), 
    .jump(jump), 
    .alu_eqz(alu_eqz),
    .addr_offset(branch_offset), // not byte addressable only word addressable
    .pc(pc)
);

// DECODE
logic [INSTR_WIDTH-1:0] instr;
logic [1:0] rs1, rs2, rd;
logic [DATA_WIRE_WIDTH-1:0] rs1_data_out, rs2_data_out, reg_data_in;

always_ff @(posedge clk) begin
    if(!rstn) begin
        instr <= '0;
    end
    else if(load_instr) begin
        instr <= mem_rdata;
    end
end

// need only 2 bits (has x0,x1,x2 only)
assign rd     = instr[8:7];
assign rs1    = instr[16:15];
assign rs2    = instr[21:20];

logic [DATA_WIRE_WIDTH-1:0] imm; // immediate is used only for address calculation for SW, LW, JAL, BEQ etc.

decode_unit #(.IMM_WIDTH(DATA_WIRE_WIDTH)) decode_unit_inst(
    .instr(instr),
    .imm(imm),
    .operation(operation)
);

assign branch_offset = imm[ADDR_WIDTH-1:0];

// REG_FILE
reg_file #( .DATA_WIDTH(DATA_WIDTH), 
            .X2_WIDTH(ADDR_WIDTH),
            .MAX_WIDTH(DATA_WIRE_WIDTH)) reg_file_inst(
            .clk(clk),
            .rstn(rstn),
            .rs1(rs1),
            .rs2(rs2),
            .rd(rd),
            .reg_write(reg_write),
            .reg_data_in(reg_data_in),
            .rs1_data_out(rs1_data_out),
            .rs2_data_out(rs2_data_out)
);

//ALU
//ALU is only for the data address / pc calculations
logic [ADDR_WIDTH-1:0] alu_a, alu_b, alu_y, alu_result_reg;
assign alu_a = rs1_data_out[ADDR_WIDTH-1:0];
assign alu_b = (alu_src_imm == 1'b1)? imm : rs2_data_out[ADDR_WIDTH-1:0];
alu #(.DATA_WIDTH(DATA_WIRE_WIDTH))alu_inst(
    .a(alu_a),
    .b(alu_b),
    .y(alu_y),
    .alu_op(alu_op),
    .alu_eqz(alu_eqz)
);

always_ff @(posedge clk) begin
    if(!rstn) begin
        alu_result_reg <= '0;
    end
    else if(execute) begin
        alu_result_reg <= alu_y;
    end
end

// WRITE_BACK
assign reg_data_in = (mem_to_regFile == 1'b1)? mem_rdata[DATA_WIDTH-1:0] : alu_result_reg;


// memory interface
assign mem_wdata = {'0,rs2_data_out};
always_comb begin
    mem_ren = 1'b0;
    mem_addr = '0;

    if(imem_read == 1'b1) begin
        mem_ren = 1'b1;
        mem_addr = pc;
    end
    else if (dmem_read == 1'b1) begin
        mem_ren = 1'b1;
        mem_addr = alu_result_reg;
    end
    else if (mem_wen == 1'b1) begin
        mem_addr = alu_result_reg;
    end
end

endmodule