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

import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

from config import LOGS_DIR, MOCK_MODE, SIMULATION_TIMEOUT, WAVEFORMS_DIR

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
    vcd_data: Optional[str] = field(default=None)
    vcd_size_bytes: int = field(default=0)
    # Persistent logs and waveform tracing:
    log_file_path: Optional[str] = field(default=None)
    vcd_file_path: Optional[str] = field(default=None)
    error_summary: Optional[str] = field(default=None)
    iteration: int = 1


# ─── Waveform and Error Log Helpers ──────────────────────────────────────────
def _extract_vcd_signals(vcd_text: str) -> List[Dict[str, str]]:
    """Extract list of variable names and types from VCD header."""
    signals = []
    if not vcd_text:
        return signals
    for line in vcd_text.splitlines():
        line = line.strip()
        if line.startswith("$var"):
            parts = line.split()
            if len(parts) >= 5:
                signals.append({
                    "type": parts[1],
                    "width": parts[2],
                    "id": parts[3],
                    "name": parts[4],
                })
        elif line.startswith("$enddefinitions"):
            break
    return signals


def _extract_error_summary(stdout: str, stderr: str, phase: str) -> str:
    """Extract actionable failure summary from simulation stdout/stderr."""
    combined = (stdout + "\n" + stderr).strip()
    fail_lines = [l.strip() for l in combined.splitlines() if "FAIL:" in l or "%Error" in l or "%Fatal" in l or "TIMEOUT:" in l]
    if fail_lines:
        return "\n".join(fail_lines[:5])
    if phase == "build":
        return "Verilator C++ binary compilation failed."
    return "Simulation finished with failure status."


def _record_simulation_log(
    session_id: str,
    iteration: int,
    phase: str,
    passed: bool,
    timed_out: bool,
    returncode: int,
    stdout: str,
    stderr: str,
    elapsed_ms: float,
    vcd_path: Optional[Path],
    vcd_data: Optional[str],
    vcd_size_bytes: int,
    dut_path: str,
    top_module: Optional[str],
) -> tuple[Optional[str], Optional[str], str]:
    """
    Save structured simulation log and .vcd waveform file to disk,
    and update simulation_history.json for persistent tracing.
    """
    sid = session_id or "default_session"
    session_log_dir = LOGS_DIR / sid
    session_log_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save VCD waveform if present
    saved_vcd_path: Optional[Path] = None
    if vcd_path and vcd_path.exists() and vcd_path.stat().st_size > 0:
        iter_vcd_name = f"trace_iter{iteration}_{'pass' if passed else 'fail'}.vcd"
        saved_vcd_path = session_log_dir / iter_vcd_name
        shutil.copy2(vcd_path, saved_vcd_path)
        # Also maintain latest_trace.vcd
        shutil.copy2(vcd_path, session_log_dir / "latest_trace.vcd")
    elif vcd_data:
        iter_vcd_name = f"trace_iter{iteration}_{'pass' if passed else 'fail'}.vcd"
        saved_vcd_path = session_log_dir / iter_vcd_name
        saved_vcd_path.write_text(vcd_data, encoding="utf-8")
        (session_log_dir / "latest_trace.vcd").write_text(vcd_data, encoding="utf-8")

    # 2. Extract error summary and signals
    error_summary = _extract_error_summary(stdout, stderr, phase) if not passed else "All testbench assertions passed cleanly."
    signals = _extract_vcd_signals(vcd_data) if vcd_data else []

    # 3. Write human-readable simulation log
    iter_log_path = session_log_dir / f"sim_iter{iteration}.log"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    log_content = [
        "══════════════════════════════════════════════════════════════════════",
        f"  RTL-AGENT SIMULATION & WAVEFORM LOG — Iteration #{iteration}",
        "══════════════════════════════════════════════════════════════════════",
        f"Timestamp   : {now_iso}",
        f"Session ID  : {sid}",
        f"Iteration   : {iteration}",
        f"Phase       : {phase.upper()} ({'Build / Syntax' if phase == 'build' else 'Behavioral Simulation'})",
        f"Verdict     : {'PASS ✓' if passed else 'FAIL ✗'}",
        f"Return Code : {returncode}",
        f"Timed Out   : {timed_out}",
        f"Duration    : {elapsed_ms:.2f} ms",
        f"DUT Path    : {dut_path}",
        f"Top Module  : {top_module or 'unknown'}",
        f"Waveform    : {saved_vcd_path.name if saved_vcd_path else 'None'} ({vcd_size_bytes:,} bytes)",
    ]

    if signals:
        sig_names = ", ".join(s["name"] for s in signals)
        log_content.append(f"Signals ({len(signals)}): {sig_names}")

    log_content.extend([
        "",
        "─── DIAGNOSTIC SUMMARY ───────────────────────────────────────────────",
        error_summary,
        "",
        "─── SIMULATION STDOUT ────────────────────────────────────────────────",
        stdout.strip() or "(empty stdout)",
        "",
        "─── SIMULATION STDERR ────────────────────────────────────────────────",
        stderr.strip() or "(empty stderr)",
        "══════════════════════════════════════════════════════════════════════",
    ])

    iter_log_path.write_text("\n".join(log_content), encoding="utf-8")

    # 4. Update JSON history
    history_file = session_log_dir / "simulation_history.json"
    history = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
        except Exception:
            history = []

    history_entry = {
        "iteration": iteration,
        "timestamp": now_iso,
        "phase": phase,
        "passed": passed,
        "timed_out": timed_out,
        "returncode": returncode,
        "elapsed_ms": elapsed_ms,
        "error_summary": error_summary,
        "top_module": top_module,
        "log_file": str(iter_log_path.name),
        "vcd_file": str(saved_vcd_path.name) if saved_vcd_path else None,
        "vcd_size_bytes": vcd_size_bytes,
        "signals_captured": [s["name"] for s in signals],
    }
    history.append(history_entry)
    history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")

    return str(iter_log_path), (str(saved_vcd_path) if saved_vcd_path else None), error_summary


