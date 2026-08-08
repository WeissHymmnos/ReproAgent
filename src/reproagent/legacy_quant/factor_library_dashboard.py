import json
from pathlib import Path
from typing import Optional
from .factor_db import FactorDB


def generate_dashboard(db_path: Optional[Path] = None, output_path: Optional[Path] = None):
    db = FactorDB(db_path)
    db.seed_demo()
    factor_rows = db.get_factors()

    factors = []
    for fr in factor_rows:
        ic_s, ex_s = db.get_factor_ts(fr["id"])
        factors.append(
            {
                "id": fr["id"],
                "name": fr["name"],
                "ic_series": ic_s,
                "excess_cum": ex_s,
                "stats": {
                    "ic": fr["ic_mean"],
                    "icir": fr["icir"],
                    "ann_return": fr["ann_return"],
                    "max_drawdown": fr["max_drawdown"],
                    "win_rate": fr["win_rate"],
                    "std": fr["ic_std"],
                },
            }
        )

    HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>因子库仪表盘</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  background:#0b0e1a; color:#e8ecf4; min-height:100vh;
}}
.nav {{
  background:linear-gradient(135deg,#141a2e 0%,#1a2140 100%);
  border-bottom:1px solid rgba(255,255,255,.06);
  padding:20px 48px;
  display:flex; align-items:center; justify-content:space-between;
}}
.nav h1 {{
  font-size:22px; font-weight:700;
  background:linear-gradient(90deg,#5b7cfa,#a78bfa);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent;
}}
.nav .badge {{
  background:rgba(91,124,250,.18); color:#8ba4ff;
  padding:6px 16px; border-radius:20px;
  font-size:14px; font-weight:600;
}}
.nav .badge span {{ color:#fff; font-size:18px; }}
.toolbar {{
  padding:24px 48px 0;
  display:flex; gap:12px; align-items:center;
}}
.toolbar input {{
  flex:1; max-width:320px;
  background:#151c30; border:1px solid #252d48;
  color:#e8ecf4; padding:10px 16px; border-radius:10px;
  font-size:14px; outline:none; transition:.2s;
}}
.toolbar input:focus {{ border-color:#5b7cfa; box-shadow:0 0 0 3px rgba(91,124,250,.2); }}
.toolbar .count {{ font-size:14px; color:#6b7599; margin-left:auto; }}
.grid {{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  gap:16px; padding:24px 48px 48px;
}}
.card {{
  background:linear-gradient(145deg,#141b30,#181f38);
  border:1px solid rgba(255,255,255,.05);
  border-radius:14px; padding:20px;
  cursor:pointer; transition:all .25s ease;
  position:relative; overflow:hidden;
}}
.card::before {{
  content:''; position:absolute; inset:0;
  background:linear-gradient(135deg,rgba(91,124,250,.08),transparent);
  opacity:0; transition:.25s;
}}
.card:hover {{ transform:translateY(-4px); border-color:#3f539c; box-shadow:0 12px 32px rgba(0,0,0,.5); }}
.card:hover::before {{ opacity:1; }}
.card .name {{ font-size:16px; font-weight:600; margin-bottom:10px; }}
.card .stat-row {{ display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px; }}
.card .stat-row .label {{ color:#6b7599; }}
.card .stat-row .value {{ font-weight:600; }}
.card .value.green {{ color:#34d399; }}
.card .value.red {{ color:#f87171; }}
.card .value.blue {{ color:#60a5fa; }}
.card .mini {{ font-size:11px; color:#4a5480; margin-top:8px; border-top:1px solid rgba(255,255,255,.04); padding-top:8px; }}
.modal-overlay {{
  display:none; position:fixed; inset:0; z-index:1000;
  background:rgba(0,0,0,.7); backdrop-filter:blur(6px);
  align-items:center; justify-content:center;
}}
.modal-overlay.active {{ display:flex; }}
.modal {{
  background:#131a30;
  border:1px solid rgba(255,255,255,.06);
  border-radius:20px; width:90%; max-width:960px;
  max-height:90vh; overflow-y:auto;
  padding:32px; position:relative;
  animation:modalIn .3s ease;
}}
@keyframes modalIn {{ from{{opacity:0;transform:scale(.95)translateY(16px)}} to{{opacity:1;transform:scale(1)translateY(0)}} }}
.modal-close {{
  position:absolute; top:16px; right:20px;
  background:none; border:none; color:#6b7599;
  font-size:28px; cursor:pointer; transition:.2s;
}}
.modal-close:hover {{ color:#fff; transform:rotate(90deg); }}
.modal h2 {{ font-size:22px; font-weight:700; margin-bottom:4px; }}
.modal .subtitle {{ color:#6b7599; font-size:14px; margin-bottom:20px; }}
.kpis {{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
  gap:12px; margin-bottom:24px;
}}
.kpi {{
  background:rgba(255,255,255,.03);
  border-radius:12px; padding:16px; text-align:center;
}}
.kpi .kpi-label {{ font-size:12px; color:#6b7599; margin-bottom:4px; }}
.kpi .kpi-value {{ font-size:20px; font-weight:700; }}
.kpi .kpi-value.green {{ color:#34d399; }}
.kpi .kpi-value.red {{ color:#f87171; }}
.kpi .kpi-value.blue {{ color:#60a5fa; }}
.tabs {{
  display:flex; gap:4px;
  background:rgba(255,255,255,.03);
  border-radius:10px; padding:4px; margin-bottom:16px;
}}
.tab {{
  flex:1; padding:10px; text-align:center;
  border:none; background:transparent; color:#6b7599;
  font-size:14px; font-weight:600; cursor:pointer;
  border-radius:8px; transition:.2s;
}}
.tab.active {{ background:#1d2645; color:#e8ecf4; }}
.tab:hover:not(.active) {{ color:#e8ecf4; }}
.tab-content {{ display:none; height:340px; }}
.tab-content.active {{ display:block; }}
.data-table {{ width:100%; border-collapse:collapse; font-size:14px; }}
.data-table th {{
  text-align:left; padding:10px 12px;
  border-bottom:1px solid rgba(255,255,255,.06);
  color:#6b7599; font-weight:500;
}}
.data-table td {{
  padding:10px 12px;
  border-bottom:1px solid rgba(255,255,255,.03);
}}
.modal::-webkit-scrollbar {{ width:6px; }}
.modal::-webkit-scrollbar-track {{ background:transparent; }}
.modal::-webkit-scrollbar-thumb {{ background:#2a3560; border-radius:3px; }}
@media (max-width:640px) {{
  .nav {{ padding:16px 20px; }}
  .grid {{ padding:16px 20px; grid-template-columns:1fr 1fr; }}
  .toolbar {{ padding:16px 20px 0; }}
  .modal {{ padding:20px; }}
}}
</style>
</head>
<body>
<div class="nav">
  <h1>&#x1F4CA; 因子库</h1>
  <div class="badge">总计 <span id="totalCount">{len(factors)}</span> 个因子</div>
</div>
<div class="toolbar">
  <input id="searchInput" type="text" placeholder="搜索因子名称..." oninput="filterCards()">
  <div class="count" id="visibleCount">显示 {len(factors)} / {len(factors)} 个</div>
</div>
<div class="grid" id="factorGrid"></div>
<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <button class="modal-close" onclick="closeModal()">&#215;</button>
    <h2 id="modalName"></h2>
    <div class="subtitle" id="modalSubtitle"></div>
    <div class="kpis" id="modalKpis"></div>
    <div class="tabs">
      <button class="tab active" data-tab="ic">IC 时序图</button>
      <button class="tab" data-tab="excess">超额复权时序</button>
      <button class="tab" data-tab="data">基本数据</button>
    </div>
    <div class="tab-content active" id="tabIc"><canvas id="icChart"></canvas></div>
    <div class="tab-content" id="tabExcess"><canvas id="excessChart"></canvas></div>
    <div class="tab-content" id="tabData"><table class="data-table" id="dataTable"></table></div>
  </div>
</div>
<script>
const FACTORS = {json.dumps(factors, ensure_ascii=False)};

function renderCard(f, i) {{
  const s = f.stats;
  const icColor = s.ic > 0 ? 'green' : 'red';
  const retColor = s.ann_return > 0 ? 'green' : 'red';
  return `<div class="card" onclick="openModal(${{i}})">
    <div class="name">${{f.name}}</div>
    <div class="stat-row"><span class="label">IC</span><span class="value ${{icColor}}">${{s.ic > 0 ? '+' : ''}}${{s.ic.toFixed(4)}}</span></div>
    <div class="stat-row"><span class="label">ICIR</span><span class="value blue">${{s.icir.toFixed(2)}}</span></div>
    <div class="stat-row"><span class="label">年化收益</span><span class="value ${{retColor}}">${{s.ann_return > 0 ? '+' : ''}}${{s.ann_return.toFixed(1)}}%</span></div>
    <div class="mini">回撤 ${{s.max_drawdown.toFixed(1)}}%  ·  胜率 ${{s.win_rate.toFixed(0)}}%</div>
  </div>`;
}}

function filterCards() {{
  const q = document.getElementById('searchInput').value.trim().toLowerCase();
  const grid = document.getElementById('factorGrid');
  let visible = 0;
  for (const [i, f] of FACTORS.entries()) {{
    const show = !q || f.name.includes(q);
    grid.children[i].style.display = show ? '' : 'none';
    if (show) visible++;
  }}
  document.getElementById('visibleCount').textContent = `显示 ${{visible}} / ${{FACTORS.length}} 个`;
}}

let charts = {{}};

function openModal(idx) {{
  const f = FACTORS[idx];
  const s = f.stats;
  document.getElementById('modalName').textContent = f.name;
  document.getElementById('modalSubtitle').textContent = `因子库 @ DB  · 第 ${{idx + 1}} / ${{FACTORS.length}} 个`;
  document.getElementById('modalKpis').innerHTML = `
    <div class="kpi"><div class="kpi-label">IC</div><div class="kpi-value ${{s.ic > 0 ? 'green' : 'red'}}">${{s.ic.toFixed(4)}}</div></div>
    <div class="kpi"><div class="kpi-label">ICIR</div><div class="kpi-value blue">${{s.icir.toFixed(2)}}</div></div>
    <div class="kpi"><div class="kpi-label">年化收益</div><div class="kpi-value ${{s.ann_return > 0 ? 'green' : 'red'}}">${{s.ann_return.toFixed(1)}}%</div></div>
    <div class="kpi"><div class="kpi-label">最大回撤</div><div class="kpi-value red">${{s.max_drawdown.toFixed(1)}}%</div></div>
    <div class="kpi"><div class="kpi-label">IC 标准差</div><div class="kpi-value blue">${{s.std.toFixed(4)}}</div></div>
    <div class="kpi"><div class="kpi-label">胜率</div><div class="kpi-value green">${{s.win_rate.toFixed(0)}}%</div></div>`;
  Object.values(charts).forEach(c => c.destroy());
  charts = {{}};
  const labels = f.ic_series.map((_, i) => `T${{i + 1}}`);
  charts.ic = new Chart(document.getElementById('icChart'), {{
    type:'line',
    data:{{
      labels,
      datasets:[{{
        label:'IC', data:f.ic_series,
        borderColor:'#5b7cfa',
        backgroundColor:(ctx) => {{ const g=ctx.chart.ctx.createLinearGradient(0,0,0,260); g.addColorStop(0,'rgba(91,124,250,.25)'); g.addColorStop(1,'rgba(91,124,250,.01)'); return g; }},
        fill:true, tension:.3, pointRadius:0, borderWidth:2,
      }}]
    }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{legend:{{display:false}}}},
      scales:{{x:{{display:false}},y:{{grid:{{color:'rgba(255,255,255,.04)'}},ticks:{{color:'#6b7599'}}}}}}
    }}
  }});
  charts.excess = new Chart(document.getElementById('excessChart'), {{
    type:'line',
    data:{{
      labels,
      datasets:[{{
        label:'累计超额复权', data:f.excess_cum,
        borderColor:'#34d399',
        backgroundColor:(ctx) => {{ const g=ctx.chart.ctx.createLinearGradient(0,0,0,260); g.addColorStop(0,'rgba(52,211,153,.2)'); g.addColorStop(1,'rgba(52,211,153,.01)'); return g; }},
        fill:true, tension:.3, pointRadius:0, borderWidth:2,
      }}]
    }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{legend:{{display:false}}}},
      scales:{{x:{{display:false}},y:{{grid:{{color:'rgba(255,255,255,.04)'}},ticks:{{color:'#6b7599'}}}}}}
    }}
  }});
  document.getElementById('dataTable').innerHTML = `
    <thead><tr><th>日期</th><th>IC</th><th>累计超额复权</th></tr></thead>
    <tbody>${{f.ic_series.map((v,i)=>`<tr><td>T${{i+1}}</td><td>${{v.toFixed(6)}}</td><td>${{f.excess_cum[i].toFixed(2)}}</td></tr>`).join('')}}</tbody>`;
  document.getElementById('modalOverlay').classList.add('active');
}}

function closeModal() {{
  document.getElementById('modalOverlay').classList.remove('active');
  Object.values(charts).forEach(c => c.destroy());
  charts = {{}};
}}

document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
    tab.classList.add('active');
    (tab.dataset.tab==='ic') ? document.getElementById('tabIc').classList.add('active') :
    (tab.dataset.tab==='excess') ? document.getElementById('tabExcess').classList.add('active') :
    document.getElementById('tabData').classList.add('active');
    setTimeout(() => Object.values(charts).forEach(c => c.resize()), 50);
  }});
}});

document.getElementById('modalOverlay').addEventListener('click', e => {{
  if (e.target === e.currentTarget) closeModal();
}});

document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') closeModal();
}});

document.getElementById('factorGrid').innerHTML = FACTORS.map(renderCard).join('');
</script>
</body>
</html>"""

    if output_path is None:
        output_path = Path(__file__).parent / "factor_library.html"
    else:
        output_path = Path(output_path)

    output_path.write_text(HTML, encoding="utf-8")
    print(f"OK - 因子库页面: {output_path.resolve()}")
    print(f"共 {len(factors)} 个因子 (来自 SQLite: {db.db_path})")
    db.close()


if __name__ == "__main__":
    generate_dashboard()
