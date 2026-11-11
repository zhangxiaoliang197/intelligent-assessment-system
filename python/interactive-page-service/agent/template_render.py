"""template_render —— 零 LLM 确定性兜底页面。

当 PageWriter 多次失败时，用固定模板把 dataBundle 渲染成
「单屏态势区（图表+地图）+ 平铺明细/结论」：页头 → KPI → 主区 → 明细表 → 结论。
单屏区高度取宿主注入的 --ipage-vh；图表卡片等宽且带最小可读高度，超出时图表列内滚动；
明细表每页最多 10 行，超过由组件分页。模板内只有通用映射逻辑，不编造业务结论；
同样严格遵守 page-kit 运行时契约，可通过 Guard。
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
         background: #f4f6fa; color: #1f2937; padding: 16px 16px 30px; }
  #root { display: flex; flex-direction: column; gap: 12px; }
  /* 单屏区：页头 + KPI + 主区（图表/地图），高度固定为宿主可视高 */
  .screen { height: var(--ipage-vh, 720px); display: flex; flex-direction: column;
            gap: 12px; }
  .page-head { flex: none; background: linear-gradient(135deg,#1e3a8a,#1d4ed8); color: #fff;
               border-radius: 12px; padding: 14px 20px; }
  .page-head h1 { font-size: 20px; margin-bottom: 4px; }
  .page-head .meta { font-size: 12px; opacity: .85; }
  .note { flex: none; background: #fffbeb; border: 1px solid #fde68a; color: #92400e;
          font-size: 12px; border-radius: 8px; padding: 8px 12px; }
  .kpi-row { flex: none; display: grid; grid-template-columns: repeat(auto-fit,minmax(160px,1fr));
             gap: 10px; }
  .kpi { background: #fff; border-radius: 10px; padding: 10px 14px;
         box-shadow: 0 1px 4px rgba(15,23,42,.08); }
  .kpi .v { font-size: 22px; font-weight: 700; color: #1d4ed8; }
  .kpi .l { font-size: 12px; color: #64748b; margin-top: 2px; }
  /* 主区：左图表 / 右地图，整体吸收单屏区剩余高度 */
  .main { flex: 1; min-height: 0; display: grid;
          grid-template-columns: minmax(0, var(--ipage-left,44%)) minmax(0, 1fr); gap: 12px; }
  /* 图表列：卡片等宽铺满；总高超出时只在列内滚动，地图保持满高 */
  .chart-col { display: grid; gap: 10px; min-height: 0; min-width: 0;
               grid-template-columns: minmax(0, 1fr);
               grid-auto-rows: minmax(320px, 1fr);
               overflow-y: auto; overscroll-behavior: contain; align-content: start; }
  .card { background: #fff; border-radius: 10px; padding: 10px 12px;
          box-shadow: 0 1px 4px rgba(15,23,42,.08); min-width: 0; min-height: 0;
          display: flex; flex-direction: column; }
  .chart-card { width: 100%; max-width: none; min-width: 0; min-height: 0;
                display: flex; flex-direction: column; }
  .chart-card.wide { max-width: none; grid-column: 1 / -1; }
  .card h3 { flex: none; font-size: 13px; margin-bottom: 6px; color: #0f172a; }
  .chart { flex: 1; width: 100%; min-height: 240px; }
  .map-card { padding: 10px 12px; }
  .map { flex: 1; min-height: 0; border-radius: 8px; overflow: hidden; }
  /* 平铺区：明细表与结论不设固定高度、不出现内部滚动条 */
  .table-card { flex: none; }
  .text-card { flex: none; }
  .text-card p { font-size: 12px; line-height: 1.7; color: #334155; }
  @media (max-width: 900px) {
    .screen { height: auto; }
    .main { grid-template-columns: 1fr; grid-auto-rows: minmax(220px, auto); }
    .chart-col { grid-template-columns: 1fr !important; grid-template-rows: none !important;
                 grid-auto-rows: minmax(240px, auto); overflow: visible; }
    .chart-card, .chart-card.wide { max-width: none; grid-column: auto !important; }
    .chart { min-height: 220px; }
    .map-card { min-height: 320px; }
  }
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

  // ── 单屏区：页头 + KPI + 主区 ──
  var screen = el('div', 'screen');
  root.appendChild(screen);

  var head = el('div', 'page-head');
  head.appendChild(el('h1', null, SitUtil.escapeHtml(data.question ? (data.question.length > 28 ? data.question.slice(0, 28) : data.question) : '态势交互页面')));
  head.appendChild(el('div', 'meta', '生成时间：' + (data.generatedAt || '') + ' ｜ 数据源：' + datasets.length + ' 个'));
  screen.appendChild(head);

  screen.appendChild(el('div', 'note', '说明：智能页面引擎本次未能生成定制页面，已切换为标准模板渲染，数据为实时查询结果。'));

  var kpiRow = el('div', 'kpi-row');
  datasets.forEach(function (ds) {
    var card = el('div', 'kpi');
    card.appendChild(el('div', 'v', String(ds.totalRows != null ? ds.totalRows : (ds.rows || []).length)));
    card.appendChild(el('div', 'l', SitUtil.escapeHtml(ds.name || ds.datasetId)));
    kpiRow.appendChild(card);
  });
  screen.appendChild(kpiRow);

  // ── 页面级时间轴：只创建时钟（控件由宿主浮层渲染），容器在结论区之后 ──
  var tlEl = el('div');
  tlEl.id = 'tl';
  var tl = null;
  if (data.timeline && (data.timeline.buckets || []).length > 1) {
    // 必须先建时钟：SitChart 的 timeline 配置依赖 SitTimeline.current()
    tl = SitTimeline.render(tlEl, { axis: data.timeline.buckets });
  }

  var main = el('div', 'main');
  var chartCol = el('div', 'chart-col');
  main.appendChild(chartCol);
  screen.appendChild(main);

  // ── 图表数据：聚合表取分类列+数值列；时序表保留时间桶结构（不强制联动）──
  var items = [];
  datasets.forEach(function (ds) {
    if (ds.mode === 'timeseries' && ds.rows && ds.rows.length) {
      items.push({ type: 'line', ds: ds });
      return;
    }
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
    if (labelCol && valueCols.length) {
      items.push({ type: 'bar', ds: ds, labelCol: labelCol, valueCols: valueCols });
    }
  });

  // 5 张图时底部通栏优先放折线图：把第一个时序图移到最后
  if (items.length === 5) {
    var lineIdx = items.findIndex(function (it) { return it.type === 'line'; });
    if (lineIdx >= 0 && lineIdx !== items.length - 1) {
      var lineItem = items.splice(lineIdx, 1)[0];
      items.push(lineItem);
    }
  }

  // ── 图表排列：1~3 单列；4~6+ 两列；5 张时底部通栏 ──
  // 单列每张卡片至少 320px，双列至少 280px；总高超出时图表列内滚动，地图保持满高
  var n = items.length;
  var cols = 1, wideLast = false;
  if (n === 4) { cols = 2; }
  else if (n === 5) { cols = 2; wideLast = true; }
  else if (n >= 6) { cols = 2; }
  var rowMin = cols === 1 ? 320 : 280;
  chartCol.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0,1fr))';
  chartCol.style.gridAutoRows = 'minmax(' + rowMin + 'px, 1fr)';
  // 左栏宽度随图表数增加，单列至少 44%，保证折线图横向空间
  var leftPct = Math.max(cols === 1 ? 44 : 36, Math.min(54, 30 + 4 * Math.max(1, n)));
  main.style.setProperty('--ipage-left', leftPct + '%');

  items.forEach(function (item, idx) {
    var ds = item.ds;
    var card = el('div', 'card chart-card' + (wideLast && idx === n - 1 ? ' wide' : ''));
    if (wideLast && idx === n - 1) card.style.gridColumn = '1 / -1';
    var title = item.type === 'line'
      ? (ds.name || '时序数据') + ' · 随时间轴变化'
      : (ds.name || '数据') + ' · ' + item.valueCols.join(' / ');
    card.appendChild(el('h3', null, SitUtil.escapeHtml(title)));
    var chartEl = el('div', 'chart');
    chartEl.style.minHeight = (cols === 1 ? 240 : 200) + 'px';
    card.appendChild(chartEl);
    chartCol.appendChild(card);

    if (item.type === 'line') {
      // 传 timeline 配置；页面没有统一时间轴时运行时按全部桶静态展示（不会空白）
      SitChart.render(chartEl, {
        type: 'line', title: '',
        timeline: {
          mode: 'trend', bucketField: 'bucketKey',
          valueField: ds.valueField || 'value',
          categoryField: (ds.groupBy || [])[0] || '',
        },
        rows: ds.rows,
      });
    } else {
      SitChart.render(chartEl, {
        type: 'bar', title: '',
        xData: ds.rows.map(function (r) { return String(r[item.labelCol]); }),
        series: item.valueCols.map(function (c) {
          return { name: c, data: ds.rows.map(function (r) { return num(r[c]) || 0; }) };
        }),
      });
    }
  });

  // ── 地图：第一个含地理特征的数据集 ──
  var geoDs = datasets.filter(function (ds) {
    return ds.geoFeatures && (ds.geoFeatures.points.length || ds.geoFeatures.tracks.length || ds.geoFeatures.circles.length);
  })[0];
  if (geoDs) {
    var mapCard = el('div', 'card map-card');
    mapCard.appendChild(el('h3', null, SitUtil.escapeHtml(geoDs.name || '空间分布')));
    var mapEl = el('div', 'map');
    mapCard.appendChild(mapEl);
    main.appendChild(mapCard);
    var gf = geoDs.geoFeatures;
    SitMap.render(mapEl, {
      tracks: gf.tracks, points: gf.points, circles: gf.circles,
      fit: true, clusterPoints: true,
      timeline: !!tl,
    });
  } else {
    // 无地理数据：取消单屏固定高度与图表列内部滚动，图表平铺，页面随内容自然滚动
    main.style.gridTemplateColumns = '1fr';
    chartCol.style.gridTemplateColumns = 'repeat(auto-fit,minmax(360px,1fr))';
    chartCol.style.gridAutoRows = 'minmax(300px,auto)';
    chartCol.style.overflow = 'visible';
    screen.style.height = 'auto';
  }

  // ── 平铺区：明细表每页最多 10 行，超过由组件分页 ──
  var detailDs = datasets.filter(function (ds) { return ds.mode === 'detail' && ds.rows && ds.rows.length; })[0];
  if (detailDs) {
    var tableCard = el('div', 'card table-card');
    tableCard.appendChild(el('h3', null, SitUtil.escapeHtml(detailDs.name || '明细')));
    var tableEl = el('div');
    tableCard.appendChild(tableEl);
    root.appendChild(tableCard);
    var rows = detailDs.rows;
    SitTable.render(tableEl, {
      columns: (detailDs.columns || []).slice(0, 8),
      rows: rows,
      pageSize: 10,
    });
  }

  // ── 评估结论（评估产物模式专用；普通页面无该字段）──
  if (data.conclusion) {
    var conclusionCard = el('div', 'card text-card');
    conclusionCard.appendChild(el('h3', null, '评估结论'));
    conclusionCard.appendChild(el('p', null, SitUtil.escapeHtml(data.conclusion)));
    root.appendChild(conclusionCard);
  }

  // ── 结论 / 数据说明：向下平铺，不设滚动条 ──
  var textCard = el('div', 'card text-card');
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
    textCard.appendChild(el('p', null, line));
  });
  root.appendChild(textCard);

  // 时间轴占位：无标题、无高度、无卡片样式，控件由宿主浮层渲染
  root.appendChild(tlEl);

  SitApp.ready();
});
</script>
</body>
</html>
"""


def render_template_page(bundle: Dict[str, Any]) -> str:
    """返回确定性兜底 HTML（与 bundle 内容无关，运行时由数据驱动）。"""
    return _TEMPLATE
