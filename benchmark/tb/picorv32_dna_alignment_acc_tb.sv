module picorv32_acc_tb;

    reg clk;
    reg rst;
    logic [7:0] LED;

    picorv32_top_module dut (
        .clk    (clk),
        .rst    (rst),
        .LED (LED)
    );

    always #5 clk = ~clk;



    integer k;

    initial begin

        clk = 0;
        rst = 1;

        #100;
        rst = 0;

        #20_000_000;

        $display("Results:");

        for (k = 0; k < 20; k = k + 1) begin
            $display(
                "Result[%0d] = %0d",
                k,
                $signed(dut.picorv32_fpga_top_inst.memory_inst.sram[(32'h288 + k*4) >> 2]) // 00000288 B results (from command: riscv64-unknown-elf-nm -n dna_accel.elf)
            );
        end

        $finish;
    end

endmodule