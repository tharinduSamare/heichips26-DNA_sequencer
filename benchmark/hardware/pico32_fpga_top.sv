`include "macros.svh"

module picorv32_fpga_top #(
    parameter MEM_DEPTH = 1024,
    parameter MEM_ADDR_WIDTH = 32,

    parameter ACCEL_ADDR_WIDTH = 1,
    parameter ACCEL_WDATA_WIDTH = `N+1,
    parameter ACCEL_RDATA_WIDTH = `REG_WIDTH
)(
    input  logic clk,
    input  logic rst,

    output logic accel_addr,
    output logic accel_wr_en,
    output logic accel_rd_en,
    output logic [`N:0] accel_wdata,
    input  logic [`REG_WIDTH-1:0] accel_rdata
);

    logic resetn;
    assign resetn = ~rst;


    // ============================================================
    // PicoRV32 memory interface
    // ============================================================

    logic        mem_valid;
    logic        mem_instr;
    logic        mem_ready;

    logic [31:0] mem_addr;
    logic [31:0] mem_wdata;
    logic [3:0]  mem_wstrb;
    logic [31:0] mem_rdata;


    // ============================================================
    // SRAM interface
    // ============================================================

    logic [31:0] mem_rdata_sram;
    logic [31:0] mem_wdata_sram;
    logic [31:0] mem_addr_sram;

    logic        mem_rd_en;
    logic        mem_wr_en;


    // ============================================================
    // PicoRV32
    // ============================================================

    picorv32 picorv32_inst (
        .clk        (clk),
        .resetn     (resetn),

        .mem_valid  (mem_valid),
        .mem_instr  (mem_instr),
        .mem_ready  (mem_ready),

        .mem_addr   (mem_addr),
        .mem_wdata  (mem_wdata),
        .mem_wstrb  (mem_wstrb),
        .mem_rdata  (mem_rdata)
    );


    // ============================================================
    // Address decoding
    //
    // bit 31 = 0 -> SRAM
    // bit 31 = 1 -> accelerator
    // ============================================================

    logic accelerator_access;
    logic memory_access;
    
    assign accelerator_access = mem_addr[31];
    assign memory_access      = ~mem_addr[31];


    // ============================================================
    // SRAM signals
    // ============================================================

    assign mem_addr_sram  = mem_addr;
    assign mem_wdata_sram = mem_wdata;

    assign mem_wr_en = mem_valid &&
                       memory_access &&
                       |mem_wstrb;

    assign mem_rd_en = mem_valid &&
                       memory_access &&
                       (mem_wstrb == 4'b0000);


    // ============================================================
    // Accelerator signals
    // ============================================================
    logic mem_valid_old;
    always_ff @(posedge clk) begin
        if (!resetn) begin
            mem_valid_old <= 1'b0;
        end
        else begin
            mem_valid_old <= mem_valid;
        end
    end

    assign accel_addr = mem_addr[2];

    assign accel_wdata =
        mem_wdata[ACCEL_WDATA_WIDTH-1:0];

    assign accel_wr_en =
        mem_valid && ~mem_valid_old &&
        accelerator_access &&
        |mem_wstrb;

    assign accel_rd_en =
        mem_valid && ~mem_valid_old &&
        accelerator_access &&
        (mem_wstrb == 4'b0000);


    // ============================================================
    // SRAM
    // ============================================================

    pico32_memory #(
        .DATA_WIDTH (32),
        .MEM_DEPTH  (MEM_DEPTH)
    ) memory_inst (
        .clk   (clk),
        .rstn  (resetn),

        .rden  (mem_rd_en),
        .wren  (mem_wr_en),

        .addr  (mem_addr_sram[$clog2(MEM_DEPTH)+1:2]),
        .w_data(mem_wdata_sram),
        .r_data(mem_rdata_sram)
    );


    // ============================================================
    // Read response
    //
    // SRAM and accelerator both have 1-cycle read latency.
    // Therefore mem_ready is generated one cycle after the
    // original read request.
    // ============================================================

    logic read_pending;
    logic read_pending_accel;
    logic read_pending_mem;


    always_ff @(posedge clk) begin

        if (!resetn) begin
            read_pending       <= 1'b0;
            read_pending_accel <= 1'b0;
            read_pending_mem   <= 1'b0;
        end
        else begin

            // Capture the type of the current read request
            read_pending <= mem_valid &&
                            (mem_wstrb == 4'b0000);

            read_pending_accel <=
                mem_valid &&
                accelerator_access &&
                (mem_wstrb == 4'b0000);

            read_pending_mem <=
                mem_valid &&
                memory_access &&
                (mem_wstrb == 4'b0000);

        end
    end


    // ============================================================
    // Return data
    // ============================================================

    always_comb begin

        if (read_pending_accel) begin

            mem_rdata = {{(32-ACCEL_RDATA_WIDTH){1'b0}},
                         accel_rdata};

        end
        else if (read_pending_mem) begin

            mem_rdata = mem_rdata_sram;

        end
        else begin

            mem_rdata = 32'b0;

        end

    end


    // ============================================================
    // Memory response
    //
    // Writes can complete immediately.
    // Reads complete one cycle later.
    // ============================================================

    always_comb begin

        if (!mem_valid) begin
            mem_ready = 1'b0;
        end
        else if (|mem_wstrb) begin
            // write
            mem_ready = 1'b1;
        end
        else begin
            // read
            mem_ready = read_pending;
        end

    end

endmodule