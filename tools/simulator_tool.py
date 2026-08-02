"""
simulator_tool.py — Two-phase Verilator simulation wrapper.

Phase 1 (build): verilator --binary compiles DUT + testbench into a native binary.
Phase 2 (run):   the binary executes; testbench emits "PASS:" or "FAIL:" strings.

Amendments implemented:
  - Am. 2: SimResult.phase distinguishes build failures from run failures so
            agent.py can route to the correct correction prompt.
  - Am. 3: Full process-group kill (os.killpg / SIGKILL) on timeout for both
            the compile step and the run step — no zombie processes.
  - Am. 4: sv_parser.normalize() applied to testbench before writing to disk
            so missing `timescale / `default_nettype never causes a build failure.
"""

import os
import re
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from config import MOCK_MODE, SIMULATION_TIMEOUT

# Reuse the normalizer from sv_parser — do NOT duplicate logic (Amendment 4).
from tools.sv_parser import _normalize as _normalize_sv


# ─── Result Dataclass ────────────────────────────────────────────────────────
@dataclass
class SimResult:
    passed: bool
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool
    # Amendment 2: "build" = verilator --binary compile failed (structural bug)
    #              "run"   = binary ran but testbench reported FAIL (behavioral bug)
    phase: Literal["build", "run"] = "run"
    # Telemetry (Amendment 8)
    elapsed_ms: float = 0.0
    # Which file the error references (used for TB vs DUT routing in agent.py)
    error_file: str = ""   # e.g. "tb_top.sv" or "{session_id}_iter3.sv"


# ─── Top-Module Extractor ─────────────────────────────────────────────────────
_MODULE_NAME_RE = re.compile(r"\bmodule\s+(\w+)", re.IGNORECASE)


def extract_tb_top_module(tb_code: str) -> Optional[str]:
    """
    Extract the top-level testbench module name by finding the LAST `module`
    declaration in the file (reusing the same regex approach as sv_parser.py —
    no duplicate parser). Testbenches conventionally put the top module last.
    """
    matches = _MODULE_NAME_RE.findall(tb_code)
    if not matches:
        return None
    return matches[-1]


# ─── Platform helpers ────────────────────────────────────────────────────────
def _to_posix_path(path: str) -> str:
    """Convert Windows absolute path to WSL-compatible /mnt/... path."""
    p = Path(path).resolve()
    return "/mnt/" + str(p).replace("\\", "/").replace(":", "", 1).lower()


def _verilator_cmd(args: list) -> list:
    """Prefix verilator command with 'wsl' on Windows."""
    if sys.platform == "win32":
        return ["wsl"] + args
    return args


def _posix_if_win(path: str) -> str:
    """Return WSL-mapped path on Windows, native path on Linux."""
    return _to_posix_path(path) if sys.platform == "win32" else str(Path(path).resolve())


# ─── Process-group kill (Amendment 3) ────────────────────────────────────────
def _kill_process_group(proc: subprocess.Popen) -> None:
    """
    Kill the full process group rooted at proc.pid.
    On Linux: uses os.killpg(SIGKILL) to catch any child processes.
    On Windows (WSL): falls back to proc.kill().
    """
    try:
        if sys.platform != "win32" and hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        # Process already exited — safe to ignore
        pass


