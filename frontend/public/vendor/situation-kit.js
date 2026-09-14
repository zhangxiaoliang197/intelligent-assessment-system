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
    addTiles(map);
    var bounds = [];

    // 标点
    var points = layer.points || [];
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      if (p.lng == null || p.lat == null) continue;
      var ll = toLatLng(p.lng, p.lat);
      bounds.push(ll);
      var color = colorByName(p.name || p.city || p.label);
      window.L.circleMarker(ll, {
        radius: 4, color: color, weight: 1, fillColor: color, fillOpacity: 0.75,
      }).addTo(map).bindPopup(esc(p.name || p.city || p.label || ''));
    }
    // 路线
    var routes = layer.routes || [];
    for (var r = 0; r < routes.length; r++) {
      var route = routes[r];
      var coords = (route.coordinates || route.coords || route.waypoints || [])
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

  function render() {
    if (!state) return;
    try { renderTexts(); } catch (e) { }
    try { renderKpis(); } catch (e) { }
    try { renderCharts(); } catch (e) { }
    try { renderMap(); } catch (e) { }
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
