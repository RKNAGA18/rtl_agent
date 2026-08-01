`timescale 1ns/1ps
`default_nettype none

module fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 8
) (
    input  logic                    clk,
    input  logic                    rst,
    input  logic                    wr_en,
    input  logic [DATA_WIDTH-1:0]   wr_data,
    output logic                    full,
    input  logic                    rd_en,
    output logic [DATA_WIDTH-1:0]   rd_data,
    output logic                    empty,
    output logic [DEPTH-1:0]        count
);

    localparam ADDR_WIDTH = $clog2(DEPTH);

    logic [ADDR_WIDTH-1:0] wr_ptr;
    logic [ADDR_WIDTH-1:0] rd_ptr;
    logic [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    logic                  full_flag;
    logic                  empty_flag;

    assign full  = full_flag;
    assign empty = empty_flag;
    assign count = wr_ptr - rd_ptr;

    always_ff @(posedge clk) begin
        if (rst) begin
            wr_ptr  <= '0;
            rd_ptr  <= '0;
            full_flag <= '0;
            empty_flag <= '1;
        end else begin
            if (!full_flag && wr_en) begin
                mem[wr_ptr] <= wr_data;
                wr_ptr <= wr_ptr + 1;
                if (wr_ptr == DEPTH - 1) begin
                    full_flag <= '1;
                end
            end

            if (!empty_flag && rd_en) begin
                rd_ptr <= rd_ptr + 1;
                if (rd_ptr == DEPTH - 1) begin
                    empty_flag <= '1;
                end
            end

            if (wr_ptr == rd_ptr) begin
                empty_flag <= '1;
                full_flag <= '0;
            end
        end
    end

    always_comb begin
        rd_data = '0;
        if (!empty_flag) begin
            rd_data = mem[rd_ptr];
        end
    end

endmodule

`default_nettype wire