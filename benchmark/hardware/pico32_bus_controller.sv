module picorv32_bus_controller #(
    parameter MEM_DEPTH = 1024,

    parameter ACCEL_ADDR_WIDTH = 1,
    parameter ACCEL_WDATA_WIDTH = `N+1,
    parameter ACCEL_RDATA_WIDTH = `REG_WIDTH
)(
    input logic clk,
    input logic rstn,

    // ==========================================================
    // PicoRV32
    // ==========================================================

    input  logic        cpu_valid,
    input  logic [31:0] cpu_addr,
    input  logic [31:0] cpu_wdata,
    input  logic [3:0]  cpu_wstrb,

    output logic        cpu_ready,
    output logic [31:0] cpu_rdata,


    // ==========================================================
    // SRAM
    // ==========================================================

    output logic [31:0] mem_addr,
    output logic [31:0] mem_wdata,
    output logic        mem_rd_en,
    output logic        mem_wr_en,

    input logic [31:0]  mem_rdata,


    // ==========================================================
    // Accelerator
    // ==========================================================

    output logic                         accel_addr,
    output logic                         accel_wr_en,
    output logic                         accel_rd_en,
    output logic [ACCEL_WDATA_WIDTH-1:0] accel_wdata,

    input logic [ACCEL_RDATA_WIDTH-1:0]  accel_rdata
);


    // ==========================================================
    // Address decoding
    // ==========================================================

    logic accelerator_access;
    logic memory_access;

    assign accelerator_access = cpu_addr[31];
    assign memory_access      = ~cpu_addr[31];


    // ==========================================================
    // Request type
    // ==========================================================

    logic is_write;
    logic is_read;

    assign is_write = |cpu_wstrb;
    assign is_read  = ~is_write;


    // ==========================================================
    // Request latch
    // ==========================================================

    logic        pending;
    logic        pending_accel;
    logic        pending_mem;

    logic [31:0] pending_addr;
    logic [31:0] pending_wdata;
    logic [3:0]  pending_wstrb;


    // ==========================================================
    // SRAM
    // ==========================================================

    assign mem_addr  = pending_addr;
    assign mem_wdata = pending_wdata;

    assign mem_wr_en =
        pending &&
        pending_mem &&
        is_write;

    assign mem_rd_en =
        pending &&
        pending_mem &&
        is_read;


    // ==========================================================
    // Accelerator
    // ==========================================================

    assign accel_addr =
        pending_addr[ACCEL_ADDR_WIDTH-1:0];

    assign accel_wdata =
        pending_wdata[ACCEL_WDATA_WIDTH-1:0];

    assign accel_wr_en =
        pending &&
        pending_accel &&
        is_write;

    assign accel_rd_en =
        pending &&
        pending_accel &&
        is_read;


    // ==========================================================
    // State machine
    // ==========================================================

    typedef enum logic [1:0] {
        IDLE,
        WAIT_READ
    } state_t;

    state_t state;


    always_ff @(posedge clk) begin

        if (!rstn) begin

            state           <= IDLE;

            pending         <= 1'b0;
            pending_accel   <= 1'b0;
            pending_mem     <= 1'b0;

            pending_addr    <= 32'b0;
            pending_wdata   <= 32'b0;
            pending_wstrb   <= 4'b0;

        end
        else begin

            case (state)

                // ------------------------------------------------
                // IDLE
                // ------------------------------------------------

                IDLE: begin

                    pending <= 1'b0;

                    if (cpu_valid) begin

                        pending_addr  <= cpu_addr;
                        pending_wdata <= cpu_wdata;
                        pending_wstrb <= cpu_wstrb;

                        pending_accel <= cpu_addr[31];
                        pending_mem   <= ~cpu_addr[31];

                        pending <= 1'b1;

                        if (is_read) begin

                            // SRAM / accelerator read takes
                            // one cycle.
                            state <= WAIT_READ;

                        end
                        else begin

                            // Write can complete immediately.
                            state <= IDLE;

                        end

                    end

                end


                // ------------------------------------------------
                // WAIT_READ
                // ------------------------------------------------

                WAIT_READ: begin

                    pending <= 1'b0;

                    // The SRAM/accelerator output is now valid.
                    state <= IDLE;

                end

            endcase

        end

    end


    // ============================================================
    // PicoRV32 response
    // ============================================================

    always_comb begin

        cpu_ready = 1'b0;
        cpu_rdata = 32'b0;

        case (state)

            IDLE: begin

                if (cpu_valid && is_write) begin
                    cpu_ready = 1'b1;
                end

            end

            WAIT_READ: begin

                cpu_ready = 1'b1;

                if (pending_accel) begin

                    cpu_rdata =
                        {{(32-ACCEL_RDATA_WIDTH){1'b0}},
                         accel_rdata};

                end
                else begin

                    cpu_rdata = mem_rdata;

                end

            end

        endcase

    end

endmodule