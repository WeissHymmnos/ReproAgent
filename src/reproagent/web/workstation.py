"""Single-page workstation HTML (aiminer-inspired shell; ReproAgent journeys only)."""

from __future__ import annotations

# Language: HTML + CSS + vanilla JS. Dark research-workstation layout
# patterned after aiminer frontend shell (sidebar nav + main list/detail).

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ReproAgent Workstation</title>
<style>
:root {
  color-scheme: dark;
  --ctp-peach: #f5a97f;
  --ctp-mauve: #c6a0f6;
  --ctp-blue: #8aadf4;
  --ctp-green: #a6da95;
  --ctp-red: #ed8796;
  --ctp-yellow: #eed49f;
  --ctp-text: #cad3f5;
  --ctp-subtext0: #a5adcb;
  --ctp-surface0: #363a4f;
  --ctp-surface1: #494d64;
  --ctp-surface2: #5b6078;
  --ctp-base: #24273a;
  --ctp-mantle: #1e2030;
  --ctp-crust: #181926;
  font-family: "IBM Plex Sans", "Source Sans 3", "PingFang SC", "Microsoft YaHei", sans-serif;
  line-height: 1.5;
  color: var(--ctp-text);
  background: var(--ctp-base);
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--ctp-base); }
button, input, textarea, select { font: inherit; color: inherit; }
.shell { height: 100vh; width: 100vw; display: flex; overflow: hidden; }
.sidebar {
  width: 240px; flex: 0 0 240px; padding: 24px;
  background: var(--ctp-mantle); border-right: 1px solid var(--ctp-crust);
  display: flex; flex-direction: column; gap: 16px; overflow-y: auto;
}
.main { flex: 1; min-width: 0; padding: 24px; overflow: auto; display: flex; flex-direction: column; gap: 16px; }
.eyebrow { margin: 0; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ctp-peach); font-size: 0.78rem; }
.sidebar h1 { margin: 4px 0 0; font-size: 1.35rem; }
.muted { color: var(--ctp-subtext0); font-size: 0.9rem; }
.nav { display: grid; gap: 8px; margin-top: 8px; }
.nav-link {
  display: block; padding: 10px 12px; border-radius: 10px;
  background: transparent; border: 1px solid transparent; cursor: pointer; text-align: left;
  color: var(--ctp-text);
}
.nav-link:hover { background: rgba(138,173,244,.08); border-color: var(--ctp-surface0); }
.nav-link.active { background: rgba(198,160,246,.16); border-color: rgba(198,160,246,.35); color: #fff; }
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(138,173,244,.15); color: var(--ctp-blue);
  padding: 4px 10px; border-radius: 999px; font-size: 0.82rem; font-weight: 600;
}
.panel {
  background: linear-gradient(145deg, #1f2438, #1a1f33);
  border: 1px solid rgba(255,255,255,.06); border-radius: 14px; padding: 16px 18px;
}
.panel h2 { margin: 0 0 8px; font-size: 1.15rem; }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
.toolbar input, .toolbar select, .field input, .field textarea {
  background: #151c30; border: 1px solid #252d48; border-radius: 10px;
  padding: 9px 12px; outline: none; min-width: 0;
}
.toolbar input:focus, .field input:focus, .field textarea:focus { border-color: var(--ctp-blue); }
.btn {
  background: rgba(138,173,244,.18); border: 1px solid rgba(138,173,244,.35);
  color: #fff; border-radius: 10px; padding: 9px 14px; cursor: pointer;
}
.btn:hover { background: rgba(138,173,244,.28); }
.btn.primary { background: linear-gradient(135deg, #5b7cfa, #7c6af0); border: none; }
.btn.success { background: rgba(166,218,149,.18); border-color: rgba(166,218,149,.4); color: var(--ctp-green); }
.btn.danger { background: rgba(237,135,150,.15); border-color: rgba(237,135,150,.4); color: var(--ctp-red); }
.grid-2 { display: grid; grid-template-columns: minmax(260px, 34%) 1fr; gap: 14px; min-height: 420px; }
@media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } .sidebar { width: 200px; flex-basis: 200px; } }
.list { display: flex; flex-direction: column; gap: 8px; max-height: 70vh; overflow: auto; }
.card {
  background: #141b30; border: 1px solid rgba(255,255,255,.05); border-radius: 12px;
  padding: 12px 14px; cursor: pointer; transition: .15s ease;
}
.card:hover, .card.active { border-color: #3f539c; transform: translateY(-1px); }
.card .name { font-weight: 600; margin-bottom: 4px; }
.card .meta { font-size: 0.82rem; color: var(--ctp-subtext0); display: flex; gap: 10px; flex-wrap: wrap; }
.pill {
  font-size: 0.75rem; padding: 2px 8px; border-radius: 999px;
  background: rgba(255,255,255,.06); color: var(--ctp-subtext0);
}
.pill.ok { background: rgba(166,218,149,.15); color: var(--ctp-green); }
.pill.warn { background: rgba(238,212,159,.15); color: var(--ctp-yellow); }
.detail pre, .mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem; white-space: pre-wrap; word-break: break-word;
  background: #101525; border-radius: 10px; padding: 12px; border: 1px solid rgba(255,255,255,.04);
}
.empty {
  padding: 28px; text-align: center; color: var(--ctp-subtext0);
  border: 1px dashed var(--ctp-surface1); border-radius: 12px;
}
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.kpi { background: #141b30; border-radius: 12px; padding: 14px; border: 1px solid rgba(255,255,255,.05); }
.kpi .label { color: var(--ctp-subtext0); font-size: 0.8rem; }
.kpi .value { font-size: 1.5rem; font-weight: 700; margin-top: 4px; }
.hidden { display: none !important; }
.field { display: grid; gap: 6px; margin-bottom: 12px; }
.log {
  min-height: 160px; max-height: 320px; overflow: auto;
  background: #101525; border-radius: 10px; padding: 12px; font-size: 0.85rem;
  border: 1px solid rgba(255,255,255,.04); white-space: pre-wrap;
}
.status-line { font-size: 0.85rem; color: var(--ctp-subtext0); }
.error { color: var(--ctp-red); }
.ok-text { color: var(--ctp-green); }
</style>
</head>
<body>
<div class="shell">
  <aside class="sidebar">
    <div>
      <p class="eyebrow">ReproAgent</p>
      <h1>Web Workstation</h1>
      <p class="muted">研报因子复现工作台：因子库浏览、人工复核与研报任务提交。</p>
    </div>
    <div class="badge">本地 · <span id="lib-badge">0</span> 因子</div>
    <nav class="nav">
      <button type="button" class="nav-link active" data-view="library">因子库</button>
      <button type="button" class="nav-link" data-view="review">人工复核</button>
      <button type="button" class="nav-link" data-view="reproduce">研报复现</button>
    </nav>
    <p class="muted" style="margin-top:auto">数据来自本机 ReproAgent 库与复核队列。</p>
  </aside>
  <main class="main">
    <!-- Library -->
    <section id="view-library" class="view">
      <div class="panel">
        <h2>因子库</h2>
        <p class="muted">浏览已入库因子；点击条目查看公式与状态。</p>
        <div class="toolbar">
          <input id="lib-search" type="search" placeholder="搜索名称 / 公式…" style="flex:1;min-width:180px" />
          <select id="lib-style">
            <option value="">全部风格</option>
          </select>
          <button type="button" class="btn" id="lib-refresh">刷新</button>
        </div>
        <div class="kpis" id="lib-kpis"></div>
      </div>
      <div class="grid-2">
        <div class="panel">
          <div id="lib-list" class="list"></div>
        </div>
        <div class="panel detail" id="lib-detail">
          <div class="empty">← 选择左侧因子查看详情</div>
        </div>
      </div>
    </section>

    <!-- Review -->
    <section id="view-review" class="view hidden">
      <div class="panel">
        <h2>人工复核</h2>
        <p class="muted">待审队列来自真实 Manual Review 存储；批准 / 拒绝会写回数据库。</p>
        <div class="toolbar">
          <button type="button" class="btn" id="rev-refresh">刷新队列</button>
          <span class="status-line" id="rev-status"></span>
        </div>
      </div>
      <div class="grid-2">
        <div class="panel"><div id="rev-list" class="list"></div></div>
        <div class="panel detail" id="rev-detail"><div class="empty">队列为空或未选择条目</div></div>
      </div>
    </section>

    <!-- Reproduce -->
    <section id="view-reproduce" class="view hidden">
      <div class="panel">
        <h2>研报复现</h2>
        <p class="muted">提交本机 PDF / Markdown 路径，后台运行真实 pipeline；界面轮询任务状态，不伪造指标。</p>
        <div class="field">
          <label for="repro-path">报告路径</label>
          <input id="repro-path" type="text" placeholder="/path/to/report.pdf 或 .md" />
        </div>
        <div class="field" style="margin-top: 12px;">
          <label for="repro-mode">回测模式</label>
          <select id="repro-mode" style="padding: 6px; border-radius: 4px; background: var(--ctp-surface1); border: 1px solid var(--ctp-surface2);">
            <option value="factor">因子模式 (默认分组回测)</option>
            <option value="strategy">策略模式 (按规则生成持仓)</option>
          </select>
        </div>
        <div id="strategy-options" style="display: none; margin-top: 12px; background: var(--ctp-surface0); padding: 12px; border-radius: 8px;">
          <div class="field" style="margin-bottom: 8px;">
            <label>策略类型</label>
            <select id="repro-strategy-mode" style="padding: 4px;">
              <option value="cross_sectional">截面 (Cross Sectional)</option>
              <option value="time_series">时序 (Time Series)</option>
            </select>
          </div>
          <div class="field" style="margin-bottom: 8px;">
            <label>方向</label>
            <select id="repro-direction" style="padding: 4px;">
              <option value="long_short">多空 (Long-Short)</option>
              <option value="long_only">做多 (Long-Only)</option>
              <option value="long_flat">做多平仓 (Long-Flat)</option>
            </select>
          </div>
          <div class="field" style="margin-bottom: 8px;">
            <label>选股规则</label>
            <select id="repro-selection" style="padding: 4px;">
              <option value="top_bottom_n">Top/Bottom N</option>
              <option value="top_n">Top N</option>
              <option value="bottom_n">Bottom N</option>
              <option value="threshold">阈值 (Threshold)</option>
            </select>
          </div>
          <div class="field">
            <label>N (若选Top/Bottom)</label>
            <input id="repro-param-n" type="number" placeholder="10" value="10" style="padding: 4px;" />
          </div>
          <div class="field" style="margin-top: 8px;">
            <label>多头阈值 (若选Threshold)</label>
            <input id="repro-param-long-th" type="number" step="0.1" placeholder="0.75" style="padding: 4px;" />
          </div>
          <div class="field" style="margin-top: 8px;">
            <label>空头阈值 (若选Threshold)</label>
            <input id="repro-param-short-th" type="number" step="0.1" placeholder="-0.75" style="padding: 4px;" />
          </div>
          <div class="field" style="margin-top: 8px;">
            <label>最短持有天数</label>
            <input id="repro-param-min-hold" type="number" min="1" value="1" style="padding: 4px;" />
          </div>
          <div class="field" style="margin-top: 8px;">
            <label>退出阈值 (可选)</label>
            <input id="repro-param-exit-th" type="number" step="0.1" placeholder="空=按信号离场" style="padding: 4px;" />
          </div>
        </div>
        <div class="toolbar" style="margin-top: 16px;">
          <button type="button" class="btn primary" id="repro-submit">提交复现</button>
          <button type="button" class="btn" id="repro-refresh">刷新任务</button>
        </div>
        <div class="status-line" id="repro-status">尚未提交任务</div>
        <div class="muted" id="repro-jobs">内存任务列表未加载</div>
        <div class="log" id="repro-log"></div>
      </div>
    </section>
  </main>
</div>
<script>
const state = {
  library: [],
  libTotal: 0,
  libStyles: [],
  selectedLib: null,
  reviews: [],
  reviewTotal: null,
  selectedRev: null,
  jobId: null,
  pollTimer: null,
};

async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const msg = (data && (data.error || data.detail)) || res.statusText || "request failed";
    throw new Error(msg);
  }
  return data;
}

