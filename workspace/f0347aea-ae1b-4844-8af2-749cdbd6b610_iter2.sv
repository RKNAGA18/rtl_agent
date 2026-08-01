`timescale 1ns/1ps
`default_nettype none

module alu_4bit #(
    parameter WIDTH = 4
) (
    input  logic                    clk,
    input  logic                    rst,
    input  logic [WIDTH-1:0]        a,
    input  logic [WIDTH-1:0]        b,
    input  logic [2:0]              op,
    output logic [WIDTH-1:0]        result,
    output logic                    zero,
    output logic                    carry_out
);

    logic [WIDTH-1:0] sum;
    logic [WIDTH-1:0] diff;
    logic [WIDTH-1:0] and_res;
    logic [WIDTH-1:0] or_res;
    logic [WIDTH-1:0] xor_res;
    logic [WIDTH-1:0] not_a;
    logic [WIDTH-1:0] pass_a;
    logic [WIDTH-1:0] pass_b;

    assign sum     = a + b;
    assign diff    = a - b;
    assign and_res = a & b;
    assign or_res  = a | b;
    assign xor_res = a ^ b;
    assign not_a   = ~a;
    assign pass_a  = a;
    assign pass_b  = b;

    always_comb begin
        unique case (op)
            3'b000: result = sum;
            3'b001: result = diff;
            3'b010: result = and_res;
            3'b011: result = or_res;
            3'b100: result = xor_res;
            3'b101: result = not_a;
            3'b110: result = pass_a;
            3'b111: result = pass_b;
            default: result = '0;
        endcase
    end

    assign zero = (result == '0);
    assign carry_out = (op == 3'b000 && diff > a) || (op == 3'b001 && sum < a);

endmodule

`default_nettype wire