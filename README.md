# RTL-Agent v2 — Autonomous Two-Tier RTL Verification

> An agentic AI system that generates, lints, simulates, and self-corrects SystemVerilog hardware designs — powered by local LLMs on AMD ROCm hardware via vLLM.

---

## Problem Statement

Hardware verification is widely understood to be the dominant cost and schedule sink in the RTL-to-GDS design cycle — consuming a disproportionate share of engineering effort in every VLSI project. Current AI coding assistants can write syntactically plausible SystemVerilog, but they leave the entire verification loop — finding bugs, diagnosing them, and correcting the design — entirely to the human engineer. **RTL-Agent closes that loop autonomously.**

> **[Citation needed]** The often-quoted "60–70% of design effort goes to verification" figure is widely cited in EDA conference papers and industry surveys; we have not independently verified a specific source for this document and flag it as an industry-common claim requiring a primary citation before publication.

---

## What It Does (v2)

1. **You** describe a hardware module in plain English
2. **Tier 1 (Lint):** The agent generates expert-level SystemVerilog and runs `verilator --lint-only`. If errors are found, the full error log is fed back to the LLM as a structured correction prompt — the LLM rewrites the code and retries. Loop repeats until clean or the lint iteration limit is hit.
3. **Tier 2 (Functional Simulation):** Once Tier 1 passes, the agent generates a **self-checking testbench** and compiles + runs it with `verilator --binary`. The testbench emits `PASS:` / `FAIL:` strings. If the simulation fails:
   - A **behavioral bug** (wrong reset polarity, off-by-one, etc.) → fed back via `FUNCTIONAL_CORRECTION_PROMPT` — the model is told *why* it's a behavioral mismatch, not a syntax error
   - A **structural elaboration bug** (caught by `--binary` but not `--lint-only`) → routed to the existing Tier 1 correction prompt since it's the same class of error
4. **Loop stops** when both tiers pass, or when the global `MAX_TOTAL_ITERATIONS` ceiling is hit — reported honestly (no silent failure claims)
5. **You** download a synthesis-ready `.sv` file

---

## Two-Tier Verification Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Natural-Language Spec                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 1 — Syntax / Lint                                     │
│                                                             │
│  LLM generates SV module                                    │
│         │                                                   │
│         ▼                                                   │
│  verilator --lint-only --Wall --timing                      │
│         │                                                   │
│     ────┴────                                               │
│    │         │                                              │
│  PASS      FAIL → correction prompt → LLM rewrites → loop  │
│    │                                                        │
└────┼───────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 2 — Functional Simulation                             │
│                                                             │
│  LLM generates self-checking testbench (SV)                 │
│         │                                                   │
│         ▼                                                   │
│  verilator --binary (compile DUT + TB → native binary)      │
│         │                                                   │
│    ─────┴─────                                              │
│   │    BUILD    │                                           │
│  OK   FAIL ──→ structural bug → Tier 1 correction → loop   │
│   │                                                         │
│   ▼                                                         │
│  Execute binary; parse PASS:/FAIL: in stdout                │
│         │                                                   │
│    ─────┴─────                                              │
│   │           │                                             │
│  PASS       FAIL → behavioral bug → functional correction   │
│   │                     prompt → LLM rewrites DUT → loop   │
│   │                                                         │
└───┼─────────────────────────────────────────────────────────┘
    │
    ▼
 final_result { lint_status, functional_status, total_iterations }