# ─── Top-Module Extractor ─────────────────────────────────────────────────────
def _strip_comments(code: str) -> str:
    """Strip single-line (//...) and multi-line (/*...*/) comments."""
    code_no_block = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    return re.sub(r'//[^\n]*', '', code_no_block)


def extract_tb_top_module(tb_code: str) -> Optional[str]:
    r"""
    Extract the testbench's top module name for verilator --top-module.

    Anchored to require the candidate identifier is immediately followed by
    '(' or ';' or '#' (allowing whitespace) -- this is what distinguishes a real
    `module foo (` / `module foo;` / `module foo #(` declaration from a comment
    that merely contains the word "module" followed by another word, e.g. "test the
    module directly with WIDTH=1", which a bare `module\s+(\w+)` pattern
    incorrectly matches.

    Prefers a `tb_`-prefixed module name over positional first/last
    heuristics -- testbenches generated by this pipeline are always required
    to use that prefix (see TESTBENCH_GENERATION_SYSTEM_PROMPT), so a prefix
    match is a far stronger signal than "which declaration appears first or last".
    """
    if not tb_code:
        return None

    clean_code = _strip_comments(tb_code)

    # 1. Prefer module name starting with tb_ (standard testbench convention)
    tb_match = re.search(r'\bmodule\s+(tb_\w+)\s*[(;#]', clean_code)
    if tb_match:
        return tb_match.group(1)

    # 2. Generic module declaration anchored by '(', ';', or '#'
    generic_match = re.search(r'\bmodule\s+(\w+)\s*[(;#]', clean_code)
    if generic_match:
        return generic_match.group(1)

    return None


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
    session_id: Optional[str] = None,
    iteration: int = 1,
) -> SimResult:
    """
    Compile DUT + testbench with verilator --binary, then execute the result.
    Saves simulation logs and VCD waveforms to logs/<session_id>/ for debugging.

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
    session_id : str, optional
        Unique session identifier for organizing persistent logs.
    iteration : int, default 1
        Verification loop iteration index.

    Returns
    -------
    SimResult
        .passed         — True iff the binary ran and stdout contains "PASS:"
        .phase          — "build" if verilator compile failed, "run" otherwise
        .stdout/.stderr — captured output
        .timed_out      — True if either phase hit the timeout
        .log_file_path  — Path to saved .log diagnostic file
        .vcd_file_path  — Path to saved .vcd waveform file
        .error_summary  — Diagnostic failure summary
    """
    if MOCK_MODE:
        return _mock_simulation(dut_path, tb_code, session_id=session_id, iteration=iteration)

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
        log_p, vcd_p, err_sum = _record_simulation_log(
            session_id=session_id,
            iteration=iteration,
            phase="build",
            passed=False,
            timed_out=False,
            returncode=-1,
            stdout="",
            stderr="[RTL-AGENT ERROR] Could not detect testbench top module name.",
            elapsed_ms=0.0,
            vcd_path=None,
            vcd_data=None,
            vcd_size_bytes=0,
            dut_path=dut_path,
            top_module=None,
        )
        return SimResult(
            passed=False,
            stdout="",
            stderr="[RTL-AGENT ERROR] Could not detect testbench top module name.",
            returncode=-1,
            timed_out=False,
            phase="build",
            elapsed_ms=0.0,
            error_file="tb_top.sv",
            log_file_path=log_p,
            vcd_file_path=vcd_p,
            error_summary=err_sum,
            iteration=iteration,
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
        "--trace",      # Enable VCD waveform tracing for $dumpfile / $dumpvars
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
        log_p, vcd_p, err_sum = _record_simulation_log(
            session_id=session_id,
            iteration=iteration,
            phase="build",
            passed=False,
            timed_out=True,
            returncode=-1,
            stdout=stdout_c,
            stderr=f"[RTL-AGENT ERROR] verilator --binary compile timed out after {timeout_s}s.",
            elapsed_ms=elapsed_build,
            vcd_path=None,
            vcd_data=None,
            vcd_size_bytes=0,
            dut_path=dut_path,
            top_module=top_module,
        )
        return SimResult(
            passed=False,
            stdout=stdout_c,
            stderr=f"[RTL-AGENT ERROR] verilator --binary compile timed out after {timeout_s}s.",
            returncode=-1,
            timed_out=True,
            phase="build",
            elapsed_ms=elapsed_build,
            error_file="tb_top.sv",
            log_file_path=log_p,
            vcd_file_path=vcd_p,
            error_summary=err_sum,
            iteration=iteration,
        )

    # String-based build pass/fail -- same rationale as verilator_tool.py.
    # Verilator may exit 1 for non-fatal warnings; %Error is the real signal.
    build_combined = stdout_c + stderr_c
    build_has_error = "%Error" in build_combined

    if build_has_error:
        # Determine whether the error mentions the testbench or the DUT.
        tb_basename = str(tb_path.name)   # e.g. "tb_top.sv"
        is_tb_err = (
            tb_basename in build_combined
            or "tb_" in build_combined
            or (top_module and top_module in build_combined)
            or "Cannot find file containing module" in build_combined
            or "top-module" in build_combined
        )
        error_file = tb_basename if is_tb_err else ""
        log_p, vcd_p, err_sum = _record_simulation_log(
            session_id=session_id,
            iteration=iteration,
            phase="build",
            passed=False,
            timed_out=False,
            returncode=rc_c,
            stdout=stdout_c,
            stderr=stderr_c,
            elapsed_ms=elapsed_build,
            vcd_path=None,
            vcd_data=None,
            vcd_size_bytes=0,
            dut_path=dut_path,
            top_module=top_module,
        )
        return SimResult(
            passed=False,
            stdout=stdout_c,
            stderr=stderr_c,
            returncode=rc_c,
            timed_out=False,
            phase="build",
            elapsed_ms=elapsed_build,
            error_file=error_file,
            log_file_path=log_p,
            vcd_file_path=vcd_p,
            error_summary=err_sum,
            iteration=iteration,
        )

    # ── Phase 2: Run ───────────────────────────────────────────────────────────
    # On Windows/WSL the binary is inside WSL — invoke via wsl
    if sys.platform == "win32":
        run_cmd = ["wsl", bin_p]
    else:
        run_cmd = [str(sim_binary)]

    stdout_r, stderr_r, rc_r, timed_out_r = _run_subprocess_with_timeout(
        run_cmd, timeout_s, cwd=str(workdir_path)
    )

    elapsed_total = (time.perf_counter() - t0) * 1000

    # VCD capture
    VCD_MAX_BYTES = 512 * 1024  # 512 KB hard cap
    vcd_path = workdir_path / "trace.vcd"
    vcd_data: Optional[str] = None
    vcd_size_bytes: int = 0

    if vcd_path.exists():
        vcd_size_bytes = vcd_path.stat().st_size
        if vcd_size_bytes <= VCD_MAX_BYTES:
            try:
                vcd_data = vcd_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                vcd_data = None
        else:
            import logging
            logging.warning(
                f"VCD file {vcd_path} is {vcd_size_bytes:,} bytes "
                f"(limit {VCD_MAX_BYTES:,}). Skipping SSE transfer. "
                f"Check testbench for missing $finish timeout."
            )

    if timed_out_r:
        log_p, vcd_p, err_sum = _record_simulation_log(
            session_id=session_id,
            iteration=iteration,
            phase="run",
            passed=False,
            timed_out=True,
            returncode=-1,
            stdout="FAIL: simulation timeout — binary exceeded wall-clock limit",
            stderr=stderr_r,
            elapsed_ms=elapsed_total,
            vcd_path=vcd_path if vcd_path.exists() else None,
            vcd_data=vcd_data,
            vcd_size_bytes=vcd_size_bytes,
            dut_path=dut_path,
            top_module=top_module,
        )
        return SimResult(
            passed=False,
            stdout="FAIL: simulation timeout — binary exceeded wall-clock limit",
            stderr=stderr_r,
            returncode=-1,
            timed_out=True,
            phase="run",
            elapsed_ms=elapsed_total,
            vcd_data=None,
            vcd_size_bytes=0,
            log_file_path=log_p,
            vcd_file_path=vcd_p,
            error_summary=err_sum,
            iteration=iteration,
        )

    # Primary pass/fail signal: testbench-emitted strings, not just exit code.
    # $fatal sets nonzero exit but we also want the human-readable message surfaced.
    combined = stdout_r + stderr_r
    passed = "PASS:" in combined and "FAIL:" not in combined

    # Record persistent simulation and waveform logs
    log_p, vcd_p, err_sum = _record_simulation_log(
        session_id=session_id,
        iteration=iteration,
        phase="run",
        passed=passed,
        timed_out=False,
        returncode=rc_r,
        stdout=stdout_r,
        stderr=stderr_r,
        elapsed_ms=elapsed_total,
        vcd_path=vcd_path if vcd_path.exists() else None,
        vcd_data=vcd_data,
        vcd_size_bytes=vcd_size_bytes,
        dut_path=dut_path,
        top_module=top_module,
    )

    return SimResult(
        passed=passed,
        stdout=stdout_r,
        stderr=stderr_r,
        returncode=rc_r,
        timed_out=False,
        phase="run",
        elapsed_ms=elapsed_total,
        vcd_data=vcd_data,
        vcd_size_bytes=vcd_size_bytes,
        log_file_path=log_p,
        vcd_file_path=vcd_p,
        error_summary=err_sum,
        iteration=iteration,
    )


# ─── Mock mode shim ─────────────────────────────────────────────────────────
def _mock_simulation(
    dut_path: str,
    tb_code: str,
    session_id: Optional[str] = None,
    iteration: int = 1,
) -> SimResult:
    """
    Short-circuit to canned SimResult objects when MOCK_MODE=true.
    Reads the mock scenario index from a module-level counter so
    successive calls in one mock session return the scripted sequence.
    Also records mock logs and waveform files for testing and tracing.
    """
    from tools.mock_responses import get_mock_sim_result
    res = get_mock_sim_result(dut_path, tb_code)

    top_mod = extract_tb_top_module(tb_code) or "tb_counter"
    log_p, vcd_p, err_sum = _record_simulation_log(
        session_id=session_id,
        iteration=iteration,
        phase=res.phase,
        passed=res.passed,
        timed_out=res.timed_out,
        returncode=res.returncode,
        stdout=res.stdout,
        stderr=res.stderr,
        elapsed_ms=res.elapsed_ms,
        vcd_path=None,
        vcd_data=res.vcd_data,
        vcd_size_bytes=res.vcd_size_bytes,
        dut_path=dut_path,
        top_module=top_mod,
    )
    res.log_file_path = log_p
    res.vcd_file_path = vcd_p
    res.error_summary = err_sum
    res.iteration = iteration
    return res
