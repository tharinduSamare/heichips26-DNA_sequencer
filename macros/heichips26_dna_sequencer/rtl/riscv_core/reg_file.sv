module reg_file #(
    parameter DATA_WIDTH = 32,
    parameter X2_WIDTH = 32,
    parameter MAX_WIDTH = 32 // max(data_width , x2_width)
    )(
    input logic clk, rstn,
    input logic [1:0]rs1,
    input logic [1:0]rs2,
    input logic [1:0]rd,
    input logic reg_write,
    input logic [MAX_WIDTH-1:0]reg_data_in,

    output logic [MAX_WIDTH-1:0]rs1_data_out,
    output logic [MAX_WIDTH-1:0]rs2_data_out
);

// has only x0, x1, x2 registers
logic [DATA_WIDTH-1:0]x1;
logic [X2_WIDTH-1:0]x2; // only 10 bits. [31:10] will be zero

//read logic
always_comb begin
    rs1_data_out = '0;
    rs2_data_out = '0;

    case(rs1)
        2'd0: begin
            rs1_data_out = '0;
        end
        2'd1: begin
            rs1_data_out = {'0,x1};
        end
        2'd2: begin
            rs1_data_out = {'0,x2};
        end
    endcase

    case(rs2)
        2'd0: begin
            rs2_data_out = '0;
        end
        2'd1: begin
            rs2_data_out = {'0,x1};
        end
        2'd2: begin
            rs2_data_out = {'0,x2};
        end
    endcase
end

// write logic
always_ff @(posedge clk) begin
    if(!rstn) begin
        x1 <= '0;
        x2 <= '0;
    end
    else begin
        if(reg_write) begin
            if(rd == 2'd1) begin
                x1 <= reg_data_in[DATA_WIDTH-1:0];
            end
            if(rd == 2'd2) begin
                x2 <= reg_data_in[X2_WIDTH-1:0];
            end
        end
    end
end

endmodule