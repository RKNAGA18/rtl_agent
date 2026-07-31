/**
 * app.js — RTL Verification Agent v2 Frontend
 *
 * New in v2:
 *  • Two-tier verification: Tier 1 (lint) + Tier 2 (functional simulation)
 *  • Handles new SSE events: lint_iteration, testbench_generated,
 *    sim_iteration, sim_build_error, final_result
 *  • Global iteration progress bar across both tiers
 *  • Functional verification panel with per-iteration sim cards
 *  • Testbench viewer (collapsible) with copy/download
 *  • PASS / FAIL / PARTIAL result badges
 *  • Telemetry display (elapsed ms, tokens/sec) from Amendment 8
 */

'use strict';

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  currentSession: null,
  sseSource: null,
  streamingEl: null,
  iterations: [],         // DUT code versions [{code, filename, lines, iteration, status}]
  activeIterTab: 0,
  config: null,
  tbCode: null,           // current testbench code
  tbFilename: null,       // testbench .sv filename
  simIterations: [],      // [{iteration, passed, stdout, stderr, phase}]
  totalIterations: 0,
  maxTotal: 6,
};

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const specInput      = $('spec-input');
const runBtn         = $('run-btn');
const feedEl         = $('feed');
const feedEmptyEl    = $('feed-empty');
const historyEl      = $('history-list');
const codeViewer     = $('code-viewer');
const codePlaceholder = $('code-placeholder');
const iterTabs       = $('iter-tabs');
const veriStatusBar  = $('veri-status-bar');
const codeActionBar  = $('code-action-bar');
const toastContainer = $('toast-container');
const modeBadge      = $('mode-badge');
const copyBtn        = $('copy-btn');
const downloadBtn    = $('download-btn');
const linesEl        = $('code-lines');
const tier1Pill      = $('tier1-pill');
const tier2Pill      = $('tier2-pill');
const badgeTier1     = $('badge-tier1');
const badgeTier2     = $('badge-tier2');
const globalIterBar  = $('global-iter-bar');
const globalIterLabel = $('global-iter-label');
const simIterationsEl = $('sim-iterations');
const tbSection      = $('tb-section');
const tbViewer       = $('tb-viewer');
const simEmptyState  = $('sim-empty-state');

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  await loadConfig();
  await loadHistory();

  runBtn.addEventListener('click', handleRun);
  specInput.addEventListener('keydown', e => {
    if (e.ctrlKey && e.key === 'Enter') handleRun();
  });

  copyBtn.addEventListener('click', handleCopy);
  downloadBtn.addEventListener('click', handleDownload);

  document.querySelectorAll('.example-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      specInput.value = chip.dataset.spec;
      specInput.focus();
    });
  });
}

// ─── Config ──────────────────────────────────────────────────────────────────
async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    state.config = await res.json();
    state.maxTotal = state.config.max_total_iterations || 6;
    if (modeBadge) {
      const dm = state.config.deploy_mode || (state.config.mock_mode ? 'mock' : 'vllm');
      const labels = {
        'mock':         'MOCK MODE',
        'amd-api':      'AMD API · ' + (state.config.model || 'Qwen3.6-35B-A3B'),
        'amd-deepseek': 'AMD API · DeepSeek-V4',
        'vllm':         'LIVE · AMD ROCm vLLM',
      };
      modeBadge.textContent = labels[dm] || ('LIVE · ' + dm);
      modeBadge.className = 'mode-badge ' + (dm === 'mock' ? 'mock' : 'real');
    }
  } catch (_) {}
}

// ─── Run Handler ──────────────────────────────────────────────────────────────
async function handleRun() {
  const spec = specInput.value.trim();
  if (!spec) {
    toast('Please enter a hardware specification.', 'error');
    specInput.focus();
    return;
  }
  if (state.sseSource) {
    state.sseSource.close();
    state.sseSource = null;
  }

  // Reset all state
  clearFeed();
  clearCodeViewer();
  clearFunctionalPanel();
  state.iterations = [];
  state.currentSession = null;
  state.streamingEl = null;
  state.tbCode = null;
  state.tbFilename = null;
  state.simIterations = [];
  state.totalIterations = 0;

  setRunning(true);

  let sessionId;
  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec }),
    });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    sessionId = data.session_id;
    state.currentSession = sessionId;
  } catch (err) {
    toast(`Failed to start agent: ${err.message}`, 'error');
    setRunning(false);
    return;
  }

  connectSSE(sessionId);
}

