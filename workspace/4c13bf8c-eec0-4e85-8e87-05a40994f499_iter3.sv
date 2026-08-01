`timescale 1ns/1ps
`default_nettype none

module mux_2to1 #(
    parameter DATA_WIDTH = 8
) (
    input  logic [DATA_WIDTH-1:0] a,
    input  logic [DATA_WIDTH-1:0] b,
    input  logic                  sel,
    output logic [DATA_WIDTH-1:0] y
);

    always_comb begin
        if (sel) begin
            y = b;
        end else begin
            y = a;
        end
    end

endmodule

`default_nettype wire