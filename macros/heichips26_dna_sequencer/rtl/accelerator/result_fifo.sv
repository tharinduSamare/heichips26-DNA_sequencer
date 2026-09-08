`include "../macros.svh"

module result_fifo #(parameter FIFO_DEPTH = 8) (
    input logic clk, rstn,
    input logic [`REG_WIDTH-1:0] result_in,
    input logic wr_en, rd_en,
    output logic [`REG_WIDTH-1:0] result_out,
    output logic fifo_empty, fifo_full
);


logic [`REG_WIDTH-1:0] fifo [0:FIFO_DEPTH-1];
logic [$clog2(FIFO_DEPTH)-1:0] wr_ptr, rd_ptr;
logic [$clog2(FIFO_DEPTH):0]fifo_fill_count;

always_ff @(posedge clk) begin
    if(!rstn) begin
        wr_ptr <= '0;
        rd_ptr <= '0;
        fifo_fill_count <= '0;
    end
    else begin
        // write logic
        if(wr_en && !fifo_full) begin
            wr_ptr <= (wr_ptr == (FIFO_DEPTH-1)) ? '0 : wr_ptr + 1'b1;
            fifo[wr_ptr] <= result_in;
        end

        // read logic
        if(rd_en && !fifo_empty) begin
            rd_ptr <= (rd_ptr == (FIFO_DEPTH-1))? '0 : rd_ptr + 1'b1;
        end

        // fifo fill count
        case ({(wr_en && !fifo_full), (rd_en && !fifo_empty)})
            2'b01: fifo_fill_count <= fifo_fill_count - 1'b1; // no write & read
            2'b10: fifo_fill_count <= fifo_fill_count + 1'b1; // write & no read
            default: fifo_fill_count <= fifo_fill_count;
        endcase
    end
end

assign fifo_empty = (fifo_fill_count == '0);
assign fifo_full  = (fifo_fill_count == FIFO_DEPTH);
assign result_out = fifo[rd_ptr];

// assertions
always_ff @(posedge clk) begin
    if(rstn) begin
        assert (!(fifo_empty && fifo_full)) else $error("Fifo empty and fifo full cannot occur at once");
    end
end


endmodule