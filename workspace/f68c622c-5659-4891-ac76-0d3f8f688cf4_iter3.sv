`timescale 1ns/1ps
`default_nettype none

module priority_encoder #(
    parameter WIDTH = 8
) (
    input  logic                    clk,
    input  logic                    rst,
    input  logic [WIDTH-1:0]      data_in,
    output logic [clog2(WIDTH)-1:0] encoded,
    output logic                    valid_out
);

    logic [clog2(WIDTH)-1:0] encoded_reg;

    always_ff @(posedge clk) begin
        if (rst) begin
            encoded_reg <= '0;
            valid_out <= '0;
        end else begin
            encoded_reg <= encoded;
            valid_out <= (data_in != '0);
        end
    end

    always_comb begin
        encoded = '0;
        valid_out = '0;
        for (int i = 0; i < WIDTH; i++) begin
            if (data_in[i]) begin
                encoded = i;
                valid_out = '1;
                break;
            end
        end
    end

endmodule

`default_nettype wire