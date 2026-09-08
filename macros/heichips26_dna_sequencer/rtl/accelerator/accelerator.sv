`include "../macros.svh"

module accelerator (
    input logic clk, rstn,
    input logic addr,
    input logic wr_en,
    input logic rd_en,
    input logic [`N:0] data_in, //{seq_type, seq[`N-1:0]}
    output logic [`REG_WIDTH-1:0]data_out
);

localparam S_SEQ_PREFIX = 1'b1;
localparam T_SEQ_PREFIX = 1'b0;
localparam SEQ_FIFO_DEPTH = `FIFO_DEPTH;
localparam RESULT_FIFO_DEPTH = SEQ_FIFO_DEPTH;

logic [`N-1:0]seq_in;
logic seq_type_in;
assign seq_in = data_in[`N-1:0];
assign seq_type_in = data_in[`N];

logic [`REG_WIDTH-1:0]status_reg;
logic [`REG_WIDTH-1:0]result_reg;

logic seq_fifo_rd_en, seq_read_last_char, seq_fifo_empty, seq_fifo_full;
logic [`CHA_SEQ_LENGTH:0]fifo_seq_out;

// seq_fifo //
seq_fifo #(.FIFO_DEPTH(SEQ_FIFO_DEPTH)) seq_fifo_inst(
    .clk(clk), .rstn(rstn),
    .seq_in(seq_in),
    .seq_type(seq_type_in),
    .wr_addr(addr),
    .wr_en(wr_en), .rd_en(seq_fifo_rd_en),
    .read_last_char(seq_read_last_char),
    .seq_out(fifo_seq_out), // [s/t, seq]
    .fifo_empty(seq_fifo_empty), .fifo_full(seq_fifo_full)
);

// systolic array
logic [2:0] seq_char;
logic [$clog2(`CHA_SEQ_LENGTH)-1:0] char_addr;
logic s_in_ready, t_in_ready, s_in_valid, t_in_valid, max_valid;
logic [`REG_WIDTH-1:0]max_out;

systolic_array systolic_array_inst(
    .clk(clk), .rstn(rstn),
    .s_in(seq_char), .t_in(seq_char),
    .s_in_valid(s_in_valid), .t_in_valid(t_in_valid),
    .s_in_ready(s_in_ready), .t_in_ready(t_in_ready),
    .max_valid(max_valid),
    .max_out(max_out)
);


logic [$clog2(`N)-1:0]seq_in_char_cnt;
logic seq_type_bit;
assign seq_type_bit = fifo_seq_out[`CHA_SEQ_LENGTH];


typedef enum logic {
    IDLE_STATE,
    SEND_SEQ_STATE
} state_t;

state_t state;

always_ff @(posedge clk) begin
    if(!rstn) begin
        state <= IDLE_STATE;
        seq_in_char_cnt <= '0;
    end
    else begin
        case(state)
            IDLE_STATE: begin
                if(!seq_fifo_empty && (((seq_type_bit == S_SEQ_PREFIX) && (s_in_ready)) || ((seq_type_bit == T_SEQ_PREFIX) && (t_in_ready)))) begin
                    state <= SEND_SEQ_STATE;
                    seq_in_char_cnt <= 1'b1;
                end
            end

            SEND_SEQ_STATE: begin
                seq_in_char_cnt <= seq_in_char_cnt + 1'b1;
                if(seq_in_char_cnt == `N-1) begin // need 1 cycle gap between each t_seq. So need to go to idle state first
                    state <= IDLE_STATE;
                end
            end
            
            default: begin
                state <= state;
                seq_in_char_cnt <= seq_in_char_cnt;
            end
        endcase
    end
end

assign seq_fifo_rd_en = (state == SEND_SEQ_STATE);

assign char_addr = seq_in_char_cnt<<1;
assign seq_char = {1'b1, fifo_seq_out[char_addr+:2]}; // all valid charactors have 1'b1 prefix. Systolic array internally generate IDLE_CHAR (3'b0) internally
assign seq_read_last_char = (seq_in_char_cnt == `N-1);
assign s_in_valid = !seq_fifo_empty && (seq_type_bit == S_SEQ_PREFIX);
assign t_in_valid = !seq_fifo_empty && (seq_type_bit == T_SEQ_PREFIX);

// result_fifo //
logic [`REG_WIDTH-1:0]result_fifo_out;
logic result_fifo_rd, result_fifo_full, result_fifo_empty;

assign result_fifo_rd = (addr == `RESULT_ADDR) && (rd_en == 1'b1) ;

result_fifo #(.FIFO_DEPTH(RESULT_FIFO_DEPTH)) result_fifo_inst(
    .clk(clk), .rstn(rstn),
    .result_in(max_out),
    .wr_en(max_valid),
    .rd_en(result_fifo_rd),
    .result_out(result_fifo_out),
    .fifo_empty(result_fifo_empty),
    .fifo_full(result_fifo_full)
);

assign result_reg = result_fifo_out;
assign status_reg = {'0, seq_fifo_full, seq_fifo_empty, result_fifo_full, result_fifo_empty};

always_ff @(posedge clk) begin
    if(!rstn) begin
        data_out <= '0;
    end
    else begin
        if(rd_en) begin
            if(addr == `STATUS_ADDR) begin
                data_out <= status_reg;
            end
            else begin // addr == `RESULT_ADDR
                data_out <= result_reg;
            end
        end
    end
end

endmodule