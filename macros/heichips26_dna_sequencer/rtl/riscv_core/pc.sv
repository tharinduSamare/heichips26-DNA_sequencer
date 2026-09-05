module pc #( // only word addressable, not byte addressable
    parameter ADDR_WIDTH = 10
)(
    input logic clk, rstn,
    input logic pc_inc, branch, jump, alu_eqz,
    input logic [ADDR_WIDTH-1:0] addr_offset,
    output logic [ADDR_WIDTH-1:0] pc
);

logic signed [ADDR_WIDTH-1:0] shifted_addr;
assign shifted_addr = signed'(addr_offset) >>> 2'd2;

always_ff @(posedge clk) begin
    if(!rstn) begin
        pc <= '0;
    end
    else begin
        if(branch && alu_eqz) begin
            pc <= pc + (shifted_addr);
        end
        else if (jump) begin
            pc <= pc + (shifted_addr);
        end
        else if (pc_inc) begin
            pc <= pc + 3'd1;
        end
    end
end

endmodule