```

**Key invariants:**
- `MAX_TOTAL_ITERATIONS` (default 6) is a hard ceiling on combined LLM calls per design
- Behavioral correction prompts are distinct from structural ones — the LLM is told *which kind* of bug it hit
- The full conversation history is shared across both tiers (the model remembers every prior attempt)

---

## Project Structure

```
rtl_agent/
├── agent.py              ← Two-tier agentic loop (mock / AMD API / vLLM)
├── agent_server.py       ← FastAPI server + SSE streaming (v2)
├── config.py             ← DEPLOY_MODE switch + all env-var config
├── prompts.py            ← Expert RTL + testbench + functional-correction prompts
├── tools/
│   ├── verilator_tool.py ← Subprocess wrapper for verilator --lint-only
│   ├── simulator_tool.py ← Two-phase sim tool (build + run, process-group kill)
│   ├── sv_parser.py      ← Robust SystemVerilog extractor from LLM output
│   └── mock_responses.py ← Pre-scripted demo scenarios (Tier 1 + Tier 2)
├── frontend/
│   ├── index.html        ← Three-panel UI with two-tier verification section
│   ├── style.css         ← Premium dark glassmorphism design
│   └── app.js            ← SSE consumer, deploy mode badge, TTFT telemetry
├── benchmark/
│   ├── specs.json        ← 8 RTL benchmark specifications
│   ├── run_benchmark.py  ← Crash-safe benchmark harness (Am. 5)
│   ├── rocm_bench.py     ← ROCm optimization comparison (prefix cache / quantization)
│   ├── results.json      ← Generated: per-spec results
│   └── results.md        ← Generated: human-readable results table
├── scripts/
│   ├── check_env.sh      ← Pre-flight env check (verilator ≥5.x, g++, Python)
│   └── vllm_launch.sh    ← Optimized vLLM launch (4 modes: fp16/optimized/AWQ/GPTQ)
├── workspace/            ← Generated .sv files (auto-created)
└── README.md
```

---

## Quick Start

### Mode 1: Mock Demo (zero dependencies)

```bash
pip install -r requirements.txt
python agent_server.py   # DEPLOY_MODE=mock by default
# → http://localhost:7860
```

The mock demo runs the full two-tier loop with pre-scripted responses:
- **Tier 1:** counter fails with a missing-semicolon → LLM fixes it → lint passes
- **Tier 2:** the "clean" counter has an *async* reset (passes lint) but the spec requires *sync* → testbench catches it → LLM corrects it → simulation passes

---

### Mode 2: AMD Free API (Qwen3.6-35B-A3B, zero credits)

Use the AMD Developer Platform's free public API for real LLM testing without any GPU:

```bash
# 1. Get your API key from https://developer.amd.com.cn (AMD AI Developer Program)
# 2. Set environment variables:
export DEPLOY_MODE=amd-api
export AMD_API_KEY=your-key-here

# 3. Start the agent
python agent_server.py
```

**Windows (PowerShell):**
```powershell
$env:DEPLOY_MODE = "amd-api"
$env:AMD_API_KEY = "your-key-here"
python agent_server.py
```

This uses the **Qwen3.6-35B-A3B** model (35B params, strong at RTL/SV, strict formatting compliance). If the Qwen endpoint is throttled, switch to DeepSeek:

```bash
export DEPLOY_MODE=amd-deepseek   # uses DeepSeek-V4-Flash on same API
```

---

### Mode 3: Dedicated vLLM on AMD ROCm (Final Submission)

For the hackathon submission — proves local GPU inference on AMD hardware:

```bash
# Step 0: Pre-flight environment check
chmod +x scripts/check_env.sh && ./scripts/check_env.sh

# Step 1: Install system dependencies
pip install -r requirements.txt
sudo apt-get install -y verilator build-essential

# Step 2: Launch vLLM with optimizations
chmod +x scripts/vllm_launch.sh
./scripts/vllm_launch.sh fp16-optimized   # prefix caching + tuned KV cache

# Step 3: Start RTL-Agent in vLLM mode
export DEPLOY_MODE=vllm
export MODEL_NAME=vLLM-Qwen3
python agent_server.py

# Step 4: Run benchmark with time budget
python benchmark/run_benchmark.py --time-budget-minutes 55

