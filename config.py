"""
config.py — Central configuration for the RTL Verification Agent.

═══════════════════════════════════════════════════════════════
 DEPLOYMENT MODES (single env var switch)
═══════════════════════════════════════════════════════════════

 DEPLOY_MODE  │ LLM Endpoint                          │ Notes
 ─────────────┼───────────────────────────────────────┼──────────────────────
 "mock"       │ None (pre-scripted)                   │ Zero deps, demo
 ─────────────┼───────────────────────────────────────┼──────────────────────
 "deepseek"   │ DeepSeek API (api.deepseek.com)       │ RECOMMENDED for local
              │ Model: deepseek-coder                 │ dev. Real LLM, cheap,
              │ Key:   DEEPSEEK_API_KEY               │ fully documented API.
 ─────────────┼───────────────────────────────────────┼──────────────────────
 "amd-api"    │ AMD Developer Portal API              │ ⚠ UNVERIFIED: confirm
              │ Model: Qwen3.6-35B-A3B                │ the portal actually
              │ Key:   AMD_API_KEY                    │ provides a hosted
              │ URL:   developer.amd.com.cn/radeon/.. │ inference API before
              │                                       │ using this mode.
 ─────────────┼───────────────────────────────────────┼──────────────────────
 "amd-deepseek"│ AMD Portal, DeepSeek-V4-Flash model  │ ⚠ Same caveat as above
 ─────────────┼───────────────────────────────────────┼──────────────────────
 "vllm"       │ Local vLLM on AMD ROCm                │ FINAL SUBMISSION.
              │ Model: vLLM-Qwen3 (or MODEL_NAME)     │ Proves local GPU
              │ URL:   localhost:8000/v1               │ inference on AMD hw.
 ─────────────┼───────────────────────────────────────┼──────────────────────

 Switch:
   export DEPLOY_MODE=deepseek   # Linux/Mac
   $env:DEPLOY_MODE="deepseek"   # PowerShell

 IMPORTANT — read before using DEPLOY_MODE=vllm on AMD cloud:
   Always set DEPLOY_MODE=vllm explicitly on the AMD instance.
   Do NOT rely on MOCK_MODE=false auto-promotion (which defaults to
   "deepseek", not "vllm") — if you forget to set DEPLOY_MODE=vllm,
   your "ROCm optimization" benchmark numbers would actually come from
   a remote API, not local GPU inference, undermining the 40-pt rubric.

ROCm/vLLM optimization knobs (40-point rubric bucket):
  ENABLE_PREFIX_CACHING  — caches KV blocks for shared prefixes.
  GPU_MEMORY_UTILIZATION — fraction of VRAM for KV cache (0.0-1.0).
  MAX_NUM_SEQS           — concurrent sequences (throughput tuning).
  QUANTIZATION           — '' (fp16), 'awq' (int4 AWQ), 'gptq' (GPTQ int4/int8).
  VLLM_DTYPE             — 'float16' (safe for all ROCm targets), 'bfloat16', 'auto'.
  TENSOR_PARALLEL_SIZE   — GPUs for tensor parallelism (1 for single GPU).
"""

import os
import sys
from pathlib import Path

# ─── Deployment Mode ──────────────────────────────────────────────────────────
DEPLOY_MODE: str = os.getenv("DEPLOY_MODE", "mock").lower().strip()

# Backward compat: MOCK_MODE=true → "mock",  MOCK_MODE=false → "deepseek"
# NOTE: MOCK_MODE=false promotes to "deepseek" (verified real API), NOT "amd-api"
# (unverified). Set DEPLOY_MODE=vllm explicitly on AMD cloud — never rely on auto.
_mock_env = os.getenv("MOCK_MODE", "").lower()
if _mock_env in ("true", "1", "yes"):
    DEPLOY_MODE = "mock"
elif _mock_env in ("false", "0", "no") and DEPLOY_MODE == "mock":
    DEPLOY_MODE = "deepseek"

MOCK_MODE: bool = (DEPLOY_MODE == "mock")