// ─── SSE Connection ───────────────────────────────────────────────────────────
function connectSSE(sessionId) {
  const es = new EventSource(`/api/stream/${sessionId}`);
  state.sseSource = es;

  es.onmessage = e => {
    try {
      const event = JSON.parse(e.data);
      handleEvent(event);
    } catch (_) {}
  };

  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) return;
    es.close();
    setRunning(false);
  };
}

// ─── Event Dispatcher ─────────────────────────────────────────────────────────
function handleEvent(ev) {
  // Update global total iteration counter in every relevant event
  if (ev.total_iterations !== undefined) {
    state.totalIterations = ev.total_iterations;
    updateGlobalBar(ev.total_iterations, ev.max_total || state.maxTotal);
  }

  switch (ev.type) {
    case 'connected':
      break;

    case 'agent_start':
      state.maxTotal = ev.max_total_iterations || 6;
      addFeedEvent('iteration', '🚀', 'AGENT STARTED',
        `Model: ${ev.model} · Lint≤${ev.max_lint_iterations} · Sim≤${ev.max_functional_iterations} · Total≤${ev.max_total_iterations}`,
        'iteration');
      initGlobalBar(ev.max_total_iterations);
      setTierBadge('tier1', 'running');
      break;

    case 'lint_iteration':
      if (ev.phase === 'tier1_lint') {
        addIterDivider(`Lint Iter ${ev.iteration} · Total ${ev.total_iterations}/${ev.max_total}`);
      } else if (ev.phase === 'tier1_lint_result') {
        // handled by tool_result below
      } else if (ev.phase === 'tier2_relint') {
        addFeedEvent('tool', '🔄', 'RE-LINT (Tier 2 fix)',
          ev.passed ? 'Re-lint passed — proceeding to re-simulation' : 'Re-lint FAILED after functional fix',
          ev.passed ? 'success' : 'error');
      }
      break;

    case 'thought':
      addFeedEvent('thought', '🧠', 'THINKING', ev.message, 'thought');
      break;

    case 'llm_start':
      startLLMStream();
      break;

    case 'llm_token':
      appendLLMToken(ev.token);
      break;

    case 'llm_done':
      endLLMStream(ev.elapsed_ms, ev.tokens_generated, ev.ttft_ms, ev.tokens_per_sec);
      break;

    case 'code_generated': {
      const tier = ev.tier || 'tier1';
      const idx = state.iterations.length;
      state.iterations.push({
        code: ev.code,
        filename: ev.filename,
        lines: ev.lines,
        iteration: ev.iteration || ev.total_iterations,
        status: 'pending',
        tier,
      });
      addIterTab(ev.iteration || ev.total_iterations, 'pending', tier);
      showCodeVersion(idx);
      const telemetry = ev.elapsed_ms
        ? ` · ${(ev.elapsed_ms / 1000).toFixed(1)}s · ${ev.tokens_generated || '?'} tokens`
        : '';
      addFeedEvent('code', '📄', 'RTL GENERATED',
        `${tier === 'tier2_correction' ? '[Tier 2 fix] ' : ''}SystemVerilog extracted · ${ev.lines} lines · ${ev.filename}${telemetry}`,
        'code');
      break;
    }

    case 'tool_call':
      setVeriStatus('running');
      addFeedEvent('tool', '⚙️', 'TOOL CALL',
        `Executing: verilator --lint-only --Wall --timing ${ev.file}`,
        'tool');
      break;

    case 'tool_result': {
      const lastIdx = state.iterations.length - 1;
      if (ev.success) {
        setVeriStatus('pass');
        setTierPill('tier1', 'pass');
        if (lastIdx >= 0) state.iterations[lastIdx].status = 'clean';
        updateIterTabStatus(lastIdx, 'clean');
        const feedEl2 = addFeedEvent('tool', '✅', 'VERILATOR PASS', '', 'success');
        addVeriOutput(feedEl2, ev.stdout || '0 errors, 0 warnings', true);
      } else {
        setVeriStatus('fail');
        if (lastIdx >= 0) state.iterations[lastIdx].status = 'error';
        updateIterTabStatus(lastIdx, 'error');
        const feedEl2 = addFeedEvent('tool', '⚠️', 'VERILATOR ERRORS', '', 'error');
        addVeriOutput(feedEl2, ev.stderr || ev.stdout || 'Unknown error', false);
        codeViewer.classList.add('shake');
        setTimeout(() => codeViewer.classList.remove('shake'), 500);
      }
      break;
    }

    // ── v2 Tier 2 events ──────────────────────────────────────────────────
    case 'testbench_generated': {
      state.tbCode = ev.code;
      state.tbFilename = ev.filename;
      renderTestbench(ev.code, ev.filename);
      setTierBadge('tier2', 'running');
      setTierPill('tier2', 'running');
      const tbTelemetry = ev.elapsed_ms
        ? ` · ${(ev.elapsed_ms / 1000).toFixed(1)}s · ${ev.tokens_generated || '?'} tokens`
        : '';
      addFeedEvent('code', '🧪', 'TESTBENCH GENERATED',
        `Self-checking testbench written · ${ev.filename}${tbTelemetry}`,
        'code');
      break;
    }

    case 'sim_build_error': {
      // Amendment 2: structural bug in --binary compile — distinct event
      addSimIterCard({
        iteration: ev.iteration,
        passed: false,
        phase: 'build',
        stdout: ev.sim_stdout,
        stderr: ev.sim_stderr,
        timed_out: ev.timed_out,
        elapsed_ms: ev.elapsed_ms,
        label: '🔨 BUILD ERROR (structural)',
      });
      addFeedEvent('error', '🔨', 'SIM BUILD FAILED',
        `verilator --binary compile error (structural bug). Routing to Tier 1 correction.\n${(ev.sim_stderr || '').slice(0, 160)}`,
        'error');
      break;
    }

    case 'sim_iteration': {
      state.simIterations.push(ev);
      addSimIterCard({
        iteration: ev.iteration,
        passed: ev.passed,
        phase: ev.phase || 'run',
        stdout: ev.sim_stdout,
        stderr: ev.sim_stderr,
        timed_out: ev.timed_out,
        elapsed_ms: ev.elapsed_ms,
        label: ev.passed ? '✅ SIMULATION PASS' : '❌ SIMULATION FAIL',
      });
      if (ev.passed) {
        setTierPill('tier2', 'pass');
        setTierBadge('tier2', 'pass');
      } else {
        setTierPill('tier2', 'fail');
      }
      addFeedEvent(
        ev.passed ? 'success' : 'error',
        ev.passed ? '✅' : '❌',
        ev.passed ? 'SIMULATION PASS' : 'SIMULATION FAIL',
        ev.passed
          ? `Testbench reported: PASS: all checks passed · ${(ev.elapsed_ms / 1000).toFixed(2)}s`
          : `Testbench reported: ${(ev.sim_stdout || '').split('\n')[0].slice(0, 120)}`,
        ev.passed ? 'success' : 'error'
      );
      break;
    }

    case 'final_result': {
      const lintOk  = ev.lint_status === 'PASSED';
      const simOk   = ev.functional_status === 'PASSED';
      const bothOk  = lintOk && simOk;
      const partial = lintOk && !simOk && ev.functional_status !== 'NOT_RUN';

      setTierPill('tier1', lintOk ? 'pass' : 'fail');
      setTierBadge('tier1', lintOk ? 'pass' : 'fail');
      setTierPill('tier2', simOk ? 'pass' : (ev.functional_status === 'NOT_RUN' ? 'idle' : 'fail'));
      setTierBadge('tier2', simOk ? 'pass' : (ev.functional_status === 'NOT_RUN' ? 'idle' : 'fail'));

      const resultClass = bothOk ? 'success' : partial ? 'warning' : 'error';
      const resultIcon  = bothOk ? '🎉' : partial ? '⚠️' : '❌';
      const resultLabel = bothOk ? 'FULLY VERIFIED' : partial ? 'PARTIAL RESULT' : 'VERIFICATION FAILED';

      addFeedEvent(resultClass, resultIcon, resultLabel,
        `Lint: ${ev.lint_status} · Sim: ${ev.functional_status} · ${ev.total_iterations} total iteration(s)`,
        resultClass);

      if (bothOk) {
        toast(`✓ Both tiers PASSED in ${ev.total_iterations} iteration(s)! Download your .sv file.`, 'success');
      } else if (partial) {
        toast(`Lint passed but simulation failed after ${ev.total_iterations} iteration(s). Check sim log.`, 'error');
      } else {
        toast(`Verification failed after ${ev.total_iterations} iteration(s).`, 'error');
      }

      const lastIdx = state.iterations.length - 1;
      if (lastIdx >= 0) showCodeVersion(lastIdx);
      setRunning(false);
      loadHistory();
      break;
    }

    // ── Legacy v1 events (kept for backward compatibility) ────────────────
    case 'success': {
      setTierPill('tier1', 'pass');
      setTierBadge('tier1', 'pass');
      addFeedEvent('success', '🎉', 'DESIGN VERIFIED', ev.message, 'success');
      const lastIdx = state.iterations.length - 1;
      if (lastIdx >= 0) showCodeVersion(lastIdx);
      toast(`RTL verified in ${ev.iterations} iteration(s)!`, 'success');
      setRunning(false);
      loadHistory();
      break;
    }

    case 'error':
      addFeedEvent('error', '❌', 'ERROR', ev.message, 'error');
      toast(ev.message, 'error');
      setRunning(false);
      break;

    case 'max_iterations_reached':
      addFeedEvent('error', '🔄', 'MAX ITERATIONS REACHED', ev.message, 'error');
      toast(ev.message, 'error');
      setRunning(false);
      loadHistory();
      break;

    case 'stream_end':
      state.sseSource?.close();
      setRunning(false);
      break;
  }
}

