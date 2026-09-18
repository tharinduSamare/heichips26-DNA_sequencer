module picorv32_sw_tb;

    reg clk;
    reg resetn;

    picorv32_dna_top dut (
        .clk    (clk),
        .resetn (resetn)
    );

    always #5 clk = ~clk;



    integer k;

    initial begin

        clk = 0;
        resetn = 0;

        #100;
        resetn = 1;

        #20_000_000;

        $display("Results:");

        for (k = 0; k < 20; k = k + 1) begin
            $display(
                "Result[%0d] = %0d",
                k,
                $signed(dut.memory[(32'h6f8 + k*4) >> 2]) // 000006f8 B alignment_results (from command: riscv64-unknown-elf-nm -n dna_accel.elf)
            );
        end

        $finish;
    end

endmodule