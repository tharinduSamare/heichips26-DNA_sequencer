module riscv_top_module_tb();

localparam CLK_FREQ = 100; // MHz
localparam CLK_PERIOD = 1000/CLK_FREQ; // ns

logic clk, rst;
logic [7:0]LED;

initial begin
    clk = 0;
    forever begin
        #(CLK_PERIOD/2) clk = ~clk;
    end
end


riscv_top_module dut(
    .clk(clk),
    .rst(rst),
    .LED(LED)
);

integer k;

initial begin
    rst = 1'b1;
    @(posedge clk);
    @(posedge clk);
    rst = 1'b0;

    repeat(1500) @(posedge clk);

    $display("Results:");

    for (k = 0; k < 20; k = k + 1) begin
        $display(
            "Result[%0d] = %0d",
            k,
            $signed(dut.fpga_top_inst.memory_inst.sram[(32'd420 + k)]) // final results are stored in memory starting from address 420
        );
    end

    $finish;
end

endmodule