// ─── Global Iteration Bar (Amendment 1) ───────────────────────────────────────
function initGlobalBar(maxTotal) {
  globalIterBar.innerHTML = '';
  for (let i = 1; i <= maxTotal; i++) {
    const pip = document.createElement('div');
    pip.className = 'global-pip';
    pip.id = `gpip-${i}`;
    globalIterBar.appendChild(pip);
  }
  if (globalIterLabel) globalIterLabel.textContent = `0 / ${maxTotal}`;
}

function updateGlobalBar(current, maxTotal) {
  for (let i = 1; i <= maxTotal; i++) {
    const pip = $(`gpip-${i}`);
    if (!pip) continue;
    pip.className = 'global-pip ' + (i < current ? 'done' : i === current ? 'active' : '');
  }
  if (globalIterLabel) globalIterLabel.textContent = `${current} / ${maxTotal}`;
}

// ─── Tier Badge & Pill ────────────────────────────────────────────────────────
function setTierBadge(tier, status) {
  const el = tier === 'tier1' ? badgeTier1 : badgeTier2;
  if (!el) return;
  el.className = `tier-badge ${status}`;
}

function setTierPill(tier, status) {
  const el = tier === 'tier1' ? tier1Pill : tier2Pill;
  if (!el) return;
  const labels = { idle: 'IDLE', running: 'RUNNING', pass: 'PASSED', fail: 'FAILED', warning: 'PARTIAL' };
  el.className = `tier-status-pill ${status}`;
  el.textContent = labels[status] || status.toUpperCase();
}

