`timescale 1ns/1ps
`default_nettype none

module tb_counter;
    localparam WIDTH = 4;

    logic             clk = 0;
    logic             rst;
    logic             en;
    logic [WIDTH-1:0] count;
    logic             overflow;

    // DUT instantiation
    counter #(.WIDTH(WIDTH)) dut (
        .clk      (clk),
        .rst      (rst),
        .en       (en),
        .count    (count),
        .overflow (overflow)
    );

    always #5 clk = ~clk;  // 100 MHz clock

    // Watchdog: 500-cycle timeout
    integer cycle_count = 0;
    always_ff @(posedge clk) begin
        cycle_count <= cycle_count + 1;
        if (cycle_count >= 500) begin
            $display("FAIL: timeout — simulation exceeded cycle limit");
            $fatal;
        end
    end

    initial begin
        // ── Test 1: Reset behaviour ──────────────────────────────────────
        rst = 1; en = 0;
        @(posedge clk); #1;
        if (count !== 4'd0) begin
            $display("FAIL: count should be 0 after SYNCHRONOUS reset, got %0d", count);
            $fatal;
        end

        // Release reset, verify count stays at 0 with en=0
        rst = 0; en = 0;
        @(posedge clk); #1;
        if (count !== 4'd0) begin
            $display("FAIL: count should remain 0 when en=0, got %0d", count);
            $fatal;
        end

        // ── Test 2: Normal increment ─────────────────────────────────────
        en = 1;
        repeat(4) @(posedge clk);
        #1;
        if (count !== 4'd4) begin
            $display("FAIL: expected count=4 after 4 enabled cycles, got %0d", count);
            $fatal;
        end

        // ── Test 3: Wraparound / overflow ────────────────────────────────
        en = 1;
        repeat(11) @(posedge clk);
        #1;
        // After 4+11=15 cycles, count should be 15 and overflow next cycle
        if (count !== 4'd15) begin
            $display("FAIL: expected count=15 before overflow, got %0d", count);
            $fatal;
        end
        @(posedge clk); #1;
        if (count !== 4'd0) begin
            $display("FAIL: expected count to wrap to 0 after overflow, got %0d", count);
            $fatal;
        end
        if (overflow !== 1'b0) begin
            // overflow is a combinational look-ahead; at 0 it should be 0
            $display("FAIL: overflow should be 0 when count=0, got %0b", overflow);
            $fatal;
        end

        $display("PASS: all checks passed");
        $finish;
    end
endmodule

`default_nettype wire