function showView(name) {
  document.querySelectorAll(".view").forEach(el => el.classList.add("hidden"));
  document.getElementById("view-" + name).classList.remove("hidden");
  document.querySelectorAll(".nav-link").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.view === name);
  });
  if (name === "reproduce") loadJobs().catch(() => {});
}

document.querySelectorAll(".nav-link").forEach(btn => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

function statusPill(status) {
  const s = (status || "").toLowerCase();
  if (s === "ready" || s === "approved" || s === "passed") return `<span class="pill ok">${status}</span>`;
  if (s === "review" || s === "pending") return `<span class="pill warn">${status}</span>`;
  return `<span class="pill">${status || "—"}</span>`;
}

function renderLibrary() {
  const items = state.library.slice();
  const list = document.getElementById("lib-list");
  if (!items.length) {
    list.innerHTML = `<div class="empty">${state.libTotal ? "无匹配结果" : "因子库为空 — 请先用 CLI 复现并入库"}</div>`;
  } else {
    list.innerHTML = items.map(it => `
      <div class="card ${state.selectedLib === it.id ? "active" : ""}" data-id="${it.id}">
        <div class="name">${escapeHtml(it.name_cn || it.name)}</div>
        <div class="meta">
          <span>${escapeHtml(it.style || "other")}</span>
          ${statusPill(it.status)}
          <span>v${escapeHtml(it.version || "")}</span>
        </div>
      </div>`).join("");
    list.querySelectorAll(".card").forEach(card => {
      card.addEventListener("click", () => selectLibrary(card.dataset.id));
    });
  }
  const styles = (state.libStyles && state.libStyles.length)
    ? state.libStyles
    : [...new Set(state.library.map(x => x.style).filter(Boolean))].sort();
  const sel = document.getElementById("lib-style");
  const cur = sel.value;
  sel.innerHTML = `<option value="">全部风格</option>` + styles.map(s =>
    `<option value="${escapeAttr(s)}">${escapeHtml(s)}</option>`).join("");
  if ([...sel.options].some(o => o.value === cur)) sel.value = cur;

  const total = state.libTotal || items.length;
  const kpis = document.getElementById("lib-kpis");
  kpis.innerHTML = `
    <div class="kpi"><div class="label">因子总数</div><div class="value">${total}</div></div>
    <div class="kpi"><div class="label">风格数</div><div class="value">${styles.length}</div></div>
    <div class="kpi"><div class="label">筛选后</div><div class="value">${items.length}</div></div>`;
  document.getElementById("lib-badge").textContent = String(total);
}

function selectLibrary(id) {
  state.selectedLib = id;
  const it = state.library.find(x => x.id === id);
  const box = document.getElementById("lib-detail");
  if (!it) {
    box.innerHTML = `<div class="empty">未找到因子</div>`;
    return;
  }
  box.innerHTML = `
    <h2 style="margin-top:0">${escapeHtml(it.name_cn || it.name)}</h2>
    <div class="meta" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap">
      ${statusPill(it.status)}
      <span class="pill">${escapeHtml(it.style)}</span>
      <span class="pill">v${escapeHtml(it.version)}</span>
    </div>
    <p class="muted">英文名：${escapeHtml(it.name)}</p>
    ${it.metrics && (it.metrics.ic != null || it.metrics.sharpe != null) ? `
    <div class="kpis" style="margin:12px 0">
      <div class="kpi"><div class="label">IC</div><div class="value">${Number(it.metrics.ic || 0).toFixed(3)}</div></div>
      <div class="kpi"><div class="label">Sharpe</div><div class="value">${Number(it.metrics.sharpe || 0).toFixed(2)}</div></div>
      <div class="kpi"><div class="label">年化</div><div class="value">${(Number(it.metrics.ann_return || 0)*100).toFixed(1)}%</div></div>
    </div>` : ""}
    <h3>公式</h3>
    <pre class="mono">${escapeHtml(it.formula || "")}</pre>
    <h3>字段</h3>
    <p>${(it.input_fields || []).map(f => `<span class="pill">${escapeHtml(f)}</span>`).join(" ") || "—"}</p>
    <h3>元数据</h3>
    <pre class="mono">id: ${escapeHtml(it.id)}
report_id: ${escapeHtml(it.report_id || "")}
universe: ${escapeHtml(it.universe || "")}
rebalance: ${escapeHtml(it.rebalance_frequency || "")}
deviation_passed: ${it.deviation_passed}
tags: ${(it.tags || []).join(", ") || "—"}
created_at: ${escapeHtml(it.created_at || "")}</pre>`;
  renderLibrary();
}

async function loadLibrary() {
  const q = (document.getElementById("lib-search").value || "").trim();
  const style = document.getElementById("lib-style").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (style) params.set("style", style);
  params.set("limit", "100");
  const [data, summary] = await Promise.all([
    api("/api/library?" + params.toString()),
    api("/api/summary"),
  ]);
  state.library = data.items || [];
  state.libTotal = summary.library_count || 0;
  state.libStyles = Object.keys(summary.styles || {}).sort();
  renderLibrary();
  if (state.selectedLib) selectLibrary(state.selectedLib);
}

function renderReviews() {
  const list = document.getElementById("rev-list");
  const items = state.reviews;
  const total = state.reviewTotal != null ? state.reviewTotal : items.length;
  document.getElementById("rev-status").textContent = total
    ? `待审 ${items.length}${total > items.length ? " / " + total : ""} 项`
    : "队列为空";
  if (!items.length) {
    list.innerHTML = `<div class="empty">复核队列为空</div>`;
    document.getElementById("rev-detail").innerHTML = `<div class="empty">无待审项</div>`;
    return;
  }
  list.innerHTML = items.map(it => `
    <div class="card ${state.selectedRev === it.entry_id ? "active" : ""}" data-id="${it.entry_id}">
      <div class="name">${escapeHtml(it.title || it.report_id)}</div>
      <div class="meta">
        ${statusPill(it.status)}
        <span>${escapeHtml(it.broker || "—")}</span>
      </div>
    </div>`).join("");
  list.querySelectorAll(".card").forEach(card => {
    card.addEventListener("click", () => selectReview(card.dataset.id));
  });
}

function selectReview(id) {
  state.selectedRev = id;
  const it = state.reviews.find(x => x.entry_id === id);
  const box = document.getElementById("rev-detail");
  if (!it) {
    box.innerHTML = `<div class="empty">未找到条目</div>`;
    return;
  }
  box.innerHTML = `
    <h2 style="margin-top:0">${escapeHtml(it.title || "未命名报告")}</h2>
    <p class="muted">${escapeHtml(it.reason || "")}</p>
    <pre class="mono">entry_id: ${escapeHtml(it.entry_id)}
report_id: ${escapeHtml(it.report_id)}
broker: ${escapeHtml(it.broker || "")}
validation_status: ${escapeHtml(it.validation_status || "")}
file_path: ${escapeHtml(it.file_path || "")}
created_at: ${escapeHtml(it.created_at || "")}</pre>
    <div class="toolbar" style="margin-top:12px">
      <button type="button" class="btn success" id="rev-approve">批准</button>
      <button type="button" class="btn danger" id="rev-reject">拒绝</button>
    </div>`;
  document.getElementById("rev-approve").onclick = () => decideReview(id, "approve");
  document.getElementById("rev-reject").onclick = () => decideReview(id, "reject");
  renderReviews();
}

async function loadReviews() {
  const data = await api("/api/review?limit=50");
  state.reviews = data.items || [];
  state.reviewTotal = data.total;
  if (state.selectedRev && !state.reviews.some(x => x.entry_id === state.selectedRev)) {
    state.selectedRev = null;
  }
  renderReviews();
  if (state.selectedRev) selectReview(state.selectedRev);
}

async function decideReview(entryId, decision) {
  await api("/api/review/" + encodeURIComponent(entryId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  state.selectedRev = null;
  await loadReviews();
}

async function submitReproduce() {
  const path = (document.getElementById("repro-path").value || "").trim();
  const status = document.getElementById("repro-status");
  const log = document.getElementById("repro-log");
  if (!path) {
    status.innerHTML = `<span class="error">请填写报告路径</span>`;
    return;
  }
  
  const mode = document.getElementById("repro-mode").value;
  let backtest_kwargs = { mode: mode };
  if (mode === "strategy") {
    backtest_kwargs.strategy_mode = document.getElementById("repro-strategy-mode").value;
    backtest_kwargs.direction = document.getElementById("repro-direction").value;
    backtest_kwargs.selection_rule = document.getElementById("repro-selection").value;
    
    const n = parseInt(document.getElementById("repro-param-n").value);
    if (!isNaN(n)) {
      backtest_kwargs.top_n = n;
      backtest_kwargs.bottom_n = n;
    }
    const longTh = parseFloat(document.getElementById("repro-param-long-th").value);
    if (!isNaN(longTh)) backtest_kwargs.long_threshold = longTh;
    const shortTh = parseFloat(document.getElementById("repro-param-short-th").value);
    if (!isNaN(shortTh)) backtest_kwargs.short_threshold = shortTh;
    const minHold = parseInt(document.getElementById("repro-param-min-hold").value, 10);
    if (!isNaN(minHold) && minHold >= 1) backtest_kwargs.min_holding_days = minHold;
    const exitTh = parseFloat(document.getElementById("repro-param-exit-th").value);
    if (!isNaN(exitTh)) backtest_kwargs.exit_threshold = exitTh;
  }

  status.textContent = "提交中…";
  log.textContent = "";
  try {
    const data = await api("/api/reproduce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path, backtest_kwargs: backtest_kwargs }),
    });
    state.jobId = data.job_id;
    status.textContent = `任务已创建：${data.job_id}（${data.status}）`;
    loadJobs().catch(() => {});
    pollJob();
  } catch (e) {
    status.innerHTML = `<span class="error">${escapeHtml(e.message)}</span>`;
  }
}

async function pollJob() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  if (!state.jobId) return;
  const tick = async () => {
    try {
      const data = await api("/api/jobs/" + encodeURIComponent(state.jobId));
      const status = document.getElementById("repro-status");
      const log = document.getElementById("repro-log");
      status.innerHTML = `任务 ${escapeHtml(data.job_id)} · <b>${escapeHtml(data.status)}</b>`;
      log.textContent = formatJob(data);
      if (data.status === "finished" || data.status === "error") {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        if (data.status === "finished") loadLibrary().catch(() => {});
      }
    } catch (e) {
      document.getElementById("repro-status").innerHTML =
        `<span class="error">${escapeHtml(e.message)}</span>`;
      const msg = String(e && e.message || "");
      if (msg.includes("not found") || msg.includes("404")) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
      }
    }
  };
  await tick();
  state.pollTimer = setInterval(tick, 1500);
}

