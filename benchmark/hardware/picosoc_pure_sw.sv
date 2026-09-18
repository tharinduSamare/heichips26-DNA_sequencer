module picorv32_dna_top (
    input  wire clk,
    input  wire resetn
);

    wire        mem_valid;
    wire        mem_instr;
    wire        mem_ready;

    wire [31:0] mem_addr;
    wire [31:0] mem_wdata;
    wire [3:0]  mem_wstrb;
    wire [31:0] mem_rdata;


    picorv32 cpu (
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


    /*
     * Simple RAM
     *
     * 64 KB = 16384 x 32-bit words
     */
    reg [31:0] memory [0:16383];

    initial begin
        $readmemh("./firmware/output/sw/firmware.hex", memory);
    end


    /*
     * Simple single-cycle memory
     */
    assign mem_ready = mem_valid;

    assign mem_rdata = memory[mem_addr[15:2]];


    always @(posedge clk) begin

        if (mem_valid && |mem_wstrb) begin

            if (mem_wstrb[0])
                memory[mem_addr[15:2]][7:0] <= mem_wdata[7:0];

            if (mem_wstrb[1])
                memory[mem_addr[15:2]][15:8] <= mem_wdata[15:8];

            if (mem_wstrb[2])
                memory[mem_addr[15:2]][23:16] <= mem_wdata[23:16];

            if (mem_wstrb[3])
                memory[mem_addr[15:2]][31:24] <= mem_wdata[31:24];

        end
    end

endmodule