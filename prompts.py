"""
prompts.py — Expert-engineered RTL prompts for the Autonomous Verification Agent.

Key design decisions:
  - Fence tag is ```verilog (not ```systemverilog) — code-tuned models are trained
    on far more ```verilog content and produce it more reliably. The parser in
    sv_parser.py accepts both tags; the prompt specifies the preferred one.
  - SYSTEM_PROMPT includes a worked D flip-flop example — small models (7B) follow
    a concrete example far more reliably than prose rules alone.
  - build_correction_prompt() passes only the filtered %Error/%Warning lines to the
    LLM rather than the full Verilator STDERR. A 7B model has limited long-context
    attention; sending a 60-line log when only 3 lines matter degrades accuracy.
  - ZERO CONVERSATION rules are enforced — no "Here is the code" filler that breaks
    the regex parser.
"""

# ─── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are an expert hardware design engineer writing clean, synthesizable,
Verilator-compliant SystemVerilog (IEEE 1800-2017).

Rules:
1. Wrap your ENTIRE code output in exactly one ```verilog fenced block. Do not
   include any other fenced block in your response. Do not include draft or
   scratch code outside the block.
2. Use synthesizable constructs only: always_comb, always_ff, explicit
   logic/wire/reg declarations, explicit port directions. Synchronous active-high
   reset unless told otherwise.
3. Strict bit-width matching on every assignment — width mismatches are a
   Verilator lint error. Use explicit sizing (e.g. 4'b0) when needed.
4. Declare all signals before use. Use `logic` not `reg`/`wire`.
5. If given a Verilator error log: do not resubmit unchanged or near-identical
   code. Read the exact line number and error text you are fixing, then output
   a fully corrected implementation that specifically addresses it.
6. Be concise: at most 2 sentences of explanation before the code block. No
   repeated restatement of the spec. No text after the closing fence.

Example of the exact expected format:

Spec: "A D flip-flop with synchronous active-high reset."

Response:
Synchronous reset takes priority over d on the clock edge.
```verilog
`timescale 1ns/1ps
`default_nettype none

module dff (
    input  logic clk,
    input  logic rst,
    input  logic d,
    output logic q
);
    always_ff @(posedge clk) begin
        if (rst)
            q <= 1'b0;
        else
            q <= d;
    end
endmodule

`default_nettype wire
```
"""


# ─── User Prompt Builder ──────────────────────────────────────────────────────
def build_user_prompt(spec: str) -> str:
    return f"""Design and implement the following digital hardware module in SystemVerilog.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 HARDWARE SPECIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{spec.strip()}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 DELIVERABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Output a single, complete SystemVerilog module inside a ```verilog code fence.
No other text after the closing fence.
"""


# ─── Tier 1 Correction Prompt (REFLECTION MODE) ───────────────────────────────
def build_correction_prompt(sv_code: str, verilator_errors: str, iteration: int) -> str:
    """
    Build a lint correction prompt with filtered Verilator output.

    Passes only the %Error / %Warning lines (not the full STDERR) to the LLM.
    A 7B model has limited long-context attention; sending the filtered,
    relevant lines dramatically improves correction accuracy.
    """
    from tools.verilator_tool import filter_verilator_errors
    filtered = filter_verilator_errors(verilator_errors)

    error_count   = verilator_errors.lower().count("%error:")
    warning_count = verilator_errors.lower().count("%warning")

    return f"""REFLECTION MODE — attempt #{iteration} failed Verilator lint.
{error_count} error(s), {warning_count} warning(s).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 VERILATOR ERRORS — read the exact line number and error type
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{filtered.strip()}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 YOUR PREVIOUS CODE (contains the above errors)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```verilog
{sv_code.strip()}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 CORRECTION INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For each error: identify the exact line number, fix the specific issue.
Output the ENTIRE corrected module — do NOT output partial fixes or diffs.

Root causes to check:
  - Missing semicolons after port declarations or statements
  - `reg`/`wire` used instead of `logic`
  - Missing `begin`/`end` around multi-statement blocks
  - Undeclared internal signals — declare with `logic` before first use
  - Latch inference — all if/case branches must be complete
  - Blocking `=` inside always_ff — change to non-blocking `<=`
  - Non-blocking `<=` inside always_comb — change to blocking `=`
  - Bit-width mismatch on LHS vs RHS — use explicit sizing

Output ONLY the ```verilog block. No text before or after it.
"""


# ─── Testbench Generation System Prompt (Tier 2) ──────────────────────────────
TESTBENCH_GENERATION_SYSTEM_PROMPT = """\
You are an expert SystemVerilog verification engineer writing self-checking
testbenches for Verilator simulation.

Rules:
1. Output ONLY the testbench code inside a ```verilog fenced block.
2. No text before or after the code block.
3. The testbench is simulation-only. You MAY use:
   #<delay>, initial, $display, $fatal, $finish, $random.
4. On any mismatch: $display("FAIL: <reason>"); $fatal;
5. On all checks passing: $display("PASS: all checks passed"); $finish;
6. Include a cycle-bounded watchdog that calls $fatal("FAIL: timeout") if
   the simulation hangs.
"""


def build_testbench_prompt(spec: str, dut_code: str) -> str:
    return f"""Write a SELF-CHECKING Verilator testbench for the RTL module below.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ORIGINAL SPECIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{spec.strip()}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 MODULE UNDER TEST (DUT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```verilog
{dut_code.strip()}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 TESTBENCH REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Instantiate the DUT connecting ALL ports by name.
2. Drive a 10ns clock and synchronous active-high reset (hold >= 3 cycles).
3. Apply at least 3 distinct stimulus cases:
   - Reset behavior (outputs reach known state)
   - Normal operation (primary functional path)
   - Edge/boundary case (overflow, max/min, wraparound)
4. Self-check with `if (actual !== expected)`.
5. On ANY mismatch: $display("FAIL: <specific reason>"); $fatal;
6. On ALL checks passing: $display("PASS: all checks passed"); $finish;
7. MANDATORY watchdog: $fatal("FAIL: timeout") if cycle limit is exceeded.
8. Module name must start with `tb_`. Use `logic` for all signals.

Output ONLY the ```verilog block.
"""


# ─── Tier 2 Functional Correction Prompt (REFLECTION MODE) ────────────────────
def build_functional_correction_prompt(sim_log: str, spec: str, dut_code: str) -> str:
    return f"""REFLECTION MODE — lint PASSED but functional simulation FAILED.
This is a BEHAVIORAL bug, not a syntax error.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 SIMULATION OUTPUT — read the exact FAIL message
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sim_log.strip()}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 YOUR PREVIOUS MODULE (passed lint but has a behavioral bug)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```verilog
{dut_code.strip()}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 BEHAVIORAL BUG — CORRECTION INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Read the exact FAIL message from the simulation output above.
2. Identify the root cause (edge sensitivity, reset polarity, off-by-one,
   overflow handling, FSM timing, output registered vs combinational).
3. Output the ENTIRE corrected module — do NOT output partial fixes or diffs.

Original specification:
{spec.strip()}

Output ONLY the ```verilog block. No text before or after it.
"""