async function loadJobs() {
  const el = document.getElementById("repro-jobs");
  try {
    const data = await api("/api/jobs");
    const items = data.items || [];
    if (!items.length) {
      el.textContent = "内存中无任务（刷新页面会清空）";
      return;
    }
    el.innerHTML = items.map(j =>
      `<div><code>${escapeHtml(j.job_id)}</code> · ${escapeHtml(j.status)} · ${escapeHtml(j.message || "")}</div>`
    ).join("");
  } catch (e) {
    el.innerHTML = `<span class="error">${escapeHtml(e.message)}</span>`;
  }
}

function formatJob(data) {
  const lines = [
    `status: ${data.status}`,
    `path: ${data.path || ""}`,
    `message: ${data.message || ""}`,
  ];
  if (data.result) {
    lines.push("result: " + JSON.stringify(data.result, null, 2));
  }
  if (data.error) lines.push("error: " + data.error);
  return lines.join("\n");
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
}
function escapeAttr(s) { return escapeHtml(s).replace(/`/g, ""); }

document.getElementById("lib-refresh").onclick = () => loadLibrary().catch(showErr);
let _libSearchTimer = null;
document.getElementById("lib-search").oninput = () => {
  clearTimeout(_libSearchTimer);
  _libSearchTimer = setTimeout(() => loadLibrary().catch(showErr), 200);
};
document.getElementById("lib-style").onchange = () => loadLibrary().catch(showErr);
document.getElementById("rev-refresh").onclick = () => loadReviews().catch(showErr);
document.getElementById("repro-submit").onclick = submitReproduce;
document.getElementById("repro-refresh").onclick = () => {
  loadJobs().catch(showErr);
  if (state.jobId) pollJob();
};
document.getElementById("repro-mode").onchange = (e) => {
  const isStrategy = e.target.value === "strategy";
  document.getElementById("strategy-options").style.display = isStrategy ? "block" : "none";
};

function showErr(e) {
  console.error(e);
  alert(e.message || String(e));
}

// boot
Promise.all([loadLibrary(), loadReviews()]).catch(showErr);
</script>
</body>
</html>
"""


def get_index_html() -> str:
    """Return the workstation index HTML document."""
    return INDEX_HTML
