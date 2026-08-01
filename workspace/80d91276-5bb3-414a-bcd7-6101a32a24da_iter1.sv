`timescale 1ns/1ps
`default_nettype none

module traffic_light_controller #(
    parameter CLK_PERIOD = 100,
    parameter GREEN_DURATION = 10,
    parameter YELLOW_DURATION = 3,
    parameter RED_DURATION = 10
) (
    input  logic                    clk,
    input  logic                    rst,
    input  logic                    emergency,
    output logic [2:0]              red,
    output logic [2:0]              yellow,
    output logic [2:0]              green
);

    typedef enum logic [1:0] {GREEN_E, YELLOW_E, RED_E} state_t;
    state_t current_state, next_state;

    always_ff @(posedge clk or posedge rst) begin
        if (rst || emergency) begin
            current_state <= RED_E;
        end else begin
            current_state <= next_state;
        end
    end

    always_comb begin
        next_state = current_state;
        unique case (current_state)
            GREEN_E: begin
                if (emergency) begin
                    next_state = RED_E;
                end else if (CLK_PERIOD * GREEN_DURATION == 0) begin
                    next_state = YELLOW_E;
                end
            end
            YELLOW_E: begin
                if (emergency) begin
                    next_state = RED_E;
                end else if (CLK_PERIOD * YELLOW_DURATION == 0) begin
                    next_state = RED_E;
                end
            end
            RED_E: begin
                if (!emergency) begin
                    next_state = GREEN_E;
                end
            end
            default: next_state = RED_E;
        endcase
    end

    assign red     = (current_state == RED_E) ? 3'b100 : 3'b000;
    assign yellow  = (current_state == YELLOW_E) ? 3'b010 : 3'b000;
    assign green   = (current_state == GREEN_E) ? 3'b001 : 3'b000;

endmodule

`default_nettype wire