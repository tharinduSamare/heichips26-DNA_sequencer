module pico32_memory #(
    parameter DATA_WIDTH = 32,
    parameter MEM_DEPTH = 1024,
    parameter ADDR_WIDTH = $clog2(MEM_DEPTH)
)(
    input logic clk,
    input logic rstn,

    input logic rden,
    input logic wren,

    input logic [ADDR_WIDTH-1:0] addr,

    input logic [DATA_WIDTH-1:0] w_data,
    output logic [DATA_WIDTH-1:0] r_data
);

    logic [DATA_WIDTH-1:0] sram [0:MEM_DEPTH-1];

    integer i;

    initial begin

        for (i = 0; i < MEM_DEPTH; i = i + 1)
            sram[i] = '0;

        $readmemh(
            "/home/samare/Documents/heiChip/SW_DNA_allignment/benchmark/firmware/firmware.hex",
            sram
        );

    end


    always_ff @(posedge clk) begin

        if (!rstn) begin

            r_data <= '0;

        end
        else if (wren) begin

            sram[addr] <= w_data;

        end
        else if (rden) begin

            r_data <= sram[addr];

        end

    end

endmodule