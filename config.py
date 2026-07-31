"""
config.py — Central configuration for the RTL Verification Agent.

═══════════════════════════════════════════════════════════════
 DEPLOYMENT MODES (single env var switch)
═══════════════════════════════════════════════════════════════

 DEPLOY_MODE  │ What it does
 ─────────────┼───────────────────────────────────────────────
 "mock"       │ No LLM, no GPU. Pre-scripted demo responses.
              │ For UI development, frontend testing, and
              │ benchmark harness rehearsal.
 ─────────────┼───────────────────────────────────────────────
 "amd-api"    │ Free AMD Developer API (Qwen/Qwen2.5-Coder-7B-Instruct).
              │ Zero credits. Full two-tier agent loop with
              │ a 35B model. For local dev and real testing
              │ before cloud deployment.
 ─────────────┼───────────────────────────────────────────────
 "vllm"       │ Dedicated vLLM on AMD ROCm (vLLM-Qwen3).
              │ Local GPU inference. For the final hackathon
              │ submission — proves AMD hardware acceleration.
 ─────────────┼───────────────────────────────────────────────

 Switch with:
   set DEPLOY_MODE=mock         # Windows
   export DEPLOY_MODE=amd-api   # Linux

ROCm/vLLM optimization knobs (40-point rubric bucket):
  ENABLE_PREFIX_CACHING  — caches KV blocks for shared prefixes across iterations.
  GPU_MEMORY_UTILIZATION — fraction of VRAM allocated to KV cache (0.0-1.0).
  MAX_NUM_SEQS           — concurrent sequences vLLM can handle (throughput tuning).
  QUANTIZATION           — '' (fp16), 'awq' (int4 AWQ), or 'gptq' (GPTQ int4/int8).
  VLLM_DTYPE             — model weight dtype: 'float16', 'bfloat16', or 'auto'.
  TENSOR_PARALLEL_SIZE   — number of GPUs for tensor parallelism (1 for single GPU).
"""

import os
from pathlib import Path

# ─── Deployment Mode ──────────────────────────────────────────────────────────
# The single switch that controls everything: LLM endpoint, model, API key.
# "mock" = pre-scripted (no LLM)  |  "amd-api" = free AMD API  |  "vllm" = local GPU
DEPLOY_MODE: str = os.getenv("DEPLOY_MODE", "mock").lower().strip()

# Backward compat: MOCK_MODE=true → deploy_mode="mock"
if os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes"):
    DEPLOY_MODE = "mock"
elif os.getenv("MOCK_MODE", "").lower() in ("false", "0", "no"):
    if DEPLOY_MODE == "mock":
        DEPLOY_MODE = "amd-api"  # default real mode is the free API

MOCK_MODE: bool = (DEPLOY_MODE == "mock")

# ─── AMD Developer API Endpoints ─────────────────────────────────────────────
# Free public API: zero credits, 35B model, no GPU required locally.
# Dedicated API: runs on AMD cloud GPU, required for Track 2 points.
_AMD_API_ENDPOINTS = {
    # Phase 1: Free public API (Qwen/Qwen2.5-Coder-7B-Instruct, DeepSeek-V4-Flash)
    "amd-api": {
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "model":    "Qwen/Qwen2.5-Coder-7B-Instruct",
        "api_key":  os.getenv("AMD_API_KEY", ""),  # paste from AMD dev portal
    },
    # Fallback: DeepSeek on AMD free API (elite coding, if Qwen throttled)
    "amd-deepseek": {
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "model":    "DeepSeek-V4-Flash",
        "api_key":  os.getenv("AMD_API_KEY", ""),
    },
    # Phase 2: Dedicated vLLM on AMD ROCm hardware (final submission)
    "vllm": {
        "base_url": os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
        "model":    os.getenv("MODEL_NAME", "vLLM-Qwen3"),
        "api_key":  os.getenv("VLLM_API_KEY", "token-rtl-agent"),
    },
}

# ─── Resolve active endpoint ─────────────────────────────────────────────────
def _resolve_endpoint():
    """Pick the right endpoint config based on DEPLOY_MODE."""
    if DEPLOY_MODE in _AMD_API_ENDPOINTS:
        ep = _AMD_API_ENDPOINTS[DEPLOY_MODE]
        return ep["base_url"], ep["api_key"], ep["model"]

    # Direct override via env vars (backward compat)
    return (
        os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
        os.getenv("VLLM_API_KEY", "token-rtl-agent"),
        os.getenv("MODEL_NAME", "Qwen/Qwen2.5-Coder-7B-Instruct"),
    )


