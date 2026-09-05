`include "macros.svh"

`timescale 1ns/10ps

module heichips26_dna_sequencer_tb();

localparam int test_count = 20; // number of sequences in the file
localparam int test_type = 2; // 1: 1 S seq, 2: different S seqs

localparam CLK_PERIOD = 10;
localparam PIPELINE_DELAY = 4;

localparam S_SEQ_PREFIX = 1'b1;
localparam T_SEQ_PREFIX = 1'b0;

localparam RESULT_ADDR = 1'b0;
localparam STATUS_ADDR = 1'b1;

logic clk, rst_n;

initial begin
    clk = 1'b0;
    forever #(CLK_PERIOD/2) clk = ~clk;
end

wire [7:0] ui_in;    // Dedicated inputs - All used. 
wire [7:0] uo_out;   // Dedicated outputs
wire [7:0] uio_in;   // IOs: Input path
wire [7:0] uio_out;  // IOs: Output path
wire [7:0] uio_oe;   // IOs: Enable path (active high: 0=input, 1=output)
wire       ena;      // always 1 when the design is powered, so you can ignore it

logic addr;
logic wr_en;
logic rd_en;
logic [`N:0]data_in; //{seq_type, seq[`N-1:0]}
logic [`REG_WIDTH-1:0]data_out, result, status;

logic [`CHA_SEQ_LENGTH:0] s_seq, t_seq;
logic fifo_empty, fifo_full, result_valid;

logic [`N-1:0] seq_in; // [s/t, seq]
logic seq_type;

heichips26_dna_sequencer dut (.*);

assign ui_in = {4'b0, data_in[`N], rd_en, wr_en, addr};
assign uio_in = data_in[`N-1:0];
assign ena = 1'b1;
assign data_out = uo_out[5:0];

assign fifo_empty = status[2];
assign fifo_full = status[1];
assign result_valid = status[0];
assign data_in = {seq_type, seq_in};

initial begin
    int fd_s, fd_t, fd_max;
    int max_val;

    $dumpfile("heichips26_dna_sequencer_tb.fst");
    $dumpvars;

    fd_s = $fopen("../../scripts/output/seq1.txt", "r");
    fd_t = $fopen("../../scripts/output/seq2.txt", "r");
    fd_max = $fopen("../../scripts/output/final_op.txt", "r");

    if((fd_s == 0) || (fd_t == 0) || (fd_max == 0)) begin
        $error("some data files are missing");
    end

    reset_task();

    for(int i=0; i<test_count; i++) begin
        s_seq = read_s_seq_from_file(fd_s);
        t_seq = read_t_seq_from_file(fd_t);
        max_val = read_max_val_from_file(fd_max);

        // expected_max_val_queue.push_back(max_val);

        // send s_seq
        if(!((test_type == 1) && (i > 0))) begin
            read_reg(STATUS_ADDR);
            while(fifo_full) begin
                read_reg(STATUS_ADDR);
            end

            @(negedge clk);
            send_seq_task(s_seq);
        end

        // send t_seq
        read_reg(STATUS_ADDR);
        while(fifo_full) begin
            read_reg(STATUS_ADDR);
        end
        send_seq_task(t_seq);

        // read results
        read_reg(STATUS_ADDR);
        while(!result_valid) begin
            read_reg(STATUS_ADDR);
        end
        read_reg(RESULT_ADDR);

        // check results
        if(result != max_val) begin
            $display("[ERROR] Wrong result: %d, expected %d", result, max_val);
        end
        else begin
            $display("[INFO] Correct result: %d", result);
        end

    end

    $finish;

end


task automatic reset_task();
    @(negedge clk);
    rst_n = 1'b0;
    wr_en = 1'b0;
    seq_in = '0;
    seq_type = 1'b0;
    addr = STATUS_ADDR;
    rd_en = 1'b0;
    status = '0;
    result = '0;

    @(negedge clk);
    rst_n = 1'b1;
endtask

task automatic send_seq_task(input logic [`CHA_SEQ_LENGTH:0] seq);
    @(negedge clk);
    wr_en = 1'b1;
    addr = `FIFO_LOW_ADDR;
    seq_in = seq[`N-1:0];
    @(negedge clk);
    wr_en = 1'b0;
    repeat(PIPELINE_DELAY) @(negedge clk);
    wr_en = 1'b1;
    addr = `FIFO_HIGH_ADDR;
    seq_in = seq[`CHA_SEQ_LENGTH-1:`N];
    seq_type = seq[`CHA_SEQ_LENGTH];
    @(negedge clk);
    wr_en = 1'b0;
    seq_type = 1'b0;
endtask

task automatic read_reg(input logic rd_addr);
    @(negedge clk);
    addr = rd_addr;
    rd_en = 1'b1;
    @(negedge clk);
    rd_en = 1'b0;
    if(addr == STATUS_ADDR) begin
        status = data_out;
        // $display("read_reg_val at status: %0d", status);
    end

    else if (addr == RESULT_ADDR) begin
        result = data_out;
        // $display("read reg_val at result: %0d", result);
    end
    
endtask


function automatic logic [`CHA_SEQ_LENGTH:0] read_s_seq_from_file(input int fd);

    int ret;
    logic [`CHA_SEQ_LENGTH:0]s_seq;
    byte ch;

    do begin
        ret = $fscanf(fd, "%c", ch);
    end while (ret == 1 && ch != "[");

    for(int i=0; i< `N; i++) begin
        logic [2:0] tmp;
        ret = $fscanf(fd, "%b", tmp);
        s_seq[(`N-1-i)*2 +: 2] = tmp[1:0]; // read in reverse order

        if(i !=`N-1) begin
            ret = $fscanf(fd, "%c", ch);   // reads ','
        end
    end
    s_seq[`CHA_SEQ_LENGTH] = S_SEQ_PREFIX;

    // $display("s_seq %0b", s_seq);
    // $write("s_seq ");
    // for (int i = 0; i < `N; i++) begin
    //     $write("1%02b", s_seq[i*2 +: 2]);

    //     if (i != 7)
    //         $write(",");
    // end
    // $display("");

    do begin
        ret = $fscanf(fd, "%c", ch);
    end while (ret == 1 && ch != "]");

    return s_seq;

endfunction

function automatic logic [`CHA_SEQ_LENGTH:0] read_t_seq_from_file(input int fd);

    int ret;
    logic [`CHA_SEQ_LENGTH:0]t_seq;
    byte ch;

    do begin
        ret = $fscanf(fd, "%c", ch);
    end while (ret == 1 && ch != "[");

    for(int i=0; i< `N; i++) begin
        logic [2:0] tmp;
        ret = $fscanf(fd, "%b", tmp);
        t_seq[i*2 +: 2] = tmp[1:0];

        if(i !=`N-1) begin
            ret = $fscanf(fd, "%c", ch);   // reads ','
        end
    end
    t_seq[`CHA_SEQ_LENGTH] = T_SEQ_PREFIX;

    // $display("t_seq %0b", t_seq);
    // $write("t_seq ");
    // for (int i = 0; i < `N; i++) begin
    //     $write("1%02b", t_seq[i*2 +: 2]);

    //     if (i != 7)
    //         $write(",");
    // end
    // $display("");

    do begin
        ret = $fscanf(fd, "%c", ch);
    end while (ret == 1 && ch != "]");

    return t_seq;

endfunction

function automatic int read_max_val_from_file(input int fd);

    int max_val, ret;

    ret = $fscanf(fd, "%d", max_val);

    return max_val;

endfunction



endmodule