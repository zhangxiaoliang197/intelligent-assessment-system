/**
 * situation-kit.js —— HTML Artifact 沙箱内渲染器（态势图排版架构 §5）。
 *
 * 运行在 iframe 沙箱中（无网络、无同源权限），职责：
 * 1. 监听父页 postMessage('sit:data') 获取产物数据（图表 option / 地图图层 / KPI 行数据 / 文本）；
 * 2. 按 data-sit 占位符挂载真实内容：
 *    chart → ECharts；map → Leaflet（瓦片 + 点/线/面/圆，gcoord WGS84→GCJ02）；
 *    kpi → 行数据聚合；narrative / narrative_chart / map_explanation → 父页预渲染的 HTML。
 * 仅承担渲染，不含任何业务数据；数据全部来自父页注入。
 */
(function () {
  'use strict';

  var state = null;           // 父页注入的数据
  var chartsRendered = {};    // chartId → echarts 实例（防重复挂载）
  var mapRendered = false;
  var mapInstance = null;     // Leaflet 地图实例（供二次 invalidateSize）
  var echartsInstances = [];

  // ── 工具 ──
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function toNum(v) {
    var n = Number(v);
    return isFinite(n) ? n : 0;
  }

  // 名称 → 颜色（与 GeoMap 同策略：简单 hash，同名同色）
  var PALETTE = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9254de', '#13c2c2', '#fa8c16'];
  function colorByName(name) {
    var hash = 0;
    name = String(name || '');
    for (var i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return PALETTE[Math.abs(hash) % PALETTE.length];
  }

  // ── 坐标转换（与 GeoMap 同口径：WGS84 → GCJ02，Leaflet 用 [lat, lng]）──
  function toLatLng(lng, lat) {
    var pt = [Number(lng) || 0, Number(lat) || 0];
    try {
      if (window.gcoord) {
        var r = window.gcoord.transform([pt[0], pt[1]], window.gcoord.WGS84, window.gcoord.GCJ02);
        pt = [r[0], r[1]];
      }
    } catch (e) { /* 转换失败按原值渲染 */ }
    return [pt[1], pt[0]];
  }

  // ── 文本槽位（父页已做 markdown 渲染 + DOMPurify 消毒）──
  function renderTexts() {
    var nodes = document.querySelectorAll('[data-sit="narrative"]');
    for (var i = 0; i < nodes.length; i++) {
      var part = nodes[i].getAttribute('data-part') || 'intro';
      nodes[i].innerHTML = part === 'intro' ? (state.narrative.introHtml || '') : '';
    }
    var exps = state.narrative.explanations || {};
    var expNodes = document.querySelectorAll('[data-sit="narrative_chart"]');
    for (var j = 0; j < expNodes.length; j++) {
      var ref = expNodes[j].getAttribute('data-ref');
      var text = exps[ref] || '';
      expNodes[j].innerHTML = text
        ? '<div class="sit-explain">' + text + '</div>'
        : '';
    }
    var mapExpNodes = document.querySelectorAll('[data-sit="map_explanation"]');
    for (var k = 0; k < mapExpNodes.length; k++) {
      var me = state.narrative.mapExplanationHtml || '';
      mapExpNodes[k].innerHTML = me ? '<div class="sit-explain">' + me + '</div>' : '';
    }
  }

  // ── KPI 指标卡（从注入行数据聚合，agg 与后端白名单一致）──
  function aggregate(rows, column, agg) {
    if (agg === 'count') return rows.length;
    var values = [];
    for (var i = 0; i < rows.length; i++) {
      var v = rows[i][column];
      var n = Number(v);
      if (v !== null && v !== undefined && v !== '' && isFinite(n)) values.push(n);
    }
    if (!values.length) return 0;
    var sum = values.reduce(function (a, b) { return a + b; }, 0);
    if (agg === 'sum') return sum;
    if (agg === 'avg') return sum / values.length;
    if (agg === 'max') return Math.max.apply(null, values);
    if (agg === 'min') return Math.min.apply(null, values);
    return 0;
  }
  function fmtNum(n) {
    if (n == null || !isFinite(n)) return '-';
    if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + ' 亿';
    if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + ' 万';
    return Math.abs(n) >= 100 ? Math.round(n).toLocaleString('zh-CN') : String(Math.round(n * 100) / 100);
  }
  function renderKpis() {
    var nodes = document.querySelectorAll('[data-sit="kpi"]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var ref = el.getAttribute('data-ref');
      var metrics = [];
      try { metrics = JSON.parse(el.getAttribute('data-metrics') || '[]'); } catch (e) { metrics = []; }
      var ds = (state.datasets || {})[ref];
      var rows = (ds && ds.rows) || [];
      if (!metrics.length) continue;
      var html = '<div class="sit-kpi-row">';
      for (var m = 0; m < metrics.length; m++) {
        var item = metrics[m];
        var value = aggregate(rows, item.column, item.agg);
        html += '<div class="sit-kpi"><div class="sit-kpi-label">' + esc(item.label) + '</div>'
          + '<div class="sit-kpi-value">' + fmtNum(value) + '</div></div>';
      }
      html += '</div>';
      el.innerHTML = html;
    }
  }

  // ── 图表（ECharts；option 为父页用全量数据重建后的完整配置）──
  // 图表槽最小高度：LLM 常用 200px 固定高，双轴/多类目图被压扁、轴标签侵入绘图区
  var CHART_MIN_H = 300;          // 常规图保底
  var CHART_MIN_H_DENSE = 360;    // 多类目（轴标签旋转）保底，给底部标签留足空间

  function categoryCount(option) {
    var xa = option && option.xAxis;
    if (Array.isArray(xa)) {
      for (var i = 0; i < xa.length; i++) {
        if (xa[i] && xa[i].type === 'category' && Array.isArray(xa[i].data)) return xa[i].data.length;
      }
      return 0;
    }
    return (xa && xa.type === 'category' && Array.isArray(xa.data)) ? xa.data.length : 0;
  }

  function ensureChartHeight(el, option) {
    var need = categoryCount(option) > 10 ? CHART_MIN_H_DENSE : CHART_MIN_H;
    if (el.clientHeight < need) el.style.height = need + 'px';
  }

  // 绘图区边距运行时兜底（与后端 chart_polish._polish_grid 同构，改动需同步）：
  // 历史报告的 option 未经后端 grid 规范化，top:100/bottom:'12%' 在矮容器内压扁
  // 绘图区、旋转日期标签侵入折线区，这里在 setOption 前做幂等钳制。
  function normalizeGridOption(option) {
    if (!option || typeof option !== 'object') return;
    var title = option.title;
    var titleItems = Array.isArray(title) ? title : (title && typeof title === 'object' ? [title] : []);
    var hasTitle = titleItems.some(function (t) { return t && t.text; });
    var legend = option.legend;
    var hasLegend = Array.isArray(legend)
      ? legend.some(function (x) { return x && typeof x === 'object'; })
      : (legend && typeof legend === 'object');
    var rotated = false;
    var xa = option.xAxis;
    var axes = Array.isArray(xa) ? xa : (xa && typeof xa === 'object' ? [xa] : []);
    axes.forEach(function (item) {
      if (item && (item.type === 'category' || item.type === undefined)
          && item.axisLabel && item.axisLabel.rotate) rotated = true;
    });
    var topCap = (hasTitle && hasLegend) ? 72 : (hasTitle ? 48 : 24);
    var bottomFloor = rotated ? 56 : 32;
    var grids;
    if (option.grid == null) { option.grid = {}; grids = [option.grid]; }
    else if (Array.isArray(option.grid)) grids = option.grid.filter(function (g) { return g && typeof g === 'object'; });
    else if (typeof option.grid === 'object') grids = [option.grid];
    else return;
    grids.forEach(function (g) {
      if (!g.containLabel) g.containLabel = true;
      if (typeof g.top !== 'number' || g.top > topCap) g.top = topCap;
      if (rotated && (typeof g.bottom !== 'number' || g.bottom < bottomFloor)) g.bottom = bottomFloor;
      else if (g.bottom == null) g.bottom = bottomFloor;
    });
  }

  function renderCharts() {
    if (!window.echarts) return;
    var nodes = document.querySelectorAll('[data-sit="chart"]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var ref = el.getAttribute('data-ref');
      if (chartsRendered[ref]) continue;
      var chart = (state.charts || {})[ref];
      if (!chart || !chart.option) continue;
      try {
        ensureChartHeight(el, chart.option);
        normalizeGridOption(chart.option);
        var inst = window.echarts.init(el);
        inst.setOption(chart.option);
        chartsRendered[ref] = inst;
        echartsInstances.push(inst);
      } catch (e) { /* 单图失败不影响整页 */ }
    }
  }

  // ── 地图（Leaflet：瓦片层 + 点/线/面/圆）──
  function addTiles(map) {
    var layers = state.tileLayers || [];
    for (var i = 0; i < layers.length; i++) {
      var cfg = layers[i];
      try {
        var opts = {
          opacity: cfg.opacity != null ? cfg.opacity : 1,
          minZoom: cfg.minZoom != null ? cfg.minZoom : 3,
          maxZoom: cfg.maxZoom != null ? cfg.maxZoom : 18,
          tms: !!cfg.tms,
          attribution: cfg.attribution || ''
        };
        if (cfg.subdomains) opts.subdomains = cfg.subdomains;
        window.L.tileLayer(cfg.urlTemplate, opts).addTo(map);
      } catch (e) { /* 单层失败跳过 */ }
    }
  }

  function renderMap() {
    if (mapRendered || !window.L) return;
    var nodes = document.querySelectorAll('[data-sit="map"]');
    if (!nodes.length) return;
    var el = nodes[0];
    mapRendered = true;
    var layer = state.mapLayer;
    if (!layer) return;

    var map = window.L.map(el, { zoomControl: true }).setView([35, 105], 4);
    mapInstance = map;
    addTiles(map);
    var bounds = [];

    // 标点（density=cluster/heavy 时走 markercluster 聚合，避免密集平铺）
    var points = layer.points || [];
    var useCluster = window.L.markerClusterGroup
      && (layer.density === 'cluster' || layer.density === 'heavy');
    var clusterGroup = useCluster ? window.L.markerClusterGroup({
      chunkedLoading: true, maxClusterRadius: 60,
      showCoverageOnHover: false, zoomToBoundsOnClick: true,
    }) : null;
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      if (p.lng == null || p.lat == null) continue;
      var ll = toLatLng(p.lng, p.lat);
      bounds.push(ll);
      var color = colorByName(p.name || p.city || p.label);
      var marker = window.L.circleMarker(ll, {
        radius: 4, color: color, weight: 1, fillColor: color, fillOpacity: 0.75,
      }).bindPopup(esc(p.name || p.city || p.label || ''));
      if (clusterGroup) {
        clusterGroup.addLayer(marker);
      } else {
        marker.addTo(map);
      }
    }
    if (clusterGroup) map.addLayer(clusterGroup);
    // 路线（后端 GeoRoute 契约字段为 points：[{lng,lat,name,...}]；
    // 兼容 coordinates/coords/waypoints 及数组元组写法）
    var routes = layer.routes || [];
    for (var r = 0; r < routes.length; r++) {
      var route = routes[r];
      var coords = (route.points || route.coordinates || route.coords || route.waypoints || [])
        .map(function (c) {
          var lng = c.lng != null ? c.lng : c[0];
          var lat = c.lat != null ? c.lat : c[1];
          if (lng == null || lat == null) return null;
          var g = toLatLng(lng, lat);
          bounds.push(g);
          return g;
        })
        .filter(function (c) { return c; });
      if (coords.length >= 2) {
        window.L.polyline(coords, {
          color: route.color || colorByName(route.name || route.routeId || ''), weight: 3, opacity: 0.8,
        }).addTo(map).bindPopup(esc(route.name || route.routeId || '路线'));
      }
    }
    // 区域
    var areas = layer.areas || [];
    for (var a = 0; a < areas.length; a++) {
      var area = areas[a];
      var ring = (area.coordinates || area.ring || [])
        .map(function (c) {
          var lng = c.lng != null ? c.lng : c[0];
          var lat = c.lat != null ? c.lat : c[1];
          if (lng == null || lat == null) return null;
          var g = toLatLng(lng, lat);
          bounds.push(g);
          return g;
        })
        .filter(function (c) { return c; });
      if (ring.length >= 3) {
        window.L.polygon(ring, {
          color: area.color || colorByName(area.name || ''), weight: 2, fillOpacity: 0.2,
        }).addTo(map).bindPopup(esc(area.name || '区域'));
      }
    }
    // 圆形区域
    var circles = layer.circles || [];
    for (var c = 0; c < circles.length; c++) {
      var ci = circles[c];
      if (ci.lng == null || ci.lat == null) continue;
      var cll = toLatLng(ci.lng, ci.lat);
      bounds.push(cll);
      window.L.circle(cll, {
        radius: Number(ci.radius) || 1000,
        color: ci.color || colorByName(ci.name || ''), weight: 2, fillOpacity: 0.15,
      }).addTo(map).bindPopup(esc(ci.name || ''));
    }

    if (bounds.length) {
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 12 });
    }
    setTimeout(function () { map.invalidateSize(); }, 200);
  }

  // ── 布局自检：上报 body 尺寸与槽位 0×0 计数，供父页识别"零布局白屏"并自愈 ──
  function postLayout() {
    try {
      var slots = document.querySelectorAll('[data-sit]');
      var zeroSlots = 0;
      for (var i = 0; i < slots.length; i++) {
        var r = slots[i].getBoundingClientRect();
        if (r.width === 0 && r.height === 0) zeroSlots++;
      }
      var body = document.body;
      window.parent.postMessage({
        type: 'sit:layout',
        bodyW: body ? body.scrollWidth : 0,
        bodyH: body ? body.scrollHeight : 0,
        slotCount: slots.length,
        zeroSlots: zeroSlots,
        renderedCharts: echartsInstances.length,
        mapRendered: mapRendered,
      }, '*');
    } catch (e) { }
  }

  function render() {
    if (!state) return;
    try { renderTexts(); } catch (e) { }
    try { renderKpis(); } catch (e) { }
    try { renderCharts(); } catch (e) { }
    try { renderMap(); } catch (e) { }
    // 内容注入后高度变化，主动上报一次（ResizeObserver 也会兜底）
    requestPostHeight();
    // 数据注入后的二次自适应：部分渲染器在容器首帧尺寸未定时初始化会塌缩，
    // 延迟重排一次图表与地图，规避零布局/瓦片灰块
    setTimeout(function () {
      for (var i = 0; i < echartsInstances.length; i++) {
        try { echartsInstances[i].resize(); } catch (e) { }
      }
      try { if (mapInstance) mapInstance.invalidateSize(); } catch (e) { }
    }, 350);
    // 布局自检三拍：覆盖同步注入、ECharts/Leaflet 异步绘制两个时点
    setTimeout(postLayout, 0);
    setTimeout(postLayout, 300);
    setTimeout(postLayout, 800);
  }

  // ── 高度自适应：量高 → postMessage 父页调整 iframe 高度 ──
  // 沙箱无同源权限，父页无法读 contentDocument，只能由 kit 主动上报
  var heightTimer = null;
  function postHeight() {
    try {
      var h = Math.max(
        document.body ? document.body.scrollHeight : 0,
        document.documentElement ? document.documentElement.scrollHeight : 0
      );
      if (h > 0) window.parent.postMessage({ type: 'sit:height', height: h }, '*');
    } catch (e) { }
  }
  function requestPostHeight() {
    clearTimeout(heightTimer);
    heightTimer = setTimeout(postHeight, 120);
  }
  // body 尺寸变化（文本/KPI 注入、图片加载、字体就绪）→ 防抖上报
  if (window.ResizeObserver && document.body) {
    new ResizeObserver(requestPostHeight).observe(document.body);
  }

  // 窗口尺寸变化时重排图表
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      for (var i = 0; i < echartsInstances.length; i++) {
        try { echartsInstances[i].resize(); } catch (e) { }
      }
    }, 150);
  });

  // 与父页握手：kit 就绪 → 请求注入数据。
  // vendor 脚本（echarts/leaflet）加载可能慢于父页兜底定时器，因此未收到数据前
  // 周期性重发 ready，直到父页回注 sit:data 为止（防握手竞态丢数据）。
  function requestReady() {
    try {
      var sitNodes = document.querySelectorAll('[data-sit]').length;
      var h1 = document.querySelector('h1');
      window.parent.postMessage({
        type: 'sit:ready',
        diag: {
          readyState: document.readyState,
          sitNodes: sitNodes,
          bodyChildren: document.body ? document.body.childElementCount : -1,
          h1Text: h1 ? h1.textContent.slice(0, 40) : '',
          hasEcharts: !!window.echarts,
          hasL: !!window.L,
        },
      }, '*');
    } catch (e) { }
  }
  var readyTimers = [0, 400, 1000, 2000, 3500, 5500];
  for (var t = 0; t < readyTimers.length; t++) {
    setTimeout(function () { if (!state) requestReady(); }, readyTimers[t]);
  }
  window.addEventListener('message', function (e) {
    var msg = e.data || {};
    if (msg.type === 'sit:data' && msg.payload) {
      state = msg.payload;
      render();
    }
  });

  // DOMContentLoaded 后握手；srcdoc 场景脚本位于 body 末尾，DOM 已就绪
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', requestReady);
  } else {
    requestReady();
  }
})();