// ─── Functional Verification Panel ────────────────────────────────────────────
function clearFunctionalPanel() {
  if (simIterationsEl) simIterationsEl.innerHTML = '';
  if (simEmptyState) {
    simEmptyState.style.display = '';
    simIterationsEl?.appendChild(simEmptyState);
  }
  if (tbSection) tbSection.style.display = 'none';
  if (tbViewer) tbViewer.innerHTML = '';
  setTierPill('tier1', 'idle');
  setTierPill('tier2', 'idle');
  setTierBadge('tier1', 'idle');
  setTierBadge('tier2', 'idle');
}

function renderTestbench(code, filename) {
  if (!tbSection) return;
  if (simEmptyState) simEmptyState.style.display = 'none';
  tbSection.style.display = '';

  const copyTbBtn = $('copy-tb-btn');
  const downloadTbBtn = $('download-tb-btn');
  if (copyTbBtn) copyTbBtn.style.display = '';
  if (downloadTbBtn) {
    downloadTbBtn.style.display = '';
    downloadTbBtn.dataset.filename = filename || '';
    downloadTbBtn.dataset.sessionId = state.currentSession || '';
  }

  // Render syntax-highlighted testbench code
  if (tbViewer) {
    tbViewer.innerHTML = '';
    const pre = document.createElement('pre');
    const codeEl = document.createElement('code');
    codeEl.className = 'language-verilog';
    codeEl.textContent = code;
    pre.appendChild(codeEl);
    tbViewer.appendChild(pre);
    if (window.hljs) hljs.highlightElement(codeEl);
  }
}

