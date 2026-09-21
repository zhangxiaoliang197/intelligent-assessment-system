"""template_render —— 零 LLM 确定性兜底页面。

当 PageWriter 多次失败时，用固定模板把 dataBundle 渲染成
KPI + 图表 + 地图 + 表格 + 数据说明页面。模板内只有通用映射逻辑，
不编造业务结论；同样严格遵守 page-kit 运行时契约，可通过 Guard。
"""
from typing import Any, Dict

_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>态势交互页面（兜底）</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         background: #f4f6fa; color: #1f2937; padding: 20px; }
  .page-head { background: linear-gradient(135deg,#1e3a8a,#1d4ed8); color: #fff;
               border-radius: 12px; padding: 20px 24px; margin-bottom: 16px; }
  .page-head h1 { font-size: 22px; margin-bottom: 6px; }
  .page-head .meta { font-size: 13px; opacity: .85; }
  .kpi-row { display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr));
             gap: 12px; margin-bottom: 16px; }
  .kpi { background: #fff; border-radius: 10px; padding: 16px 18px;
         box-shadow: 0 1px 4px rgba(15,23,42,.08); }
  .kpi .v { font-size: 26px; font-weight: 700; color: #1d4ed8; }
  .kpi .l { font-size: 13px; color: #64748b; margin-top: 4px; }
  .grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; }
  .card { background: #fff; border-radius: 10px; padding: 14px 16px;
          box-shadow: 0 1px 4px rgba(15,23,42,.08); min-width: 0; }
  .card.full { grid-column: 1 / -1; }
  .card h3 { font-size: 15px; margin-bottom: 10px; color: #0f172a; }
  .chart { height: 300px; }
  .map { height: 420px; }
  .note { background: #fffbeb; border: 1px solid #fde68a; color: #92400e;
          font-size: 13px; border-radius: 10px; padding: 12px 16px; margin-bottom: 16px; }
  .text-card p { font-size: 14px; line-height: 1.9; color: #334155; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div id="root"></div>
<script>
SitApp.bootstrap(function (data) {
  var root = document.getElementById('root');
  var datasets = data.datasets || [];

  function el(tag, cls, html) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html != null) node.innerHTML = html;
    return node;
  }
  function num(v) { var n = parseFloat(v); return isNaN(n) ? null : n; }

  // ── 页头 ──
  var head = el('div', 'page-head');
  head.appendChild(el('h1', null, SitUtil.escapeHtml(data.question ? (data.question.length > 28 ? data.question.slice(0, 28) : data.question) : '态势交互页面')));
  head.appendChild(el('div', 'meta', '生成时间：' + (data.generatedAt || '') + ' ｜ 数据源：' + datasets.length + ' 个'));
  root.appendChild(head);

  root.appendChild(el('div', 'note', '说明：智能页面引擎本次未能生成定制页面，已切换为标准模板渲染，数据为实时查询结果。'));

  // ── KPI：每个数据集行数 ──
  var kpiRow = el('div', 'kpi-row');
  datasets.forEach(function (ds) {
    var card = el('div', 'kpi');
    card.appendChild(el('div', 'v', String(ds.totalRows != null ? ds.totalRows : (ds.rows || []).length)));
    card.appendChild(el('div', 'l', SitUtil.escapeHtml(ds.name || ds.datasetId)));
    kpiRow.appendChild(card);
  });
  root.appendChild(kpiRow);

  var grid = el('div', 'grid');
  root.appendChild(grid);

  // ── 图表：聚合数据集，取首个分类列 + 数值列 ──
  datasets.forEach(function (ds, index) {
    if (ds.mode !== 'aggregate' || !ds.rows || !ds.rows.length) return;
    var cols = ds.columns || Object.keys(ds.rows[0]);
    var labelCol = null, valueCols = [];
    cols.forEach(function (c) {
      var numericSeen = 0, distinct = {};
      ds.rows.forEach(function (r) {
        if (num(r[c]) !== null) numericSeen++;
        else distinct[String(r[c])] = 1;
      });
      if (numericSeen >= ds.rows.length * 0.8 && valueCols.length < 3) valueCols.push(c);
      else if (!labelCol && Object.keys(distinct).length <= 30) labelCol = c;
    });
    if (!labelCol || !valueCols.length) return;
    var xData = ds.rows.map(function (r) { return String(r[labelCol]); });
    var series = valueCols.map(function (c) {
      return { name: c, data: ds.rows.map(function (r) { return num(r[c]) || 0; }) };
    });
    var card = el('div', 'card');
    card.appendChild(el('h3', null, SitUtil.escapeHtml((ds.name || '数据') + ' · ' + valueCols.join(' / '))));
    var chartEl = el('div', 'chart');
    card.appendChild(chartEl);
    grid.appendChild(card);
    SitChart.render(chartEl, {
      type: 'bar', title: '', xData: xData, series: series
    });
  });

  // ── 地图：第一个含地理特征的明细数据集 ──
  var geoDs = datasets.filter(function (ds) {
    return ds.geoFeatures && (ds.geoFeatures.points.length || ds.geoFeatures.tracks.length || ds.geoFeatures.circles.length);
  })[0];
  if (geoDs) {
    var mapCard = el('div', 'card full');
    mapCard.appendChild(el('h3', null, SitUtil.escapeHtml(geoDs.name || '空间分布')));
    var mapEl = el('div', 'map');
    mapCard.appendChild(mapEl);
    grid.appendChild(mapCard);
    var gf = geoDs.geoFeatures;
    SitMap.render(mapEl, {
      tracks: gf.tracks, points: gf.points, circles: gf.circles,
      fit: true, clusterPoints: true
    });
  }

  // ── 表格：第一个明细数据集前 8 列 / 10 行 ──
  var detailDs = datasets.filter(function (ds) { return ds.mode === 'detail' && ds.rows && ds.rows.length; })[0];
  if (detailDs) {
    var tableCard = el('div', 'card full');
    tableCard.appendChild(el('h3', null, SitUtil.escapeHtml((detailDs.name || '明细') + '（前 10 行）')));
    var tableEl = el('div');
    tableCard.appendChild(tableEl);
    grid.appendChild(tableCard);
    var cols = (detailDs.columns || []).slice(0, 8);
    SitTable.render(tableEl, {
      columns: cols, rows: detailDs.rows.slice(0, 10), maxHeight: 360
    });
  }

  // ── 文字：数据范围与字段说明（不编造结论）──
  var textCard = el('div', 'card full text-card');
  textCard.appendChild(el('h3', null, '数据说明'));
  var lines = datasets.map(function (ds) {
    return '· ' + SitUtil.escapeHtml(ds.name || ds.datasetId) + '：'
      + (ds.totalRows != null ? ds.totalRows : (ds.rows || []).length) + ' 行'
      + (ds.truncated ? '（已截断展示）' : '')
      + (ds.summary ? '，' + SitUtil.escapeHtml(ds.summary) : '');
  });
  var allWarnings = [];
  datasets.forEach(function (ds) { (ds.warnings || []).forEach(function (w) { allWarnings.push(w); }); });
  if (allWarnings.length) lines.push('· 取数提示：' + allWarnings.map(SitUtil.escapeHtml).join('；'));
  lines.push('· 本页为标准模板渲染，仅陈述查询到的数据范围与分布，业务结论需结合专业判读。');
  lines.forEach(function (line) {
    var p = el('p', null, line);
    textCard.appendChild(p);
  });
  grid.appendChild(textCard);

  SitApp.ready();
});
</script>
</body>
</html>
"""


def render_template_page(bundle: Dict[str, Any]) -> str:
    """返回确定性兜底 HTML（与 bundle 内容无关，运行时由数据驱动）。"""
    return _TEMPLATE