def _run_subprocess_with_timeout(
    cmd: list,
    timeout_s: int,
    cwd: Optional[str] = None,
    use_setsid: bool = True,
) -> tuple:
    """
    Run a subprocess with a process-group-aware timeout (Amendment 3).

    Returns (stdout, stderr, returncode, timed_out).
    """
    # setsid creates a new session so we can kill the whole group on timeout.
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if cwd:
        kwargs["cwd"] = cwd

    # Only use preexec_fn on Linux — not available on Windows (WSL handles its own PTY).
    if use_setsid and sys.platform != "win32" and hasattr(os, "setsid"):
        kwargs["preexec_fn"] = os.setsid

    proc = subprocess.Popen(cmd, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        return stdout, stderr, proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except Exception:
            stdout, stderr = "", ""
        return stdout, stderr, -1, True


# ─── Main entry point ────────────────────────────────────────────────────────
def run_simulation(
    dut_path: str,
    tb_code: str,
    workdir: str,
    timeout_s: int = SIMULATION_TIMEOUT,
) -> SimResult:
    """
    Compile DUT + testbench with verilator --binary, then execute the result.

    Parameters
    ----------
    dut_path : str
        Path to the DUT .sv file (already lint-passed).
    tb_code  : str
        Raw testbench SystemVerilog source (will be normalized + written to disk).
    workdir  : str
        Directory for obj_dir and compiled binary (must be writable).
    timeout_s : int
        Per-phase timeout in seconds (applies to both compile and run).

    Returns
    -------
    SimResult
        .passed      — True iff the binary ran and stdout contains "PASS:"
        .phase       — "build" if verilator compile failed, "run" otherwise
        .stdout/.stderr — captured output
        .timed_out   — True if either phase hit the timeout
    """
    if MOCK_MODE:
        return _mock_simulation(dut_path, tb_code)

    import time
    t0 = time.perf_counter()

    workdir_path = Path(workdir)
    workdir_path.mkdir(parents=True, exist_ok=True)

    # ── Amendment 4: normalize testbench (adds `timescale if missing) ─────────
    tb_normalized = _normalize_sv(tb_code)

    # Write testbench to disk
    tb_path = workdir_path / "tb_top.sv"
    tb_path.write_text(tb_normalized, encoding="utf-8")

    # Extract top module name
    top_module = extract_tb_top_module(tb_normalized)
    if not top_module:
        return SimResult(
            passed=False,
            stdout="",
            stderr="[RTL-AGENT ERROR] Could not detect testbench top module name.",
            returncode=-1,
            timed_out=False,
            phase="build",
            elapsed_ms=0.0,
        )

    obj_dir = workdir_path / "obj_dir"
    sim_binary = workdir_path / "sim_out"

    dut_p = _posix_if_win(dut_path)
    tb_p  = _posix_if_win(str(tb_path))
    obj_p = _posix_if_win(str(obj_dir))
    bin_p = _posix_if_win(str(sim_binary))

    # Phase 1: Compile
    compile_cmd = _verilator_cmd([
        "verilator",
        "--binary",
        "--timing",
        "-Wall",        # all warnings
        "-Wno-style",   # suppress DECLFILENAME and cosmetic warnings
        "-Wno-fatal",   # non-fatal warnings don't abort the build
        "--sv",
        "--top-module", top_module,
        "-o", bin_p,
        "--Mdir", obj_p,
        dut_p,
        tb_p,
    ])

    stdout_c, stderr_c, rc_c, timed_out_c = _run_subprocess_with_timeout(
        compile_cmd, timeout_s
    )

    elapsed_build = (time.perf_counter() - t0) * 1000

    if timed_out_c:
        return SimResult(
            passed=False,
            stdout=stdout_c,
            stderr=f"[RTL-AGENT ERROR] verilator --binary compile timed out after {timeout_s}s.",
            returncode=-1,
            timed_out=True,
            phase="build",
            elapsed_ms=elapsed_build,
            error_file="",
        )

    # String-based build pass/fail -- same rationale as verilator_tool.py.
    # Verilator may exit 1 for non-fatal warnings; %Error is the real signal.
    build_combined = stdout_c + stderr_c
    build_has_error = "%Error" in build_combined

    if build_has_error:
        # Determine whether the error mentions the testbench or the DUT.
        tb_basename = str(tb_path.name)   # e.g. "tb_top.sv"
        error_file = tb_basename if tb_basename in build_combined else ""
        # Amendment 2: compile failure -> phase="build" -> agent uses correction prompt
        return SimResult(
            passed=False,
            stdout=stdout_c,
            stderr=stderr_c,
            returncode=rc_c,
            timed_out=False,
            phase="build",
            elapsed_ms=elapsed_build,
            error_file=error_file,
        )

    # ── Phase 2: Run ───────────────────────────────────────────────────────────
    # On Windows/WSL the binary is inside WSL — invoke via wsl
    if sys.platform == "win32":
        run_cmd = ["wsl", bin_p]
    else:
        run_cmd = [str(sim_binary)]

    stdout_r, stderr_r, rc_r, timed_out_r = _run_subprocess_with_timeout(
        run_cmd, timeout_s
    )

    elapsed_total = (time.perf_counter() - t0) * 1000

    if timed_out_r:
        return SimResult(
            passed=False,
            stdout="FAIL: simulation timeout — binary exceeded wall-clock limit",
            stderr=stderr_r,
            returncode=-1,
            timed_out=True,
            phase="run",
            elapsed_ms=elapsed_total,
        )

    # Primary pass/fail signal: testbench-emitted strings, not just exit code.
    # $fatal sets nonzero exit but we also want the human-readable message surfaced.
    combined = stdout_r + stderr_r
    passed = "PASS:" in combined and "FAIL:" not in combined

    return SimResult(
        passed=passed,
        stdout=stdout_r,
        stderr=stderr_r,
        returncode=rc_r,
        timed_out=False,
        phase="run",
        elapsed_ms=elapsed_total,
    )


# ─── Mock mode shim ─────────────────────────────────────────────────────────
def _mock_simulation(dut_path: str, tb_code: str) -> SimResult:
    """
    Short-circuit to canned SimResult objects when MOCK_MODE=true.
    Reads the mock scenario index from a module-level counter so
    successive calls in one mock session return the scripted sequence.
    """
    from tools.mock_responses import get_mock_sim_result
    return get_mock_sim_result(dut_path, tb_code)
