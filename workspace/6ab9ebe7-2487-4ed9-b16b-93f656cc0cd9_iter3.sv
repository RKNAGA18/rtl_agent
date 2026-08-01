`timescale 1ns/1ps
`default_nettype none

module sipo_shift_register #(
    parameter DATA_WIDTH = 8
) (
    input  logic                    clk,
    input  logic                    rst,
    input  logic                    shift_en,
    input  logic                    serial_in,
    output logic [DATA_WIDTH-1:0]   data_out
);

    logic [DATA_WIDTH-1:0] reg_a;

    always_ff @(posedge clk) begin
        if (rst) begin
            reg_a <= '0;
        end else if (shift_en) begin
            reg_a <= {serial_in, reg_a[DATA_WIDTH-2:0]};
        end
    end

    assign data_out = reg_a;

endmodule

`default_nettype wire