# ─── API Endpoint Definitions ─────────────────────────────────────────────────
_ENDPOINTS = {
    # ── Recommended for local dev: DeepSeek Coder ─────────────────────────────
    # Real, documented, inexpensive API. DeepSeek-coder is elite at RTL.
    # Get key at: https://platform.deepseek.com/api_keys
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model":    "deepseek-coder",
        "api_key":  os.getenv("DEEPSEEK_API_KEY", ""),
    },

    # ── AMD Developer Portal API (unverified — confirm before use) ─────────────
    # AMD's hackathon compute access works via $100 AMD Developer Cloud credits
    # for self-hosted vLLM on MI300X instances — it may NOT be a standing managed
    # inference API with a portal-issued key. Verify at:
    # https://www.amd.com/en/developer/resources/rocm-hub/ai-devmaster.html
    "amd-api": {
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "model":    "Qwen3.6-35B-A3B",
        "api_key":  os.getenv("AMD_API_KEY", ""),
    },
    "amd-deepseek": {
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "model":    "DeepSeek-V4-Flash",
        "api_key":  os.getenv("AMD_API_KEY", ""),
    },

    # ── Local vLLM on AMD ROCm (final submission) ─────────────────────────────
    # Must set DEPLOY_MODE=vllm explicitly on the AMD cloud instance.
    "vllm": {
        "base_url": os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
        "model":    os.getenv("MODEL_NAME", "vLLM-Qwen3"),
        "api_key":  os.getenv("VLLM_API_KEY", "token-rtl-agent"),
    },
}


def _resolve_endpoint():
    """Pick endpoint config based on DEPLOY_MODE, with env-var overrides."""
    if DEPLOY_MODE in _ENDPOINTS:
        ep = _ENDPOINTS[DEPLOY_MODE]
        base_url = ep["base_url"]
        api_key  = ep["api_key"]
        model    = ep["model"]
    else:
        # Unknown mode: fall back to direct env vars
        base_url = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
        api_key  = os.getenv("VLLM_API_KEY",  "token-rtl-agent")
        model    = os.getenv("MODEL_NAME",     "Qwen/Qwen2.5-Coder-7B-Instruct")

    # Explicit env vars always win over mode defaults
    if os.getenv("VLLM_BASE_URL"):
        base_url = os.getenv("VLLM_BASE_URL")
    if os.getenv("VLLM_API_KEY"):
        api_key  = os.getenv("VLLM_API_KEY")
    if os.getenv("MODEL_NAME"):
        model    = os.getenv("MODEL_NAME")

    # Key-specific overrides (highest priority)
    if DEPLOY_MODE == "deepseek" and os.getenv("DEEPSEEK_API_KEY"):
        api_key = os.getenv("DEEPSEEK_API_KEY")
    if DEPLOY_MODE in ("amd-api", "amd-deepseek") and os.getenv("AMD_API_KEY"):
        api_key = os.getenv("AMD_API_KEY")

    return base_url, api_key, model


VLLM_BASE_URL, VLLM_API_KEY, MODEL_NAME = _resolve_endpoint()

MAX_TOKENS:   int   = int(os.getenv("MAX_TOKENS",   "4096"))
TEMPERATURE:  float = float(os.getenv("TEMPERATURE", "0.05"))  # near-zero for deterministic RTL

# ─── Agent Iteration Limits ───────────────────────────────────────────────────
MAX_LINT_ITERATIONS:         int = int(os.getenv("MAX_LINT_ITERATIONS",         "3"))
MAX_FUNCTIONAL_ITERATIONS:   int = int(os.getenv("MAX_FUNCTIONAL_ITERATIONS",   "3"))
MAX_TOTAL_ITERATIONS:        int = int(os.getenv("MAX_TOTAL_ITERATIONS",        "6"))
MAX_ITERATIONS:              int = MAX_LINT_ITERATIONS  # backward-compat alias

VERILATOR_TIMEOUT:  int = int(os.getenv("VERILATOR_TIMEOUT",  "30"))
SIMULATION_TIMEOUT: int = int(os.getenv("SIMULATION_TIMEOUT", "30"))

# ─── AMD ROCm / vLLM Optimization Settings ───────────────────────────────────
ENABLE_PREFIX_CACHING:   bool  = os.getenv("ENABLE_PREFIX_CACHING",   "true").lower() in ("true", "1", "yes")
GPU_MEMORY_UTILIZATION:  float = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.90"))
MAX_NUM_SEQS:            int   = int(os.getenv("MAX_NUM_SEQS",         "64"))
QUANTIZATION:            str   = os.getenv("QUANTIZATION", "")
VLLM_DTYPE:              str   = os.getenv("VLLM_DTYPE", "float16")
TENSOR_PARALLEL_SIZE:    int   = int(os.getenv("TENSOR_PARALLEL_SIZE", "1"))

