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
    // Extended count to detect overflow on MSB carry
    logic [WIDTH:0] count_ext;

    // Synchronous active-high reset — corrected from async version
    always_ff @(posedge clk) begin
        if (rst) begin
            count <= {WIDTH{1'b0}};
        end else if (en) begin
            count <= count_ext[WIDTH-1:0];
        end
    end

    always_comb begin
        count_ext = {1'b0, count} + 1'b1;
        overflow  = count_ext[WIDTH];
    end

endmodule

`default_nettype wire