function addSimIterCard({ iteration, passed, phase, stdout, stderr, timed_out, elapsed_ms, label }) {
  if (!simIterationsEl) return;
  if (simEmptyState) simEmptyState.style.display = 'none';

  const card = document.createElement('div');
  card.className = `sim-iter-card ${passed ? 'pass' : phase === 'build' ? 'build-error' : 'fail'}`;

  const badge = passed ? 'PASS' : phase === 'build' ? 'BUILD ERROR' : timed_out ? 'TIMEOUT' : 'FAIL';
  const badgeClass = passed ? 'pass' : 'fail';
  const elapsedStr = elapsed_ms ? ` · ${(elapsed_ms / 1000).toFixed(2)}s` : '';

  const logText = ((stdout || '') + (stderr ? '\n' + stderr : '')).trim().slice(0, 400);

  card.innerHTML = `
    <div class="sim-card-header">
      <span class="sim-card-label">${escHtml(label || `Sim #${iteration}`)}</span>
      <span class="sim-badge ${badgeClass}">${badge}</span>
      <span class="sim-elapsed">${escHtml(elapsedStr)}</span>
    </div>
    <pre class="sim-log ${passed ? 'pass' : 'fail'}">${escHtml(logText || '(no output)')}</pre>
  `;
  simIterationsEl.appendChild(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

window.toggleTestbench = function() {
  if (!tbViewer) return;
  const visible = tbViewer.style.display !== 'none';
  tbViewer.style.display = visible ? 'none' : '';
  const btn = $('tb-toggle-btn');
  if (btn) btn.textContent = visible ? '📋 Show Testbench Code' : '📋 Hide Testbench Code';
};

window.copyTestbench = async function() {
  if (!state.tbCode) return;
  try {
    await navigator.clipboard.writeText(state.tbCode);
    toast('Testbench copied!', 'info');
  } catch (_) { toast('Copy failed.', 'error'); }
};

window.downloadTestbench = function() {
  const btn = $('download-tb-btn');
  if (!btn) return;
  const filename = btn.dataset.filename;
  const sessionId = btn.dataset.sessionId;
  if (!filename || !sessionId) return;
  const a = document.createElement('a');
  a.href = `/api/download/${sessionId}/${filename}`;
  a.download = filename;
  a.click();
};

// ─── Feed Rendering ───────────────────────────────────────────────────────────
function clearFeed() {
  feedEl.innerHTML = '';
  if (feedEmptyEl) feedEmptyEl.style.display = 'none';
}

function addFeedEvent(category, icon, label, message, cssClass) {
  if (feedEmptyEl) feedEmptyEl.style.display = 'none';

  const el = document.createElement('div');
  el.className = 'feed-event';
  el.innerHTML = `
    <div class="ev-icon ${cssClass}">${icon}</div>
    <div class="ev-body">
      <div class="ev-type-label ${cssClass}">${label}</div>
      <div class="ev-message ${cssClass === 'success' ? 'success' : cssClass === 'error' ? 'error' : ''}">${escHtml(message)}</div>
    </div>`;
  feedEl.appendChild(el);
  feedEl.parentElement.scrollTop = feedEl.parentElement.scrollHeight;
  return el;
}

function addVeriOutput(parentEl, text, pass) {
  const bodyEl = parentEl.querySelector('.ev-body');
  const pre = document.createElement('pre');
  pre.className = 'veri-output ' + (pass ? 'pass' : 'fail');
  pre.textContent = text;
  bodyEl.appendChild(pre);
}

function addIterDivider(label) {
  const el = document.createElement('div');
  el.className = 'iter-divider';
  el.textContent = label;
  feedEl.appendChild(el);
}

// LLM Token Streaming
function startLLMStream() {
  if (feedEmptyEl) feedEmptyEl.style.display = 'none';

  const el = document.createElement('div');
  el.className = 'feed-event';
  el.innerHTML = `
    <div class="ev-icon llm">🤖</div>
    <div class="ev-body">
      <div class="ev-type-label llm">LLM GENERATING</div>
      <div class="ev-message" id="llm-stream-text" style="font-family:var(--font-code);font-size:11px;color:var(--text-muted);max-height:200px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:8;-webkit-box-orient:vertical;"></div>
    </div>`;
  feedEl.appendChild(el);
  state.streamingEl = el.querySelector('#llm-stream-text');
  feedEl.parentElement.scrollTop = feedEl.parentElement.scrollHeight;
}

function appendLLMToken(token) {
  if (!state.streamingEl) return;
  const text = document.createTextNode(token);
  state.streamingEl.appendChild(text);
  feedEl.parentElement.scrollTop = feedEl.parentElement.scrollHeight;
}

function endLLMStream(elapsed_ms, tokens, ttft_ms, tps) {
  if (state.streamingEl) {
    // Telemetry line — TTFT is the key prefix-cache metric
    if (elapsed_ms) {
      const meta = document.createElement('span');
      meta.style.cssText = 'display:block;margin-top:4px;color:var(--text-dim);font-size:10px;font-family:var(--font-code);';
      const ttftStr = ttft_ms ? ` · TTFT: ${ttft_ms.toFixed(0)}ms` : '';
      const tpsStr  = tps     ? ` · ${tps.toFixed(0)} tok/s` : '';
      meta.textContent = `${(elapsed_ms / 1000).toFixed(2)}s${ttftStr}${tpsStr} · ${tokens || 0} tokens`;
      state.streamingEl.appendChild(meta);
    }
    state.streamingEl = null;
  }
}

// ─── Code Viewer ──────────────────────────────────────────────────────────────
function clearCodeViewer() {
  codeViewer.innerHTML = '';
  if (codePlaceholder) codePlaceholder.style.display = 'flex';
  iterTabs.innerHTML = '';
  if (linesEl) linesEl.textContent = '—';
  copyBtn.disabled = true;
  downloadBtn.disabled = true;
  setVeriStatus('idle');
}

function addIterTab(iteration, status, tier) {
  const tab = document.createElement('div');
  tab.className = 'iter-tab';
  tab.dataset.idx = state.iterations.length - 1;
  const prefix = tier === 'tier2_correction' ? '★' : '';
  tab.textContent = `${prefix}v${iteration}`;
  tab.title = tier === 'tier2_correction' ? 'Functionally corrected DUT' : `Lint iteration ${iteration}`;
  tab.addEventListener('click', () => {
    showCodeVersion(parseInt(tab.dataset.idx));
  });
  iterTabs.appendChild(tab);
}

function updateIterTabStatus(idx, status) {
  const tabs = iterTabs.querySelectorAll('.iter-tab');
  if (tabs[idx]) {
    tabs[idx].classList.remove('clean', 'error', 'pending');
    tabs[idx].classList.add(status);
  }
}

function showCodeVersion(idx) {
  if (idx < 0 || idx >= state.iterations.length) return;
  state.activeIterTab = idx;
  const iter = state.iterations[idx];

  iterTabs.querySelectorAll('.iter-tab').forEach((t, i) => {
    t.classList.toggle('active', i === idx);
  });

  if (codePlaceholder) codePlaceholder.style.display = 'none';

  codeViewer.innerHTML = '';
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  code.className = 'language-verilog';
  code.textContent = iter.code;
  pre.appendChild(code);
  codeViewer.appendChild(pre);

  if (window.hljs) hljs.highlightElement(code);

  if (linesEl) linesEl.textContent = iter.lines;
  copyBtn.disabled = false;
  downloadBtn.disabled = !iter.filename;
  downloadBtn.dataset.filename = iter.filename || '';
  downloadBtn.dataset.sessionId = state.currentSession || '';
}

// ─── Verilator Status Bar ─────────────────────────────────────────────────────
function setVeriStatus(status) {
  const icons  = { idle: '◈', running: '⟳', pass: '✓', fail: '✗' };
  const labels = {
    idle:    'Awaiting lint',
    running: 'Running verilator...',
    pass:    'verilator: 0 errors · 0 warnings',
    fail:    'verilator: Errors found — see agent feed',
  };
  veriStatusBar.className = `veri-status-bar ${status}`;
  veriStatusBar.id = 'veri-status-bar';
  veriStatusBar.innerHTML = `<span class="veri-icon">${icons[status]}</span>${labels[status]}`;
}

// ─── Run State ────────────────────────────────────────────────────────────────
function setRunning(running) {
  runBtn.disabled = running;
  if (running) {
    runBtn.classList.add('running');
    runBtn.innerHTML = `
      <div class="btn-inner">
        <div class="spinner visible"></div>
        <span>Agent Running...</span>
      </div>`;
  } else {
    runBtn.classList.remove('running');
    runBtn.innerHTML = `
      <div class="btn-inner">
        <span>▶&nbsp;&nbsp;Run Agent</span>
      </div>`;
  }
}

// ─── Actions ──────────────────────────────────────────────────────────────────
async function handleCopy() {
  const idx = state.activeIterTab;
  if (idx < 0 || idx >= state.iterations.length) return;
  try {
    await navigator.clipboard.writeText(state.iterations[idx].code);
    toast('Code copied to clipboard!', 'info');
  } catch (_) {
    toast('Copy failed — use Ctrl+A on the code panel.', 'error');
  }
}

function handleDownload() {
  const filename = downloadBtn.dataset.filename;
  const sessionId = downloadBtn.dataset.sessionId;
  if (!filename || !sessionId) return;
  const a = document.createElement('a');
  a.href = `/api/download/${sessionId}/${filename}`;
  a.download = filename;
  a.click();
}

// ─── History ──────────────────────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch('/api/sessions');
    const sessions = await res.json();
    renderHistory(sessions);
  } catch (_) {}
}

function renderHistory(sessions) {
  const entries = Object.values(sessions).reverse().slice(0, 20);
  if (!entries.length) {
    historyEl.innerHTML = '<div class="history-empty">No sessions yet</div>';
    return;
  }
  historyEl.innerHTML = '';
  entries.forEach(s => {
    const el = document.createElement('div');
    el.className = 'history-item' + (s.session_id === state.currentSession ? ' active' : '');
    const dotClass = s.status === 'success' ? 'success'
                   : s.status === 'partial' ? 'warning'
                   : s.status === 'running' ? 'running'
                   : s.status === 'error' || s.status === 'failed' ? 'error'
                   : 'queued';
    const elapsed = s.completed_at ? ((s.completed_at - s.started_at)).toFixed(1) + 's' : 'running...';
    const lintBadge = s.lint_status === 'PASSED' ? '✓L' : s.lint_status === 'FAILED' ? '✗L' : '—L';
    const simBadge  = s.functional_status === 'PASSED' ? '✓S' : s.functional_status === 'FAILED' ? '✗S' : '—S';
    el.innerHTML = `
      <div class="history-dot ${dotClass}"></div>
      <div class="history-info">
        <div class="history-spec" title="${escHtml(s.spec)}">${escHtml(s.spec.slice(0, 38))}${s.spec.length > 38 ? '…' : ''}</div>
        <div class="history-meta">${s.mock_mode ? '[mock] ' : ''}${elapsed} · ${lintBadge} ${simBadge} · ${s.total_iterations || 0} iter</div>
      </div>`;
    historyEl.appendChild(el);
  });
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const icons = { success: '✓', error: '✗', info: '◈' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icons[type]}</span><span>${escHtml(msg)}</span>`;
  toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ─── Utility ──────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
