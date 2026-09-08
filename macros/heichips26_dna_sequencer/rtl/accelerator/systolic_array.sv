`include "../macros.svh"

module systolic_array(
    input logic clk, rstn,
    input logic [2:0] s_in, t_in,
    input logic s_in_valid, t_in_valid,
    output logic s_in_ready, t_in_ready,
    output logic max_valid,
    output logic signed [`REG_WIDTH-1:0] max_out
);

logic [$clog2(`N)-1:0] s_counter, s_counter_next;
logic [$clog2(`M)-1:0] t_counter, t_counter_next;

typedef enum logic [2:0] {
    RESET_STATE = 3'b000,
    IDLE_STATE  = 3'b001,
    SEND_S_STATE  = 3'b010,
    SEND_T_STATE  = 3'b011,
    DONE_STATE  = 3'b100,
    DONE_2_STATE = 3'b101,
    CLEAR_STATE = 3'b110
} state_t;

state_t state, state_next;
logic processing;

// control path
always_ff @(posedge clk) begin
    if(rstn == 1'b0) begin
        state     <= RESET_STATE;
        s_counter <= '0;
        t_counter <= '0;
    end
    else begin
        state     <= state_next;
        s_counter <= s_counter_next;
        t_counter <= t_counter_next;
    end

end

always_comb begin
    state_next = state;
    s_counter_next = `N-1;
    t_counter_next = `M-1;

    case(state)
        RESET_STATE: begin
            state_next = IDLE_STATE;
            s_counter_next = `N-1;
            t_counter_next = `M-1;
        end

        IDLE_STATE: begin
            if (s_in_valid && t_in_valid) begin
                // $error("Error: Both s_in and t_in are valid at the same time. Only one should be valid.");
                state_next = RESET_STATE;
            end
            else if(s_in_valid == 1'b1) begin
                state_next = SEND_S_STATE;
                s_counter_next = `N - 2;
            end
            else if(t_in_valid == 1'b1) begin
                state_next = SEND_T_STATE;
                t_counter_next = `M - 2;
            end
        end

        SEND_S_STATE: begin
            if (s_counter > 0) begin
                s_counter_next = s_counter - 1;
            end
            else begin
                state_next = IDLE_STATE;
            end
        end

        SEND_T_STATE: begin
            if (t_counter > 0) begin
                t_counter_next = t_counter - 1;
            end
            else begin
                state_next = DONE_STATE;
            end
        end

        DONE_STATE: begin
            state_next = DONE_2_STATE;
        end

        DONE_2_STATE: begin // Final max_value calculation need an extra cycle
            state_next = CLEAR_STATE;
        end

        CLEAR_STATE: begin // need this state to reset the systolic array after processing all inputs
            if (s_in_valid == 1'b1 && t_in_valid == 1'b1) begin
                // $error("Error: Both s_in and t_in are valid at the same time. Only one should be valid.");
                state_next = RESET_STATE;
            end
            else if(s_in_valid == 1'b1) begin
                if(~processing) begin
                    state_next = SEND_S_STATE;
                    s_counter_next = `N - 2;
                end
            end
            else if(t_in_valid == 1'b1) begin
                state_next = SEND_T_STATE;
                t_counter_next = `M - 2;
            end
            else begin
                state_next = IDLE_STATE;
            end
        end

        default: begin
            // $error("Error: Invalid state encountered in systolic_array.");
            state_next = RESET_STATE;
        end            

    endcase
end

// data path

genvar i;
logic [`N-1:0][2:0] s_in_bus, t_in_bus, s_out_bus, t_out_bus;
logic signed [`N-1:0][`REG_WIDTH-1:0] max_in_bus, f_in_bus, v_in_bus, max_out_bus, f_out_bus, v_out_bus;
logic shift_s;
logic [2:0] s_in_bus_0, t_in_bus_0;
logic [`N-1:0]result_valid_in_bus, result_valid_out_bus;
logic result_valid_in_bus_0;

generate

    assign s_in_bus[0] = s_in_bus_0;
    assign t_in_bus[0] = t_in_bus_0;
    assign max_in_bus[0] = '0;
    assign f_in_bus[0] = '0;
    assign v_in_bus[0] = '0;
    assign result_valid_in_bus[0] = result_valid_in_bus_0;

    for(i=1; i<`N; i++) begin : PE_CHAIN

        localparam prev_max_score = i * `MATCH;
        localparam prev_reg_width = $clog2(prev_max_score + 1) + 1;

        assign s_in_bus[i] = s_out_bus[i-1];
        assign t_in_bus[i] = t_out_bus[i-1];
        assign max_in_bus[i] = `REG_WIDTH'(signed'(max_out_bus[i-1][prev_reg_width-1:0]));
        assign f_in_bus[i] = `REG_WIDTH'(signed'(f_out_bus[i-1][prev_reg_width-1:0]));
        assign v_in_bus[i] = `REG_WIDTH'(signed'(v_out_bus[i-1][prev_reg_width-1:0]));
        assign result_valid_in_bus[i] = result_valid_out_bus[i-1];
    end
endgenerate

generate
    for(i=0; i<`N; i++) begin : PE_ARRAY
        localparam local_max_score = (i+1) * `MATCH;
        localparam local_reg_width = $clog2(local_max_score + 1) + 1;
        
        PE #(.REG_WIDTH(local_reg_width)) pe_inst(
            .clk(clk),
            .rstn(rstn),
            .s_in(s_in_bus[i]),
            .t_in(t_in_bus[i]),
            .shift_s(shift_s),
            .max_in(max_in_bus[i][local_reg_width-1:0]),
            .f_in(f_in_bus[i][local_reg_width-1:0]),
            .v_in(v_in_bus[i][local_reg_width-1:0]),
            .result_valid_in(result_valid_in_bus[i]),
            .s_out(s_out_bus[i]),
            .t_out(t_out_bus[i]),
            .max_out(max_out_bus[i][local_reg_width-1:0]),
            .f_out(f_out_bus[i][local_reg_width-1:0]),
            .v_out(v_out_bus[i][local_reg_width-1:0]),
            .result_valid_out(result_valid_out_bus[i])

        );
    end
endgenerate

always_comb begin
    if(state == SEND_S_STATE) begin
        shift_s = 1'b1;
        s_in_bus_0 = s_in;
    end
    else if ((state == IDLE_STATE) && (s_in_valid == 1'b1)) begin
        shift_s = 1'b1;
        s_in_bus_0 = s_in;
    end
    else if ((state == CLEAR_STATE) && (s_in_valid == 1'b1) && (processing == 1'b0)) begin
        shift_s = 1'b1;
        s_in_bus_0 = s_in;
    end
    else begin
        shift_s = 1'b0;
        s_in_bus_0 = `BASE_IDLE;
    end
end

always_comb begin
    if(state == SEND_T_STATE) begin
        t_in_bus_0 = t_in;
    end
    else if ((state == IDLE_STATE) && (t_in_valid == 1'b1)) begin
        t_in_bus_0 = t_in;
    end
    else if ((state == CLEAR_STATE) && (t_in_valid == 1'b1)) begin
        t_in_bus_0 = t_in;
    end
    else begin
        t_in_bus_0 = `BASE_IDLE;
    end
end

assign result_valid_in_bus_0 = ((state == DONE_STATE))? 1'b1 : 1'b0;                    

assign max_valid = (result_valid_out_bus[`N-1]) ? 1'b1 : 1'b0;
assign max_out   = max_out_bus[`N-1];

assign processing = (state == SEND_T_STATE) || (|result_valid_in_bus);

assign s_in_ready = ~processing;
assign t_in_ready = (state == IDLE_STATE) || (state == SEND_T_STATE) || (state == CLEAR_STATE);

always_ff @(posedge clk) begin
    if(rstn) begin
        assert (
            state == RESET_STATE    ||
            state == IDLE_STATE     ||
            state == SEND_S_STATE   ||
            state == SEND_T_STATE   ||
            state == DONE_STATE     ||
            state == DONE_2_STATE   ||
            state == CLEAR_STATE
        ) else $error("Invalid state: %s", state);

        assert(!(s_in_valid && t_in_valid)) else $error("Both S and T sequences can not be valid at once");

        assert(~shift_s || (state == SEND_S_STATE || state_next == SEND_S_STATE)) else $error("shift_s = 1 at wrong state");

        assert(~max_valid || (max_out <= `MAX_SCORE)) else $error("Max_out exceeded possible maximum value");
    end
end
endmodule
