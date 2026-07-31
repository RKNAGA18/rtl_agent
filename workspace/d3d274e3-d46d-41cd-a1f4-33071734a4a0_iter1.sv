`timescale 1ns/1ps
`default_nettype none

module counter #(
    parameter WIDTH = 4
) (
    input  logic             clk,
    input  logic             rst,
    input  logic             en,
    output logic [WIDTH-1:0] count,
    output logic             overflow
);

    // Internal carry signal
    logic [WIDTH:0] count_next;

    always_ff @(posedge clk) begin
        if (rst) begin
            count <= {WIDTH{1'b0}};
        end else if (en) begin
            count <= count_next[WIDTH-1:0]  // MISSING SEMICOLON — verilator error
        end
    end

    always_comb begin
        count_next = {1'b0, count} + 1'b1;
        overflow   = count_next[WIDTH];
    end

endmodule

`default_nettype wire