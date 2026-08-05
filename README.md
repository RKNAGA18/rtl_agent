# RTL-Agent: Autonomous Multi-Agent Hardware Verification on AMD ROCm

<div align="center">

[![AMD ROCm](https://img.shields.io/badge/AMD_ROCm-6.1+-ED1C24?style=for-the-badge&logo=amd&logoColor=white)](https://rocm.docs.amd.com/)
[![vLLM Accelerated](https://img.shields.io/badge/vLLM-Prefix_Caching-00ADD8?style=for-the-badge&logo=fastapi&logoColor=white)](https://docs.vllm.ai/)
[![Model](https://img.shields.io/badge/LLM-DeepSeek--V4--Flash-7C3AED?style=for-the-badge&logo=huggingface&logoColor=white)](https://huggingface.co/)
[![Verilator](https://img.shields.io/badge/Simulator-Verilator_5.0+-22D3EE?style=for-the-badge&logo=cplusplus&logoColor=white)](https://www.veripool.org/verilator/)
[![Waveforms](https://img.shields.io/badge/Waveforms-VCD_➔_WaveDrom-10B981?style=for-the-badge&logo=svg&logoColor=white)](https://wavedrom.com/)
[![License](https://img.shields.io/badge/License-Apache_2.0-F59E0B?style=for-the-badge)](LICENSE)

**An autonomous, multi-agent AI system that designs, lints, simulates, extracts digital waveforms, and self-corrects synthesizable SystemVerilog hardware designs — powered by local LLMs accelerated on AMD ROCm.**

[Features](#-key-features) • [Architecture](#-multi-agent-architecture) • [AMD ROCm Acceleration](#-amd-rocm--vllm-acceleration) • [Quick Start](#-quick-start) • [Benchmarks](#-benchmark-results)

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

*   🤖 **3-Agent Specialized Pipeline**: Linear state machine featuring **Architect** (interface & verification strategy), **Coder** (RTL synthesis & lint self-healing), and **Verifier** (testbench generation & functional simulation).
*   🔬 **Two-Tier Verification Loop**:
    *   **Tier 1 (Linting)**: Subprocess execution of `verilator --lint-only -Wall --timing` to eliminate syntax, width mismatch, and elaboration errors.
    *   **Tier 2 (Functional Simulation)**: Native binary compilation (`verilator --binary`) executing self-checking testbenches with "Soft Fail" error accumulators.
*   📈 **Real-Time Digital Waveform Viewer**: Testbenches automatically generate VCD (Value Change Dump) traces, parsed on-the-fly and rendered as interactive digital timing diagrams via **WaveDrom**.
*   🚀 **AMD ROCm & High-Throughput Inference**:
    *   Local GPU acceleration with ROCm 6.1 leveraging Triton attention on Radeon.
    *   Real-time hardware telemetry streaming (TTFT, tokens/sec, throughput).
*   🛡️ **Zero Framework Overhead**: Pure Python asynchronous state machine with Server-Sent Events (SSE) streaming — no LangChain/AutoGen bloat.

---

## 🏛️ Multi-Agent Architecture

```mermaid
graph TD
    %% Styling
    classDef user fill:#2d3748,stroke:#4a5568,stroke-width:2px,color:#fff
    classDef agent fill:#2b6cb0,stroke:#63b3ed,stroke-width:2px,color:#fff
    classDef engine fill:#c53030,stroke:#fc8181,stroke-width:2px,color:#fff
    classDef backend fill:#276749,stroke:#68d391,stroke-width:2px,color:#fff
    classDef pass fill:#38a169,stroke:#9ae6b4,stroke-width:2px,color:#fff

    %% Nodes
    User([User Natural Language RTL Spec]) ::: user
    AMD[(AMD Radeon ROCm API<br>DeepSeek-V4-Flash)] ::: backend
    
    subgraph RTL-Agent Pipeline
        Arch[Architect Agent<br>Micro-Arch & Test Plan] ::: agent
        Coder[Coder Agent<br>SystemVerilog DUT] ::: agent
        Verif[Verifier Agent<br>Soft-Fail Testbench] ::: agent
    end

    subgraph Verilator Verification Engine
        Tier1{Tier 1: Linting<br>Syntax Check} ::: engine
        Tier2{Tier 2: Simulation<br>C++ VCD Trace} ::: engine
        Reflect[Dual-Perspective<br>Reflection Engine] ::: engine
    end
    
    Success(((Verified SV &<br>WaveDrom UI))) ::: pass

    %% Connections
    User --> Arch
    Arch --> Coder
    Coder --> Tier1
    
    Tier1 -->|FAIL: Diagnostics| Coder
    Tier1 -->|PASS| Verif
    
    Verif --> Tier2
    Tier2 -->|FAIL: Behavioral Diagnostics| Reflect
    
    Reflect -.->|Fix DUT| Coder
    Reflect -.->|Fix Testbench| Verif
    
    Tier2 -->|PASS| Success

    %% AMD Backend Links
    Arch -.->|API Calls| AMD
    Coder -.->|API Calls| AMD
    Verif -.->|API Calls| AMD
```

### Agent Roles and Responsibilities

| Agent | Core Objective | Verification Tooling | Outputs |
| --- | --- | --- | --- |
| **Architect** | High-level system engineering, port definition, reset strategy, and test planning. | *None (Planning Phase)* | `architect_plan` (markdown specification & strategy) |
| **Coder** | Synthesizable RTL design & static quality assurance. | `verilator --lint-only -Wall` | Clean SystemVerilog DUT (`rtl_code`) |
| **Verifier** | Dynamic verification, self-checking stimulus, waveform dumping. | `verilator --binary` + VCD Parser | Self-checking Testbench (`tb_code`), VCD traces |

---

## 🚀 AMD ROCm Acceleration

RTL-Agent is designed specifically for **AMD hardware execution**, fully utilizing the ROCm stack for high-throughput EDA workflows.

### Performance Optimizations

1. **Radeon API Backend**: Utilizes the AMD developer API for DeepSeek-V4-Flash inference.
2. **KV-Cache Prefix Caching**: Because the system prompt, architect plan, and previous iteration attempts share identical prefixes, KV-cache reuse heavily reduces Time-To-First-Token (TTFT) across multi-turn correction loops.
3. **Real-Time Hardware Telemetry Stream**: SSE streams live TTFT, tokens-per-second, and total generated tokens directly to the dashboard alongside the verification results.

---

## 💻 Quick Start

### Prerequisites

* Ubuntu/Debian-based Linux environment (or WSL2)
* Python 3.10+
* `verilator` (v5.0+ recommended)
* Node.js (for Localtunnel UI exposure)

### Installation & Execution

```bash
# 1. Clone the repository
git clone https://github.com/your-username/rtl_agent.git
cd rtl_agent

# 2. Install dependencies & Verilator
apt-get update && apt-get install -y verilator build-essential nodejs npm
pip install -r requirements.txt

# 3. Export AMD API Credentials
export VLLM_BASE_URL="https://developer.amd.com.cn/radeon/api/v1"
export MODEL_NAME="DeepSeek-V4-Flash" 
export VLLM_API_KEY="your-api-key-here"
export DEPLOY_MODE="amd-api"

# 4. Launch the Agent Server in the background
python agent_server.py > agent_server.log 2>&1 &
sleep 4

# 5. Expose the UI via Localtunnel
npx --yes localtunnel --port 7860
```

---

## 📊 Benchmark Results

RTL-Agent was evaluated against a comprehensive benchmark suite spanning arithmetic, sequential pipelines, multiplexing, and finite state machines, achieving a **100% Pass Rate on Tier 1 (Syntactical Linting)** natively against Verilator's strict C++ ruleset.

| Benchmark Module | Architectural Complexity | Tier 1 (Lint) | Tier 2 (Sim) | Waveform Generated |
| --- | --- | --- | --- | --- |
| **4-bit Sync Counter** | Active-high enable, synchronous reset, overflow flag | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` |
| **8-bit Shift Register** | Parallel load, bidirectional serial shift, serial out | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` |
| **2-to-1 Multiplexer** | Parameterized data bus width (32-bit default) | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` |
| **Traffic Light FSM** | Configurable phase timers, emergency override | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` |
| **4-bit ALU** | 8 Operations (ADD, SUB, AND, OR, XOR, NOT), Flags | ✅ PASSED | ✅ PASSED | ✅ `trace.vcd` |

### Run Benchmark Suite

```bash
# Execute the full automated benchmark suite
python benchmark/run_benchmark.py
```

---

## 🖥️ Frontend, Waveforms & Telemetry

The RTL-Agent user interface is an engineering cockpit designed for VLSI designers:

1. **3-Agent Pipeline Tracker**: Real-time status pills showing active thinking, lint status, and simulation completion.
2. **Interactive WaveDrom Waveform Viewer**: Live SVG timing diagrams parsed directly from simulation VCD traces with signal-by-signal clock transitions.
3. **AMD ROCm Telemetry Widget**: Live display of generation TTFT, token throughput, total context tokens, and simulation elapsed time.
4. **Code Inspector**: SystemVerilog syntax highlighting with tabbed iteration history and download buttons.

---

## 🏆 Hackathon Alignment (Track 2: AI Agents)

| Evaluation Criterion | Implementation in RTL-Agent |
| --- | --- |
| **Autonomous Multi-Agent Workflow** | Linear state machine coordinating **Architect**, **Coder**, and **Verifier** with structured handoffs. |
| **Real-World Tool Integration** | Subprocess invocation of industry-standard EDA tools: **Verilator** (`--lint-only` & `--binary`), **g++**, and VCD extractors. |
| **Self-Correction & Reasoning** | Dual-Perspective router dynamically toggles between repairing DUT syntax and fixing flawed testbench assertions. |
| **AMD Acceleration** | Fully powered by the AMD Radeon API leveraging DeepSeek-V4-Flash for complex hardware synthesis. |
| **Silicon Reliability & Impact** | Catches non-synthesizable constructs, elaboration errors, and behavioral corner-case bugs before tape-out. |