# ─── Server ───────────────────────────────────────────────────────────────────
SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "7860"))

# ─── Filesystem ──────────────────────────────────────────────────────────────
BASE_DIR:      Path = Path(__file__).parent
WORKSPACE_DIR: Path = BASE_DIR / "workspace"
FRONTEND_DIR:  Path = BASE_DIR / "frontend"
WORKSPACE_DIR.mkdir(exist_ok=True)


# ─── Runtime Warnings ─────────────────────────────────────────────────────────
def _emit_warnings():
    """Emit warnings for configurations that could silently produce wrong results."""
    if DEPLOY_MODE in ("amd-api", "amd-deepseek") and not VLLM_API_KEY:
        print(
            "\n[RTL-AGENT WARNING] DEPLOY_MODE=amd-api but AMD_API_KEY is not set.\n"
            "  Verify that the AMD Developer Portal provides a hosted inference API\n"
            "  before trying this mode. If it doesn't, use DEPLOY_MODE=deepseek instead.\n"
            "  AMD hackathon compute: https://www.amd.com/en/developer/resources/rocm-hub/ai-devmaster.html\n",
            file=sys.stderr,
        )
    if DEPLOY_MODE == "deepseek" and not VLLM_API_KEY:
        print(
            "\n[RTL-AGENT WARNING] DEPLOY_MODE=deepseek but DEEPSEEK_API_KEY is not set.\n"
            "  Get a key at: https://platform.deepseek.com/api_keys\n",
            file=sys.stderr,
        )
    if DEPLOY_MODE == "vllm" and "localhost" not in VLLM_BASE_URL and "127.0.0.1" not in VLLM_BASE_URL:
        print(
            f"\n[RTL-AGENT WARNING] DEPLOY_MODE=vllm but VLLM_BASE_URL={VLLM_BASE_URL!r} "
            "is not a localhost address.\n"
            "  For the 40-pt ROCm criterion, vLLM must run locally on the AMD GPU instance.\n"
            "  If benchmarking remotely, your TTFT numbers won't reflect local GPU inference.\n",
            file=sys.stderr,
        )


# ─── Startup Banner ───────────────────────────────────────────────────────────
def print_config():
    """Print resolved configuration at startup."""
    _emit_warnings()

    mode_labels = {
        "mock":         "MOCK (demo, no LLM)",
        "deepseek":     "DeepSeek API · deepseek-coder (recommended for dev)",
        "amd-api":      "AMD Portal API · Qwen3.6-35B-A3B  ⚠ verify endpoint first",
        "amd-deepseek": "AMD Portal API · DeepSeek-V4-Flash  ⚠ verify endpoint first",
        "vllm":         "LOCAL vLLM on AMD ROCm (final submission)",
    }
    label = mode_labels.get(DEPLOY_MODE, f"CUSTOM ({DEPLOY_MODE})")

    key_display = "—"
    if not MOCK_MODE and VLLM_API_KEY:
        key_display = "***" + VLLM_API_KEY[-4:] if len(VLLM_API_KEY) > 6 else "(set)"

    print("=" * 68)
    print("  RTL Verification Agent v2 — Two-Tier Verification Loop")
    print(f"  Deploy : {label}")
    print(f"  Model  : {MODEL_NAME}")
    if not MOCK_MODE:
        print(f"  URL    : {VLLM_BASE_URL}")
        print(f"  Key    : {key_display}")
    print(f"  Limits : Lint={MAX_LINT_ITERATIONS} / Sim={MAX_FUNCTIONAL_ITERATIONS} / Total={MAX_TOTAL_ITERATIONS}")
    if DEPLOY_MODE == "vllm":
        print(f"  ROCm   : prefix_cache={ENABLE_PREFIX_CACHING}  gpu_mem={GPU_MEMORY_UTILIZATION}  seqs={MAX_NUM_SEQS}")
        if QUANTIZATION:
            print(f"  Quant  : {QUANTIZATION}")
    print("=" * 68)
