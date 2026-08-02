import subprocess
import sys
from pathlib import Path

def run_verilator(filepath: str, timeout: int = 30) -> dict:
    sv_path = Path(filepath).resolve()

    _flags = [
        "--lint-only",
        "-Wall",
        "-Wno-style",
        "-Wno-fatal",
        "--timing",
    ]

    if sys.platform == "win32":
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
        
        # Log exact output to disk for debugging
        log_path = str(sv_path).replace(".sv", "_verilator.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"EXIT CODE: {result.returncode}\n")
            f.write("=== STDOUT ===\n")
            f.write(result.stdout if result.stdout else "No standard output.\n")
            f.write("\n=== STDERR ===\n")
            f.write(result.stderr if result.stderr else "No standard error.\n")

        combined_output = (result.stdout or "") + (result.stderr or "")
        is_success = "%Error" not in combined_output

        return {
            "success":    is_success,
            "stdout":     result.stdout,
            "stderr":     result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     "[RTL-AGENT ERROR] Verilator timed out.",
            "returncode": -1,
        }
    except FileNotFoundError:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     "[RTL-AGENT ERROR] Verilator executable not found.",
            "returncode": -2,
        }
    except Exception as exc:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     f"[RTL-AGENT ERROR] Unexpected error: {exc}",
            "returncode": -3,
        }

def filter_verilator_errors(raw_output: str) -> str:
    lines = (raw_output or "").splitlines()
    keep, capturing = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("%Error") or stripped.startswith("%Warning"):
            if "For warning description see" in stripped or 'Use "/* verilator lint_off' in stripped:
                capturing = False
                continue
            capturing = True
            keep.append(line)
        elif capturing and (line.startswith((" ", "\t")) or stripped.startswith(("...", "|"))):
            keep.append(line)  # continuation: note, source line, caret
        else:
            capturing = False

    if not keep:
        return raw_output
    
    error_count = sum(1 for l in keep if l.strip().startswith("%Error"))
    warning_count = sum(1 for l in keep if l.strip().startswith("%Warning"))
    return f"[Verilator: {error_count} error(s), {warning_count} warning(s)]\n" + "\n".join(keep)
