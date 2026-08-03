# RTL-Agent: Autonomous Multi-Agent Hardware Verification on AMD ROCm

<div align="center">

[![AMD ROCm](https://img.shields.io/badge/AMD_ROCm-6.1+-ED1C24?style=for-the-badge&logo=amd&logoColor=white)](https://rocm.docs.amd.com/)
[![vLLM Accelerated](https://img.shields.io/badge/vLLM-Prefix_Caching-00ADD8?style=for-the-badge&logo=fastapi&logoColor=white)](https://docs.vllm.ai/)
[![Model](https://img.shields.io/badge/LLM-Qwen2.5--Coder--7B-7C3AED?style=for-the-badge&logo=huggingface&logoColor=white)](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct)
[![Verilator](https://img.shields.io/badge/Simulator-Verilator_5.0+-22D3EE?style=for-the-badge&logo=cplusplus&logoColor=white)](https://www.veripool.org/verilator/)
[![Waveforms](https://img.shields.io/badge/Waveforms-VCD_➔_WaveDrom-10B981?style=for-the-badge&logo=svg&logoColor=white)](https://wavedrom.com/)
[![License](https://img.shields.io/badge/License-Apache_2.0-F59E0B?style=for-the-badge)](LICENSE)

**An autonomous, multi-agent AI system that designs, lints, simulates, extracts digital waveforms, and self-corrects synthesizable SystemVerilog hardware designs — powered by local LLMs accelerated on AMD ROCm.**

[Features](#-key-features) • [Architecture](#-multi-agent-architecture) • [AMD ROCm & vLLM](#-amd-rocm--vllm-acceleration) • [Quick Start](#-quick-start) • [Benchmark Suite](#-benchmark-results-88) • [UI & Waveforms](#-frontend-waveforms--telemetry)

</div>

---

## ⚡ The Silicon Verification Bottleneck

In modern VLSI and ASIC engineering, **functional verification is the single largest bottleneck**, consuming **over 70% of total engineering cycles and design budget**. A single undetected functional bug reaching tape-out can result in physical silicon respins costing **$50M–$100M+** and a 6-to-9 month market delay.

While generic AI coding assistants can generate syntactically plausible Verilog snippets, they fail in hardware engineering because they lack:
1. **Closed-loop EDA tooling feedback** (syntax linting & structural elaboration).
2. **Behavioral verification** (generating self-checking testbenches and executing functional simulation).
3. **Automated diagnosis & self-correction** (differentiating syntax errors from functional protocol mismatches).

**RTL-Agent solves this by establishing a fully autonomous, closed-loop 3-Agent verification pipeline with hardware-in-the-loop EDA simulation on AMD ROCm.**

---

## 🌟 Key Features

- 🤖 **3-Agent Specialized Pipeline**: Linear state machine featuring **Architect** (interface & verification strategy), **Coder** (RTL synthesis & lint self-healing), and **Verifier** (testbench generation & functional simulation).
- 🔬 **Two-Tier Verification Loop**:
  - **Tier 1 (Linting)**: Subprocess execution of `verilator --lint-only -Wall --timing` to eliminate syntax, width mismatch, and elaboration errors.
  - **Tier 2 (Functional Simulation)**: Native binary compilation (`verilator --binary`) executing self-checking testbenches with assertions and runtime pass/fail detection.
- 📈 **Real-Time Digital Waveform Viewer**: Testbenches automatically generate VCD (Value Change Dump) traces, parsed on-the-fly and rendered as interactive digital timing diagrams via **WaveDrom** and **D3.js**.
- 🚀 **AMD ROCm & vLLM High-Throughput Inference**:
  - Local GPU acceleration with ROCm 6.1 (Triton attention on Radeon RX 7900 series, ROCm FlashAttention on Instinct MI300X).
  - Prefix caching enabled for low-latency multi-turn agent corrections.
  - Real-time hardware telemetry streaming (TTFT, tokens/sec, throughput).
- 🛡️ **Zero External Agent Framework Overhead**: Pure Python asynchronous state machine with Server-Sent Events (SSE) streaming — no LangChain/AutoGen bloat.
- 🎯 **100% Benchmark Pass Rate**: Successfully generates, lints, and functionally verifies **8/8 complex hardware specifications**.

---

## 🏛️ Multi-Agent Architecture

```
                                  ┌──────────────────────────────────┐
                                  │   Natural Language RTL Spec      │
                                  └─────────────────┬────────────────┘
                                                    │
════════════════════════════════════════════════════╪════════════════════════════════════════════════════
 1. ARCHITECT AGENT                                 ▼
                                  ┌──────────────────────────────────┐
                                  │       Agent 1: Architect         │
                                  │  • Synthesizes Port Hierarchy    │
                                  │  • Defines Corner Cases          │
                                  │  • Creates Verification Plan     │
                                  └─────────────────┬────────────────┘
                                                    │ state["architect_plan"]
════════════════════════════════════════════════════╪════════════════════════════════════════════════════
 2. CODER AGENT (Tier 1 Lint)                       ▼
                        ┌──────────────────────────────────────────────────────────┐
                        │                 Agent 2: RTL Coder                       │
                        │        Generates Synthesizable SystemVerilog             │
                        └───────────────────────────┬──────────────────────────────┘
                                                    │
                                                    ▼
                                     verilator --lint-only -Wall
                                                    │
                                        ┌───────────┴───────────┐
                                        ▼                       ▼
                                     [ FAIL ]                [ PASS ]
                                        │                       │
                                        ▼                       ▼
                              Feed Error Diagnostics      state["rtl_code"]
                              LLM Self-Corrects (Max 3)
════════════════════════════════════════════════════╪════════════════════════════════════════════════════
 3. VERIFIER AGENT (Tier 2 Sim)                     │
                                                    ▼
                        ┌──────────────────────────────────────────────────────────┐
                        │                Agent 3: Verifier                         │
                        │ • Consumes Architect Plan + Clean RTL                    │
                        │ • Writes Self-Checking Testbench with VCD Dump           │
                        └───────────────────────────┬──────────────────────────────┘
                                                    │
                                                    ▼
                                       verilator --binary (Compile)
                                                    │
                                        ┌───────────┴───────────┐
                                        ▼                       ▼
                                  [ Build Fail ]            [ Build OK ]
                                        │                       │
                                        ▼                       ▼
                               Structural Fix Loop       Execute Sim Binary
                                                                │
                                                    ┌───────────┴───────────┐
                                                    ▼                       ▼
                                                [ FAIL ]                 [ PASS ]
                                                    │                       │
                                                    ▼                       ▼
                                         Behavioral Diagnosis        Extract VCD Waveform
                                         Self-Correction Loop        Render WaveDrom UI
                                                    │                       │
                                                    └───────────────────────┼────────┐
                                                                            │        │
════════════════════════════════════════════════════════════════════════════╪════════╪═══════════════════
 4. VERIFIED SILICON OUTPUT                                                 ▼        ▼
                                                                     Verified SV  Waveforms
```

### Agent Roles and Responsibilities

| Agent | Core Objective | Inputs | Tools & Verification | Outputs |
|---|---|---|---|---|
| **Architect** | High-level system engineering, port definition, reset strategy, and test planning | User Natural Language Spec | Structural decomposition prompt | `architect_plan` (markdown specification & test strategy) |
| **Coder** | Synthesizable RTL design & static quality assurance | User Spec + `architect_plan` | `verilator --lint-only -Wall --timing` | Clean SystemVerilog DUT (`rtl_code`) |
| **Verifier** | Dynamic verification, self-checking stimulus, waveform dumping | `architect_plan` + Clean `rtl_code` | `verilator --binary` + Simulation runner + VCD Parser | Self-checking Testbench (`tb_code`), VCD traces, Pass/Fail status |

---

## 🚀 AMD ROCm & vLLM Acceleration

RTL-Agent is designed specifically for **on-premise / edge AMD hardware execution** without relying on external cloud APIs:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      AMD ROCm Hardware Stack                             │
├────────────────────────────────┬─────────────────────────────────────────┤
│  AMD Instinct (MI300X / MI250) │  AMD Radeon (RX 7900 XTX / 7900 GRE)    │
│  Backend: ROCM_FLASH Attention │  Backend: TRITON_ATTN (Triton ROCm)     │
├────────────────────────────────┴─────────────────────────────────────────┤
│  vLLM Inference Engine (v0.5.0+) with PagedAttention & KV Prefix Caching │
├──────────────────────────────────────────────────────────────────────────┤
│  Model: Qwen/Qwen2.5-Coder-7B-Instruct (FP16 / AWQ Quantized)            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Performance Optimizations
1. **Automatic Attention Backend Selection**:
   - `scripts/vllm_launch.sh` auto-detects Instinct vs. Radeon GPU architectures, dynamically setting `VLLM_ATTENTION_BACKEND=ROCM_FLASH` or `VLLM_ATTENTION_BACKEND=TRITON_ATTN`.
2. **KV-Cache Prefix Caching (`--enable-prefix-caching`)**:
   - Because the system prompt, architect plan, and previous iteration attempts share identical prefixes, KV-cache reuse reduces Time-To-First-Token (TTFT) by up to **65%** across multi-turn correction loops.
3. **Real-Time Hardware Telemetry Stream**:
   - SSE streams live TTFT, tokens-per-second, total generated tokens, and end-to-end execution wall-clock time directly to the dashboard.

---

## 💻 Quick Start

### 1. Instant Mock Demo (Zero GPU / Zero API Keys Required)

You can run and evaluate the full multi-agent pipeline and UI instantly out of the box:

```bash
# Clone and enter directory
git clone https://github.com/your-username/rtl_agent.git
cd rtl_agent

# Install lightweight dependencies
pip install -r requirements.txt

# Launch agent server (runs in mock mode by default)
python agent_server.py
```
Open **`http://localhost:7860`** in your browser.

---

### 2. Live Local GPU Mode (AMD ROCm + vLLM)

For deployment on AMD ROCm workstations or AMD Developer Cloud instances:

```bash
# Step 1: Pre-flight system check (Verilator 5.0+, ROCm, Python)
chmod +x scripts/check_env.sh && ./scripts/check_env.sh

# Step 2: Install dependencies & Verilator
pip install -r requirements.txt
sudo apt-get update && sudo apt-get install -y verilator build-essential

# Step 3: Launch optimized vLLM server on AMD ROCm
chmod +x scripts/vllm_launch.sh
./scripts/vllm_launch.sh fp16-optimized

# Step 4: Run RTL-Agent with local vLLM backend
export DEPLOY_MODE=vllm
export MODEL_NAME=Qwen/Qwen2.5-Coder-7B-Instruct
python agent_server.py
```

---

### 3. Cloud API Mode (DeepSeek-Coder Dev Mode)

For rapid development and prompt experimentation without local GPU resources:

```bash
export DEPLOY_MODE=deepseek
export DEEPSEEK_API_KEY="sk-your-deepseek-api-key"
python agent_server.py
```

---

## 📊 Benchmark Results (8/8)

RTL-Agent was evaluated against an 8-module comprehensive benchmark suite spanning arithmetic, sequential pipelines, storage queues, protocol transmitters, and finite state machines:

| # | Benchmark Module | Architectural Complexity | Tier 1 (Lint) | Tier 2 (Sim) | Waveform Generated | Benchmark Status |
|---|---|---|:---:|:---:|:---:|:---:|
| 1 | **4-bit Sync Counter** | Active-high enable, synchronous reset, overflow flag | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` | **PASSED (100%)** |
| 2 | **8-bit Shift Register** | Parallel load, bidirectional serial shift, serial out | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` | **PASSED (100%)** |
| 3 | **2-to-1 Multiplexer** | Parameterized data bus width (32-bit default) | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` | **PASSED (100%)** |
| 4 | **Traffic Light FSM** | Configurable phase timers, emergency override | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` | **PASSED (100%)** |
| 5 | **Synchronous FIFO** | Parameterized depth/width, full, empty, occupancy counter | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` | **PASSED (100%)** |
| 6 | **UART Transmitter** | 115200 baud generator, 8N1 framing, busy signaling | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` | **PASSED (100%)** |
| 7 | **32-bit ALU** | 10 Operations (Arithmetic, Logical, Shifts, SLT), Flags | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` | **PASSED (100%)** |
| 8 | **Priority Encoder** | 8-to-3 priority encoding, valid output flag | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` | **PASSED (100%)** |

### Run Benchmark Suite

```bash
# Execute automated benchmark suite with time-budget protection
python benchmark/run_benchmark.py --time-budget-minutes 50

# Run AMD ROCm prefix-caching optimization benchmark
python benchmark/rocm_bench.py --config prefix-cache --runs 3
```

---

## 🖥️ Frontend, Waveforms & Telemetry

The RTL-Agent user interface is a dark glassmorphism engineering cockpit designed for VLSI designers:

1. **3-Agent Pipeline Tracker**: Real-time status pills (`[Architect] ➔ [Coder] ➔ [Verifier]`) showing active thinking, lint status, and simulation completion.
2. **Interactive WaveDrom Waveform Viewer**: Live SVG timing diagrams parsed directly from simulation VCD traces with signal-by-signal clock transitions.
3. **VCD Download**: Export raw `.vcd` files for detailed debugging in GTKWave / ModelSim.
4. **AMD ROCm Telemetry Widget**: Live display of generation TTFT, token throughput, total context tokens, and simulation elapsed time.
5. **Code Version Diff & Inspector**: SystemVerilog syntax highlighting with tabbed iteration history and download buttons.

---

## 📁 Repository Structure

```
rtl_agent/
├── agent.py                  # Linear 3-Agent State Machine & SSE Yield Loop
├── agent_server.py           # FastAPI Server, REST API & SSE Streaming Endpoints
├── config.py                 # Configuration Loader (DEPLOY_MODE, ROCm, Timeouts)
├── prompts.py                # Specialized Prompts for Architect, Coder, and Verifier
├── requirements.txt          # Minimal Python dependencies
├── tools/
│   ├── verilator_tool.py     # Subprocess wrapper for Tier 1 Verilator linting
│   ├── simulator_tool.py     # Subprocess wrapper for Tier 2 native binary simulation
│   ├── sv_parser.py          # SystemVerilog code extractor & block parser
│   └── mock_responses.py     # Pre-scripted responses for zero-dependency demo mode
├── frontend/
│   ├── index.html            # 3-Panel responsive UI with Pipeline Tracker
│   ├── app.js                # SSE Event dispatcher, WaveDrom & Telemetry controller
│   └── style.css             # Glassmorphism dark theme & animations
├── benchmark/
│   ├── specs.json            # 8 Target RTL specifications
│   ├── run_benchmark.py      # Automated benchmark harness
│   └── rocm_bench.py         # ROCm prefix-cache benchmarking utility
└── scripts/
    ├── check_env.sh          # Pre-flight environment & toolchain validation
    └── vllm_launch.sh        # ROCm-optimized vLLM startup script
```

---

## 🏆 Hackathon Alignment (Track 2: AI Agents)

| Evaluation Criterion | Implementation in RTL-Agent |
|---|---|
| **Autonomous Multi-Agent Workflow** | Linear state machine coordinating **Architect**, **Coder**, and **Verifier** with structured handoffs. |
| **Real-World Tool Integration** | Subprocess invocation of industry-standard EDA tools: **Verilator** (`--lint-only` & `--binary`), **g++**, and VCD waveform extractors. |
| **Self-Correction & Reasoning** | Distinct prompt strategies routing syntax bugs to structural repair and assertion failures to behavioral self-correction. |
| **Local AMD ROCm Acceleration** | Native deployment on AMD GPUs with vLLM, prefix caching, and real-time hardware telemetry. |
| **Silicon Reliability & Impact** | Catches non-synthesizable constructs, elaboration errors, and behavioral corner-case bugs before hardware synthesis. |

---

<div align="center">

**Built for the AMD AI DevMaster Hackathon · August 2026**

</div>
