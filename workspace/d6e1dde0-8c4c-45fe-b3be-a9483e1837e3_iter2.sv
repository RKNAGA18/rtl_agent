`timescale 1ns/1ps
`default_nettype none

module uart_tx #(
    parameter CLK_FREQ = 50_000_000,
    parameter BAUD_RATE = 115_200
) (
    input  logic                    clk,
    input  logic                    rst,
    input  logic                    tx_start,
    input  logic [7:0]              tx_data,
    output logic                    tx_serial,
    output logic                    tx_busy
);

    localparam CLK_PERIOD = CLK_FREQ / 1000000;
    localparam BAUD_PERIOD = CLK_PERIOD / BAUD_RATE;
    localparam TX_BIT_COUNT = 10; // 8 data bits + 1 start bit + 1 stop bit

    logic [TX_BIT_COUNT-1:0] state;
    logic [7:0] data_reg;
    logic [3:0] bit_count;
    logic [31:0] bit_timer;
    logic tx_bit;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state       <= 0;
            data_reg    <= 0;
            bit_count   <= 0;
            bit_timer   <= 0;
            tx_serial   <= 1;
            tx_busy     <= 0;
        end else begin
            case (state)
                0: begin // IDLE
                    tx_serial <= 1;
                    tx_busy   <= 0;
                    if (tx_start) begin
                        state     <= 1;
                        data_reg  <= tx_data;
                        bit_count <= 0;
                        bit_timer <= BAUD_PERIOD - 1;
                        tx_busy   <= 1;
                    end
                end
                1: begin // START BIT
                    tx_serial <= 0;
                    if (bit_timer == 0) begin
                        state     <= 2;
                        bit_timer <= BAUD_PERIOD - 1;
                    end else begin
                        bit_timer <= bit_timer - 1;
                    end
                end
                2: begin // DATA BITS
                    tx_serial <= data_reg[bit_count];
                    if (bit_timer == 0) begin
                        bit_count <= bit_count + 1;
                        bit_timer <= BAUD_PERIOD - 1;
                    end else begin
                        bit_timer <= bit_timer - 1;
                    end
                    if (bit_count == 7) begin
                        state <= 3;
                    end
                end
                3: begin // STOP BIT
                    tx_serial <= 1;
                    if (bit_timer == 0) begin
                        state <= 0;
                    end else begin
                        bit_timer <= bit_timer - 1;
                    end
                end
                default: state <= 0;
            endcase
        end
    end

endmodule

`default_nettype wire