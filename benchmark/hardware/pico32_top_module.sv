`include "macros.svh"

module picorv32_top_module (
    input logic clk,
    input logic rst,

    output logic [7:0] LED
);

    localparam MEM_DEPTH = 1024;

    localparam ACCEL_ADDR_WIDTH = 1;
    localparam ACCEL_WDATA_WIDTH = `N+1;
    localparam ACCEL_RDATA_WIDTH = `REG_WIDTH;


    // ==========================================================
    // Accelerator interface
    // ==========================================================

    logic accel_addr;
    logic accel_wr_en;
    logic accel_rd_en;

    logic [`N:0] accel_wdata;

    logic [`REG_WIDTH-1:0] accel_rdata;


    // ==========================================================
    // PicoRV32 system
    // ==========================================================

    picorv32_fpga_top #(
        .MEM_DEPTH(MEM_DEPTH),

        .ACCEL_ADDR_WIDTH(ACCEL_ADDR_WIDTH),
        .ACCEL_WDATA_WIDTH(ACCEL_WDATA_WIDTH),
        .ACCEL_RDATA_WIDTH(ACCEL_RDATA_WIDTH)

    ) picorv32_fpga_top_inst (

        .clk(clk),
        .rst(rst),

        .accel_addr(accel_addr),
        .accel_wr_en(accel_wr_en),
        .accel_rd_en(accel_rd_en),

        .accel_wdata(accel_wdata),
        .accel_rdata(accel_rdata)
    );


    // ==========================================================
    // DNA accelerator
    // ==========================================================

    accelerator accelerator_inst (

        .clk(clk),
        .rstn(~rst),

        .addr(accel_addr),

        .wr_en(accel_wr_en),
        .rd_en(accel_rd_en),

        .data_in(accel_wdata),
        .data_out(accel_rdata)
    );


    // ==========================================================
    // Debug
    // ==========================================================

    assign LED = accel_wdata[7:0];

endmodule