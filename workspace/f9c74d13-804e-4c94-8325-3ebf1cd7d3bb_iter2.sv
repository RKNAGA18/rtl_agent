`timescale 1ns/1ps
`default_nettype none

module sync_binary_counter #(
    parameter WIDTH = 4
) (
    input  logic                    clk,
    input  logic                    rst,
    input  logic                    en,
    output logic [WIDTH-1:0]        count,
    output logic                    overflow
);

    logic [WIDTH-1:0] reg_count;

    always_ff @(posedge clk) begin
        if (rst) begin
            reg_count <= '0;
        end else if (en) begin
            if (reg_count == (1 << WIDTH) - 1) begin
                reg_count <= '0;
                overflow <= 1'b1;
            end else begin
                reg_count <= reg_count + 1;
                overflow <= 1'b0;
            end
        end
    end

    assign count = reg_count;

endmodule

`default_nettype wire