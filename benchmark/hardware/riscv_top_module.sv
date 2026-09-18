`include "macros.svh"

module riscv_top_module(
    input logic clk, rst,
    output logic [7:0] LED

);

localparam INSTR_WIDTH = 32;
localparam MEM_ADDR_WIDTH = 10;
localparam MEM_DATA_WIDTH = INSTR_WIDTH;
localparam ACCEL_ADDR_WIDTH = 1;
localparam ACCEL_WDATA_WIDTH = `N+1; // {seq_type, seq[`N-1:0]}
localparam ACCEL_RDATA_WIDTH = `REG_WIDTH;
localparam MEM_DEPTH = 1024;

// accelerator
logic accel_addr;
logic accel_wr_en;
logic accel_rd_en;
logic [`N:0] accel_wdata; //{seq_type, seq[`N-1:0]}
logic [`REG_WIDTH-1:0]accel_rdata;

fpga_top #(
    .INSTR_WIDTH(INSTR_WIDTH),
    .MEM_ADDR_WIDTH(MEM_ADDR_WIDTH),
    .MEM_DATA_WIDTH(MEM_DATA_WIDTH),
    .ACCEL_ADDR_WIDTH(ACCEL_ADDR_WIDTH),
    .ACCEL_WDATA_WIDTH(ACCEL_WDATA_WIDTH), // {seq_type, seq[`N-1:0]}
    .ACCEL_RDATA_WIDTH(ACCEL_RDATA_WIDTH),
    .MEM_DEPTH(MEM_DEPTH)) 
    fpga_top_inst(
    .clk(clk), .rst(rst),

    // accelerator
    .accel_addr(accel_addr),
    .accel_wr_en(accel_wr_en),
    .accel_rd_en(accel_rd_en),
    .accel_wdata(accel_wdata), //{seq_type, seq[`N-1:0]}
    .accel_rdata(accel_rdata)
);

accelerator accelerator_inst(
    .clk(clk), .rstn(~rst),
    .addr(accel_addr),
    .wr_en(accel_wr_en),
    .rd_en(accel_rd_en),
    .data_in(accel_wdata), //{seq_type, seq[`N-1:0]}
    .data_out(accel_rdata)
);

assign LED = accel_wdata[7:0];

endmodule