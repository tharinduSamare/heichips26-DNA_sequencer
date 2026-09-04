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

logic [`N-1:0]seq_in;
logic seq_type_in;
assign seq_in = data_in[`N-1:0];
assign seq_type_in = data_in[`N];

logic [`REG_WIDTH-1:0]status_reg;
logic [`REG_WIDTH-1:0]result_reg;
logic result_valid;

logic fifo_rd_en, seq_read_last_char, fifo_empty, fifo_full;
logic [`CHA_SEQ_LENGTH:0]fifo_seq_out;

// fifo //
fifo fifo_inst(
    .clk(clk), .rstn(rstn),
    .seq_in(seq_in),
    .seq_type(seq_type_in),
    .wr_addr(addr),
    .wr_en(wr_en), .rd_en(fifo_rd_en),
    .read_last_char(seq_read_last_char),
    .seq_out(fifo_seq_out), // [s/t, seq]
    .fifo_empty(fifo_empty), .fifo_full(fifo_full)
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
                if(!fifo_empty && (((seq_type_bit == S_SEQ_PREFIX) && (s_in_ready)) || ((seq_type_bit == T_SEQ_PREFIX) && (t_in_ready)))) begin
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

assign fifo_rd_en = (state == SEND_SEQ_STATE);

assign char_addr = seq_in_char_cnt<<1;
assign seq_char = {1'b1, fifo_seq_out[char_addr+:2]}; // all valid charactors have 1'b1 prefix. Systolic array internally generate IDLE_CHAR (3'b0) internally
assign seq_read_last_char = (seq_in_char_cnt == `N-1);
assign s_in_valid = !fifo_empty && (seq_type_bit == S_SEQ_PREFIX);
assign t_in_valid = !fifo_empty && (seq_type_bit == T_SEQ_PREFIX);


always_ff @(posedge clk) begin
    if(!rstn) begin
        result_reg <= '0;
        result_valid <= 1'b0;
    end
    else begin
        if(max_valid) begin
            result_reg <= max_out;
            result_valid <= 1'b1;
        end
        else if((addr == `STATUS_ADDR) && (rd_en == 1'b1)) begin // read-clean bit
            result_valid <= 1'b0;
        end
    end
end


assign status_reg = {'0, fifo_empty, fifo_full, result_valid};

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