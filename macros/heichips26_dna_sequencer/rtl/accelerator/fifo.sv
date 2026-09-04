`include "../macros.svh"

module fifo(
    input logic clk, rstn,
    input logic [`N-1:0] seq_in,
    input logic seq_type,
    input logic wr_addr,
    input logic wr_en, rd_en,
    input logic read_last_char,
    output logic [`CHA_SEQ_LENGTH:0] seq_out, // [s/t, seq]
    output logic fifo_empty, fifo_full
);

logic [`CHA_SEQ_LENGTH:0] fifo[0:1]; // [s/t, seq]
logic fifo_wr_ptr, fifo_rd_ptr;
logic [1:0]fifo_fill_count;

always_ff @(posedge clk) begin
    if(!rstn) begin
        fifo_wr_ptr <= 1'b0;
        fifo_rd_ptr <= 1'b0;
        fifo_fill_count <= '0;
    end
    else begin
        // fifo write
        if(wr_en & !fifo_full) begin
            if(wr_addr == `FIFO_LOW_ADDR) begin
                fifo[fifo_wr_ptr][`N-1:0] <= seq_in;
            end
            else begin // wr_addr = `FIFO_HIGH_ADDR
                fifo[fifo_wr_ptr][`CHA_SEQ_LENGTH-1:`N] <= seq_in;
                fifo[fifo_wr_ptr][`CHA_SEQ_LENGTH] <= seq_type;
                fifo_wr_ptr <= ~fifo_wr_ptr;
            end
        end

        // fifo read
        if (rd_en & !fifo_empty & read_last_char ) begin
            fifo_rd_ptr <= ~fifo_rd_ptr;
        end

        // fifo fill count
        case ({(wr_en && !fifo_full && (wr_addr == `FIFO_HIGH_ADDR)), (rd_en && !fifo_empty && read_last_char)})
            2'b01: fifo_fill_count <= fifo_fill_count - 1'b1; // no write & read
            2'b10: fifo_fill_count <= fifo_fill_count + 1'b1; // write & no read
            default: fifo_fill_count <= fifo_fill_count;
        endcase
    end
end

assign fifo_empty = (fifo_fill_count == 2'b00);
assign fifo_full  = (fifo_fill_count == 2'b10);
assign seq_out = fifo[fifo_rd_ptr];

assert property (@(posedge clk) disable iff (!rstn) !(fifo_empty && fifo_full)) else $error("Fifo empty and fifo full cannot occur at once");



endmodule