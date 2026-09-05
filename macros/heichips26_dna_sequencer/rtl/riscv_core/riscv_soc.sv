

module riscv_soc#(
    parameter ADDR_WIDTH = 10,
    parameter DATA_WIDTH = 8,
    parameter INSTR_WIDTH = 32,
    parameter MEM_DEPTH = 1024
)(
    input logic clk1, rst,
    output logic [7:0]c
    // output logic [9:0]LED
);

logic rstn;
logic clk;
assign rstn = ~rst;
assign clk = clk1;

logic [INSTR_WIDTH-1:0]mem_rdata, mem_wdata; // this should be 32 
logic mem_ren, mem_wen;
logic [ADDR_WIDTH-1:0]mem_addr;

riscv_core #(.ADDR_WIDTH(ADDR_WIDTH), .DATA_WIDTH(DATA_WIDTH), .INSTR_WIDTH(INSTR_WIDTH)) riscv_core_inst(
    .clk(clk), .rstn(rstn),

    .mem_rdata(mem_rdata),
    .mem_addr(mem_addr),
    .mem_wdata(mem_wdata),
    .mem_ren(mem_ren), .mem_wen(mem_wen)
);

localparam SRAM_MEM_WIDTH = $clog2(MEM_DEPTH);
memory #(.DATA_WIDTH(INSTR_WIDTH), .MEM_DEPTH(MEM_DEPTH)) memory_inst(
    .clk(clk), .rstn(rstn),
    .rden(mem_ren), .wren(mem_wen),
    .addr(mem_addr[SRAM_MEM_WIDTH-1:0]),
    .w_data(mem_wdata),
    .r_data(mem_rdata)
);

// assign LED = mem_addr[9:0];
assign c = mem_addr[7:0];

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