VLLM_BASE_URL, VLLM_API_KEY, MODEL_NAME = _resolve_endpoint()

# Allow explicit overrides to win over mode defaults
if os.getenv("VLLM_BASE_URL"):
    VLLM_BASE_URL = os.getenv("VLLM_BASE_URL")
if os.getenv("VLLM_API_KEY"):
    VLLM_API_KEY = os.getenv("VLLM_API_KEY")
if os.getenv("MODEL_NAME"):
    MODEL_NAME = os.getenv("MODEL_NAME")

MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "4096"))
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.05"))  # Near-zero for deterministic code

# ─── Agent Configuration ──────────────────────────────────────────────────────
MAX_LINT_ITERATIONS: int = int(os.getenv("MAX_LINT_ITERATIONS", "3"))
MAX_FUNCTIONAL_ITERATIONS: int = int(os.getenv("MAX_FUNCTIONAL_ITERATIONS", "3"))
MAX_TOTAL_ITERATIONS: int = int(os.getenv("MAX_TOTAL_ITERATIONS", "6"))

# Legacy alias for backward compatibility
MAX_ITERATIONS: int = MAX_LINT_ITERATIONS

VERILATOR_TIMEOUT: int = int(os.getenv("VERILATOR_TIMEOUT", "30"))
SIMULATION_TIMEOUT: int = int(os.getenv("SIMULATION_TIMEOUT", "30"))

# ─── AMD ROCm / vLLM Optimization Settings ───────────────────────────────────
ENABLE_PREFIX_CACHING: bool = os.getenv("ENABLE_PREFIX_CACHING", "true").lower() in ("true", "1", "yes")
GPU_MEMORY_UTILIZATION: float = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.90"))
MAX_NUM_SEQS: int = int(os.getenv("MAX_NUM_SEQS", "64"))
QUANTIZATION: str = os.getenv("QUANTIZATION", "")
VLLM_DTYPE: str = os.getenv("VLLM_DTYPE", "float16")
TENSOR_PARALLEL_SIZE: int = int(os.getenv("TENSOR_PARALLEL_SIZE", "1"))

# ─── Server Configuration ────────────────────────────────────────────────────
SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "7860"))

# ─── Filesystem ──────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).parent
WORKSPACE_DIR: Path = BASE_DIR / "workspace"
FRONTEND_DIR: Path = BASE_DIR / "frontend"
WORKSPACE_DIR.mkdir(exist_ok=True)

# ─── Startup banner helper ────────────────────────────────────────────────────
def print_config():
    """Print resolved configuration for debugging."""
    mode_labels = {
        "mock":         "MOCK (demo, no LLM)",
        "amd-api":      "AMD FREE API (Qwen/Qwen2.5-Coder-7B-Instruct, zero credits)",
        "amd-deepseek": "AMD FREE API (DeepSeek-V4-Flash, zero credits)",
        "vllm":         "DEDICATED vLLM on AMD ROCm (local GPU)",
    }
    label = mode_labels.get(DEPLOY_MODE, f"CUSTOM ({DEPLOY_MODE})")
    print("=" * 68)
    print("  RTL Verification Agent v2 — Two-Tier Verification Loop")
    print(f"  Deploy : {label}")
    print(f"  Model  : {MODEL_NAME}")
    if not MOCK_MODE:
        print(f"  API URL: {VLLM_BASE_URL}")
        print(f"  API Key: {'***' + VLLM_API_KEY[-4:] if len(VLLM_API_KEY) > 6 else '(set)'}")
    print(f"  Limits : Lint={MAX_LINT_ITERATIONS} / Sim={MAX_FUNCTIONAL_ITERATIONS} / Total={MAX_TOTAL_ITERATIONS}")
    if DEPLOY_MODE == "vllm":
        print(f"  ROCm   : prefix_cache={ENABLE_PREFIX_CACHING} gpu_mem={GPU_MEMORY_UTILIZATION} seqs={MAX_NUM_SEQS}")
        if QUANTIZATION:
            print(f"  Quant  : {QUANTIZATION}")
    print("=" * 68)
