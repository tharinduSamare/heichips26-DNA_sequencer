`include "macros.svh"

module fpga_top#(
    parameter INSTR_WIDTH = 32,
    parameter MEM_ADDR_WIDTH = 10,
    parameter MEM_DATA_WIDTH = INSTR_WIDTH,
    parameter ACCEL_ADDR_WIDTH = 1,
    parameter ACCEL_WDATA_WIDTH = `N+1, // {seq_type, seq[`N-1:0]}
    parameter ACCEL_RDATA_WIDTH = `REG_WIDTH,
    parameter MEM_DEPTH = 1024
)(
    input logic clk, rst,

    // accelerator
    output logic accel_addr,
    output logic accel_wr_en,
    output logic accel_rd_en,
    output logic [`N:0] accel_wdata, //{seq_type, seq[`N-1:0]}
    input  logic [`REG_WIDTH-1:0]accel_rdata
);

logic rstn;
// logic clk;
assign rstn = ~rst;
// assign clk = clk1;

// cpu I/Os
logic [MEM_DATA_WIDTH-1:0]cpu_rdata, cpu_wdata; // this should be 32 
logic cpu_rd_en, cpu_wr_en;
logic [MEM_ADDR_WIDTH-1:0]cpu_addr;

// memory I/Os
logic [MEM_DATA_WIDTH-1:0]mem_rdata, mem_wdata; // this should be 32 
logic mem_rd_en, mem_wr_en;
logic [MEM_ADDR_WIDTH-1:0]mem_addr;

riscv_core #(.ADDR_WIDTH(MEM_ADDR_WIDTH), .DATA_WIDTH(ACCEL_WDATA_WIDTH), .INSTR_WIDTH(INSTR_WIDTH)) riscv_core_inst(
    .clk(clk), .rstn(rstn),

    .mem_rdata(cpu_rdata),
    .mem_addr(cpu_addr),
    .mem_wdata(cpu_wdata),
    .mem_ren(cpu_rd_en), .mem_wen(cpu_wr_en)
);

localparam SRAM_MEM_WIDTH = $clog2(MEM_DEPTH);
memory #(.DATA_WIDTH(INSTR_WIDTH), .MEM_DEPTH(MEM_DEPTH)) memory_inst(
    .clk(clk), .rstn(rstn),
    .rden(mem_rd_en), .wren(mem_wr_en),
    .addr(mem_addr[SRAM_MEM_WIDTH-1:0]),
    .w_data(mem_wdata),
    .r_data(mem_rdata)
);

memory_controller #(.MEM_DATA_WIDTH(MEM_DATA_WIDTH),
                    .MEM_ADDR_WIDTH(MEM_ADDR_WIDTH),
                    .ACCEL_WDATA_WIDTH(ACCEL_WDATA_WIDTH),
                    .ACCEL_RDATA_WIDTH(ACCEL_RDATA_WIDTH),
                    .ACCEL_ADDR_WIDTH(ACCEL_ADDR_WIDTH)) 
                    memory_controller_inst(
                        .clk(clk), .rstn(rstn),

                        // cpu
                        .addr_in(cpu_addr),
                        .w_data_in(cpu_wdata),
                        .rd_en(cpu_rd_en), .wr_en(cpu_wr_en),
                        .r_data_out(cpu_rdata),

                        // memory
                        .mem_addr_out(mem_addr),
                        .mem_w_data_out(mem_wdata),
                        .mem_rd_en(mem_rd_en), .mem_wr_en(mem_wr_en),
                        .mem_r_data_in(mem_rdata),

                        // accelerator
                        .accel_addr_out(accel_addr),
                        .accel_w_data_out(accel_wdata),
                        .accel_wr_en(accel_wr_en), .accel_rd_en(accel_rd_en),
                        .accel_r_data_in(accel_rdata)
);


endmodule


module memory #(
    // parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter MEM_DEPTH = 1024,
    parameter ADDR_WIDTH = $clog2(MEM_DEPTH)
)(
    input logic clk, rstn,
    input logic rden, wren,
    input logic [ADDR_WIDTH-1:0]addr,
    input logic [DATA_WIDTH-1:0]w_data,
    output logic [DATA_WIDTH-1:0]r_data
);

logic [DATA_WIDTH-1:0]sram[0:MEM_DEPTH-1];

// integer i;
// initial begin
//     for(i=0; i< MEM_DEPTH; i++) begin
//         sram[i] = '0;
//     end
//     $readmemh("/home/samare/Documents/heiChip/SW_DNA_allignment/scripts/output/mem_init.hex", sram);
// end

always_ff @(posedge clk) begin
    if(!rstn) begin
        r_data <= '0;
    end
    else if(wren) begin
        sram[addr] <= w_data;
    end
    else if(rden) begin
        r_data <= sram[addr];
    end
end

endmodule


module memory_controller #(
    parameter MEM_DATA_WIDTH = 32,
    parameter MEM_ADDR_WIDTH = 10,
    parameter ACCEL_WDATA_WIDTH = `N+1,
    parameter ACCEL_RDATA_WIDTH = `REG_WIDTH,
    parameter ACCEL_ADDR_WIDTH = 1
)(
    input logic clk, rstn,

    // cpu
    input logic [MEM_ADDR_WIDTH-1:0] addr_in,
    input logic [MEM_DATA_WIDTH-1:0] w_data_in,
    input logic rd_en, wr_en,
    output logic [MEM_DATA_WIDTH-1:0]r_data_out,

    // memory
    output logic [MEM_ADDR_WIDTH-1:0] mem_addr_out,
    output logic [MEM_DATA_WIDTH-1:0] mem_w_data_out,
    output logic mem_rd_en, mem_wr_en,
    input logic [MEM_DATA_WIDTH-1:0] mem_r_data_in,

    // accelerator
    output logic [ACCEL_ADDR_WIDTH-1:0] accel_addr_out,
    output logic [ACCEL_WDATA_WIDTH-1:0] accel_w_data_out,
    output logic accel_wr_en, accel_rd_en,
    input logic [ACCEL_RDATA_WIDTH-1:0] accel_r_data_in
    
);

logic mem_access;
assign mem_access = (addr_in[MEM_ADDR_WIDTH-1] == `MEMORY_ADDR_MSB)? 1'b1: 1'b0;

// memory write
assign mem_addr_out = addr_in;
assign mem_w_data_out = w_data_in;
assign mem_wr_en = wr_en & mem_access;
assign mem_rd_en = rd_en & mem_access;


// accelerator write
assign accel_addr_out = addr_in[ACCEL_ADDR_WIDTH-1:0];
assign accel_w_data_out = w_data_in[ACCEL_WDATA_WIDTH-1:0];
assign accel_wr_en = wr_en & ~mem_access;
assign accel_rd_en = rd_en & ~mem_access;

// memory + accelerator read
// read data available 1 cycle after the control signal
logic mem_access_old;
always_ff @(posedge clk) begin
    if(!rstn) begin
        mem_access_old <= 1'b0;
    end
    else begin
        mem_access_old <= mem_access;
    end
end

assign r_data_out = (mem_access_old == 1'b0)? {'0,accel_r_data_in} : mem_r_data_in;

endmodule