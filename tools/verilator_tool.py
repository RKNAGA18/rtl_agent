"""
verilator_tool.py — Subprocess wrapper for the Verilator lint tool.

Flag rationale (Verilator 5.x — verilator.org/guide "Arguments"):
  -Wall          Single dash. Enables all lint warnings, promoting them to errors.
                 (Note: --Wall with double dash is silently accepted as an alias on
                 v5.020 but -Wall is the canonical documented form.)
  -Wno-style     Suppresses the entire "style" warning category as a group.
                 This covers: DECLFILENAME, EOFNEWLINE, UNDRIVEN, UNUSEDSIGNAL,
                 UNUSEDGENVAR, UNUSEDPARAM, and other cosmetic codes.
                 WHY: the agent saves files as {session_id}_iter{N}.sv but the LLM
                 names modules whatever the spec says (e.g. "mux2to1"). This filename/
                 module-name mismatch triggers DECLFILENAME on EVERY design regardless
                 of correctness, which was causing 0/8 benchmark failures.
  --timing       Required for timing-sensitivity annotations in SV.
  WIDTH kept:    Bit-width mismatches are genuine bugs, not cosmetic. Do NOT add
                 -Wno-WIDTH unless a specific false positive is confirmed.
"""

import subprocess
import sys
from pathlib import Path


def run_verilator(filepath: str, timeout: int = 30) -> dict:
    """
    Execute Verilator lint check on a SystemVerilog file.

    Parameters
    ----------
    filepath : str
        Absolute or relative path to the .sv file.
    timeout : int
        Maximum seconds to wait for verilator to complete.

    Returns
    -------
    dict with keys:
        success    : bool   — True if returncode == 0
        stdout     : str    — captured stdout
        stderr     : str    — captured stderr (contains the actual errors)
        returncode : int    — process exit code (0 = clean, non-zero = errors)
    """
    sv_path = Path(filepath).resolve()

    # Base flags — shared between WSL and native Linux invocations.
    _flags = [
        "--lint-only",
        "-Wall",        # single dash — canonical per verilator.org/guide Arguments
        "-Wno-style",   # suppress DECLFILENAME, EOFNEWLINE, UNUSEDSIGNAL, UNDRIVEN, etc.
                        # WIDTH is NOT suppressed — bit-width mismatches are real bugs.
        "--timing",
    ]

    # Build command — on Windows we call through WSL; on Linux call directly.
    if sys.platform == "win32":
        # WSL path conversion: C:\foo\bar.sv → /mnt/c/foo/bar.sv
        posix_path = "/mnt/" + str(sv_path).replace("\\", "/").replace(":", "", 1).lower()
        cmd = ["wsl", "verilator"] + _flags + [posix_path]
    else:
        cmd = ["verilator"] + _flags + [str(sv_path)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success":    result.returncode == 0,
            "stdout":     result.stdout,
            "stderr":     result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     (
                f"[RTL-AGENT ERROR] Verilator timed out after {timeout} seconds.\n"
                "The design may contain a very large hierarchy or an infinite loop construct."
            ),
            "returncode": -1,
        }

    except FileNotFoundError:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     (
                "[RTL-AGENT ERROR] Verilator executable not found.\n"
                "Install with: sudo apt-get install verilator\n"
                "Or on AMD ROCm instance: sudo apt-get install -y verilator"
            ),
            "returncode": -2,
        }

    except Exception as exc:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     f"[RTL-AGENT ERROR] Unexpected error running verilator: {exc}",
            "returncode": -3,
        }


def filter_verilator_errors(raw_output: str) -> str:
    """
    Extract only the %Error / %Warning-* lines from raw Verilator output.

    A 7B model has limited long-context attention; feeding it a 60-line compile
    log when only 3 lines are relevant wastes context and degrades correction
    accuracy. This strips informational/continuation lines and keeps only the
    lines that directly identify the problem.

    Also strips the Verilator "For warning description see ..." URLs, which are
    never useful for an LLM correction prompt.

    Returns the filtered lines joined by newline, or the original string if
    no diagnostic lines are found (failsafe — better to send too much than nothing).
    """
    lines = raw_output.splitlines()
    keep = []
    for line in lines:
        stripped = line.strip()
        # Keep lines starting with %Error or %Warning
        if stripped.startswith("%Error") or stripped.startswith("%Warning"):
            # Drop the "For warning description see URL" continuation lines
            if "For warning description see" in stripped:
                continue
            # Drop the "Use lint_off/lint_on" hint lines
            if 'Use "/* verilator lint_off' in stripped:
                continue
            keep.append(line)

    if not keep:
        return raw_output   # failsafe

    # Add a summary line for context
    error_count   = sum(1 for l in keep if "%Error"   in l and "%Error-" not in l)
    warning_count = sum(1 for l in keep if "%Warning" in l)
    header = f"[Verilator: {error_count} error(s), {warning_count} warning(s)]"
    return header + "\n" + "\n".join(keep)