# Step 5: Run ROCm optimization comparison
python benchmark/rocm_bench.py --config prefix-cache --runs 3
```

> **Verilator version note:** `verilator --binary` mode (required for Tier 2) was stabilized in **Verilator 5.000**. The `check_env.sh` script verifies this. If your AMD cloud instance ships with an older verilator, build from source or use a recent Ubuntu image.

---

## Model Strategy

| Phase | Model | Endpoint | Why |
|---|---|---|---|
| **Local Dev** | `Qwen3.6-35B-A3B` | AMD Free API | 35B params. Deep enough to parse raw Verilator STDERR and map failures to specific SV lines. Strict formatting compliance (no filler text). Zero credits. |
| **Fallback** | `DeepSeek-V4-Flash` | AMD Free API | Elite coding capabilities, same free endpoint. Use if Qwen is throttled. |
| **Submission** | `vLLM-Qwen3` | Local vLLM on ROCm | Proves AMD hardware acceleration. `MiniCPM5-1B` is too small — will hallucinate hardware syntax. |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DEPLOY_MODE` | `mock` | **Primary switch**: `mock` / `amd-api` / `amd-deepseek` / `vllm` |
| `AMD_API_KEY` | *(empty)* | API key from AMD Developer Portal (for `amd-api` mode) |
| `MOCK_MODE` | *(auto)* | Legacy: `true` → `DEPLOY_MODE=mock`, `false` → `DEPLOY_MODE=amd-api` |
| `VLLM_BASE_URL` | *(auto)* | Override: explicit endpoint URL (wins over `DEPLOY_MODE` default) |
| `VLLM_API_KEY` | `token-rtl-agent` | vLLM API key (any non-empty string for local vLLM) |
| `MODEL_NAME` | *(auto)* | Override: explicit model name (wins over `DEPLOY_MODE` default) |
| `MAX_LINT_ITERATIONS` | `3` | Max Tier 1 (lint) self-correction loops |
| `MAX_FUNCTIONAL_ITERATIONS` | `3` | Max Tier 2 (simulation) self-correction loops |
| `MAX_TOTAL_ITERATIONS` | `6` | **Hard ceiling** on combined LLM calls per design |
| `MAX_TOKENS` | `4096` | LLM max output tokens |
| `TEMPERATURE` | `0.05` | Near-zero for deterministic code |
| `VERILATOR_TIMEOUT` | `30` | Lint subprocess timeout (s) |
| `SIMULATION_TIMEOUT` | `30` | Simulation compile + run timeout (s) |
| `ENABLE_PREFIX_CACHING` | `true` | vLLM prefix caching (ROCm optimization) |
| `GPU_MEMORY_UTILIZATION` | `0.90` | Fraction of GPU VRAM for KV cache |
| `MAX_NUM_SEQS` | `64` | vLLM concurrent sequence limit |
| `QUANTIZATION` | *(empty)* | `awq` or `gptq` for int4 quantization |
| `SERVER_PORT` | `7860` | FastAPI port |

---

## Benchmark Results

> **[Placeholder]** The table below will be populated by running `python benchmark/run_benchmark.py` against the live AMD/vLLM endpoint during the hackathon GPU window. The numbers below are illustrative and MUST be replaced with actual results from `benchmark/results.md` before submission.

| # | Spec | Lint | Simulation | Lint Iters | Sim Iters | Total Iters | Wall (s) | Tok/s |
|---|------|------|-----------|-----------|----------|-------------|----------|-------|
| 1 | 4-bit Sync Counter | — | — | — | — | — | — | — |
| 2 | 8-bit Shift Register | — | — | — | — | — | — | — |
| 3 | 2-to-1 Mux | — | — | — | — | — | — | — |
| 4 | Traffic Light FSM | — | — | — | — | — | — | — |
| 5 | Synchronous FIFO | — | — | — | — | — | — | — |
| 6 | UART Transmitter | — | — | — | — | — | — | — |
| 7 | 4-bit ALU | — | — | — | — | — | — | — |
| 8 | Priority Encoder | — | — | — | — | — | — | — |

---

## Judging Criteria Mapping (AMD AI DevMaster — Track 2)

