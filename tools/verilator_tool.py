"""
verilator_tool.py — Subprocess wrapper for the Verilator lint tool.

Runs verilator --lint-only --Wall on a SystemVerilog file and returns
a structured result dict. Platform-agnostic: bare on Linux, wsl on Windows.
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

    # Build command — on Windows we call through WSL; on Linux call directly.
    if sys.platform == "win32":
        # WSL path conversion: C:\foo\bar.sv → /mnt/c/foo/bar.sv
        posix_path = "/mnt/" + str(sv_path).replace("\\", "/").replace(":", "", 1).lower()
        cmd = [
            "wsl", "verilator",
            "--lint-only",
            "--Wall",
            "--timing",
            posix_path,
        ]
    else:
        cmd = [
            "verilator",
            "--lint-only",
            "--Wall",
            "--timing",
            str(sv_path),
        ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": (
                f"[RTL-AGENT ERROR] Verilator timed out after {timeout} seconds.\n"
                "The design may contain a very large hierarchy or an infinite loop construct."
            ),
            "returncode": -1,
        }

    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": (
                "[RTL-AGENT ERROR] Verilator executable not found.\n"
                "Install with: sudo apt-get install verilator\n"
                "Or on AMD ROCm instance: sudo apt-get install -y verilator"
            ),
            "returncode": -2,
        }

    except Exception as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"[RTL-AGENT ERROR] Unexpected error running verilator: {exc}",
            "returncode": -3,
        }