| Criterion | Where it's demonstrated |
|---|---|
| **Agentic reasoning** | `agent.py` two-tier correction loop; distinct correction prompts for structural vs behavioral bugs; Amendment 2 phase routing |
| **Tool execution** | `tools/verilator_tool.py` (`--lint-only`), `tools/simulator_tool.py` (`--binary`) — real subprocess calls to EDA tooling |
| **Autonomous iteration** | SSE `lint_iteration` / `sim_iteration` / `sim_build_error` events, visible in frontend tabs; global iteration counter `MAX_TOTAL_ITERATIONS` bounds cost |
| **Local AMD/ROCm hardware deployment** | `MOCK_MODE=false` + vLLM launch command; `benchmark/results.md` timings from live run show actual tok/s on AMD GPU |
| **Correctness signal beyond compilation** | Tier 2 catches behavioral bugs (e.g. async vs sync reset) that `--lint-only` cannot — this is the core novelty vs a simple code-generation tool |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/run` | Start agent with `{"spec": "..."}` |
| `GET` | `/api/stream/{session_id}` | SSE stream of all agent events |
| `GET` | `/api/sessions` | List all sessions with lint/sim status |
| `GET` | `/api/download/{sid}/{filename}` | Download generated `.sv` file |
| `GET` | `/api/config` | Runtime config (mode, model, iteration limits) |
| `GET` | `/health` | Health check |

### SSE Event Types (v2)

| Event | Key fields | Description |
|---|---|---|
| `agent_start` | `max_lint/functional/total_iterations` | Session started |
| `lint_iteration` | `iteration, total_iterations, passed, phase` | Each lint loop step |
| `testbench_generated` | `code, filename, elapsed_ms` | Tier 2 testbench ready |
| `sim_iteration` | `iteration, passed, phase, sim_stdout, elapsed_ms` | Functional sim result |
| `sim_build_error` | `sim_stderr, phase="build"` | verilator --binary compile failed (structural) |
| `final_result` | `lint_status, functional_status, total_iterations` | Canonical completion event |
| `code_generated` | `code, filename, lines, tier, tokens_generated` | DUT code version |
| `llm_done` | `elapsed_ms, tokens_generated` | LLM call telemetry (Am. 8) |

---

## Mock Mode — Demo Scenarios

All scenarios work with `MOCK_MODE=true` and zero API key:

| Keyword | Module | Tier 1 bug | Tier 2 bug |
|---|---|---|---|
| `counter`, `count` | 4-bit counter | Missing semicolon in `always_ff` | **Async reset** when spec requires sync (passes lint, fails simulation) |
| `fifo`, `queue` | Sync FIFO | `reg` instead of `logic` | *(passes Tier 2)* |
| `alu`, `arithmetic` | 32-bit ALU | Missing semicolon in `case` | *(passes Tier 2)* |
| `uart`, `serial` | UART TX | Missing `begin/end` after `else` | *(passes Tier 2)* |
| `fsm`, `traffic` | Traffic FSM | Blocking `=` inside `always_ff` | *(passes Tier 2)* |

The **counter** is the showcase scenario for judges: it demonstrates a bug that Tier 1 (lint) cannot catch but Tier 2 (simulation) can — the central claim of the two-tier approach.

---

## Known Limitations

> These are stated honestly so judges can evaluate the system fairly, and so Q&A questions can be pre-empted.

1. **LLM-generated testbenches are not formally verified.** The testbench itself could contain bugs (wrong expected values, incomplete coverage). The system proves that the DUT satisfies its own generated testbench, not a formally specified one. Production verification requires human-written or formally derived properties.

2. **`MAX_TOTAL_ITERATIONS` means some designs may not fully converge.** If a design requires more corrections than the ceiling allows, `final_result` reports `functional_status: FAILED` honestly rather than claiming success. This is intentional.

3. **Simulation timeout is a heuristic, not a liveness proof.** The 30-second wall-clock timeout prevents runaway simulations but is not a formal termination guarantee. Designs with very long pipelines or complex FSMs may require a higher `SIMULATION_TIMEOUT`.

4. **Functional testbenches test specific cases, not full coverage.** The agent generates ≥3 stimulus cases per the prompt, but combinatorial coverage, edge cases, and corner cases are not guaranteed. This is appropriate for a proof-of-concept agent but not for tape-out-grade verification.

5. **verilator --binary requires g++ and verilator ≥5.x.** If these are unavailable, Tier 2 silently reports `functional_status: NOT_RUN`. The `check_env.sh` script surfaces this before GPU time is spent.

---

## Track 2 Compliance (AMD ROCm Optimization)

- ✅ **Local LLM execution**: Qwen2.5-Coder-7B via vLLM on AMD Radeon
- ✅ **No OpenAI cloud API**: Uses vLLM's OpenAI-compatible endpoint on `localhost`
- ✅ **Multi-tool use**: `subprocess` → `verilator --lint-only` (Tier 1) + `verilator --binary` (Tier 2)
- ✅ **State management**: Rolling conversation history across both tiers (Amendment 6)
- ✅ **Bounded autonomy**: `MAX_TOTAL_ITERATIONS` ceiling prevents runaway GPU spend (Amendment 1)
- ✅ **Crash-safe benchmark**: Incremental writes, time-budget guard (Amendment 5)
- ✅ **Telemetry**: `tokens_generated` / `elapsed_ms` per LLM call → tok/s on AMD hardware (Amendment 8)
- ✅ **End-to-end functional**: Spec → SV → lint → simulate → functional correction → verified download
