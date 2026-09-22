/**
 * page-kit.js —— 智能交互页面（ipage）沙箱受限运行时。
 *
 * 运行在 iframe sandbox="allow-scripts" 中（无同源权限、CSP connect-src 'none'）：
 * 1. 与父页 postMessage 握手，接收 'ipage:data'（dataBundle + 瓦片配置）；
 * 2. 向业务页面暴露且仅暴露：SitApp / SitChart / SitMap / SitBus / SitUtil / SitTable；
 * 3. 封装 ECharts、Leaflet（含 gcoord WGS84→GCJ02、markercluster），业务代码
 *    无法直接触碰 echarts / L 全局对象，也不能发起任何网络请求。
 *
 * 业务页面唯一数据入口：SitApp.bootstrap(function (data) { ... })。
 */
(function () {
  'use strict';

  if (window.__PAGE_KIT__) return;   // 防重复注入
  window.__PAGE_KIT__ = true;

  // ────────────────────────────────────────────────────────────────
  // 内部状态
  // ────────────────────────────────────────────────────────────────
  var state = null;             // 父页注入的完整 payload
  var bootCallbacks = [];       // bootstrap 回调（数据到达前排队）
  var booted = false;
  var echartsInstances = [];    // 全部图表实例（resize / dispose 用）
  var chartByEl = [];           // [el, inst]，重渲染时先销毁旧实例
  var mapByEl = [];             // [el, mapApi]
  var tileLayers = [];

  // 专业态势配色：蓝为主，红/橙/绿/紫/青为辅
  var PALETTE = ['#1d4ed8', '#dc2626', '#d97706', '#059669', '#7c3aed', '#0891b2', '#be185d', '#65a30d'];
  var KIND_COLORS = {
    target: '#1d4ed8', threat: '#dc2626', base: '#059669', event: '#d97706', other: '#64748b',
    strike: '#dc2626', recon: '#d97706', facility: '#7c3aed',
  };
  var FACTION_COLORS = {
    '蓝方': '#1d4ed8', '红方': '#dc2626',
    // 数据源注解把阵营值规范化为英文键时同样吃语义色（与后端 field_resolver 口径一致）
    blue: '#1d4ed8', red: '#dc2626',
  };

  // 状态规范键 → 视觉（与后端 field_resolver.STATUS_KEYS 一一对应）。
  // 数据源注解把原始状态值映射到这些键时优先生效；未提供 statusKey 时走下方中文词匹配。
  var STATUS_STYLES = {
    destroyed: { color: '#94a3b8', overlayCross: true, dim: true },
    miss: { color: '#94a3b8', kinds: ['event_strike'] },
    critical: { badge: '#ef4444' },
    heavy: { badge: '#ea580c' },
    light: { badge: '#f59e0b' },
  };

  // 按系列名称取色：命中阵营名则用语义色（红方红、蓝方蓝），否则回退到 PALETTE 按序取色，
  // 保证无论 LLM 输出的 series 顺序如何，阵营颜色都正确。
  function factionColor(name, fallback) {
    return FACTION_COLORS[String(name || '').trim()] || fallback;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function toNum(v) { var n = Number(v); return isFinite(n) ? n : null; }
  function hashColor(name) {
    var hash = 0;
    name = String(name || '');
    for (var i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return PALETTE[Math.abs(hash) % PALETTE.length];
  }
  function kindColor(kind, fallbackName) {
    return KIND_COLORS[kind] || hashColor(fallbackName || kind || '');
  }

  // WGS84 → GCJ02（高德底图口径）；gcoord 缺失时按原值渲染
  function toLatLng(lng, lat) {
    var pt = [Number(lng) || 0, Number(lat) || 0];
    try {
      if (window.gcoord) {
        var r = window.gcoord.transform(pt, window.gcoord.WGS84, window.gcoord.GCJ02);
        pt = [r[0], r[1]];
      }
    } catch (e) { /* 转换失败按原值 */ }
    return [pt[1], pt[0]];
  }

  function resolveEl(el) {
    if (typeof el === 'string') return document.querySelector(el);
    return el;
  }

  // ────────────────────────────────────────────────────────────────
  // SitBus —— 组件联动事件总线
  // ────────────────────────────────────────────────────────────────
  var SitBus = (function () {
    var listeners = {};
    return {
      on: function (event, fn) {
        if (!event || typeof fn !== 'function') return;
        (listeners[event] = listeners[event] || []).push(fn);
      },
      off: function (event, fn) {
        if (!listeners[event]) return;
        listeners[event] = listeners[event].filter(function (f) { return f !== fn; });
      },
      emit: function (event, payload) {
        (listeners[event] || []).forEach(function (fn) {
          try { fn(payload); } catch (e) { reportError('联动事件 ' + event + ' 处理异常: ' + e.message); }
        });
      },
    };
  })();

  // ────────────────────────────────────────────────────────────────
  // SitUtil —— 数据工具
  // ────────────────────────────────────────────────────────────────
  function groupBy(rows, key) {
    var out = {};
    (rows || []).forEach(function (r) {
      var k = r[key] == null ? '未知' : String(r[key]);
      (out[k] = out[k] || []).push(r);
    });
    return out;
  }
  function sum(rows, key) {
    var s = 0, n = 0;
    (rows || []).forEach(function (r) { var v = toNum(r[key]); if (v !== null) { s += v; n++; } });
    return n ? s : 0;
  }
  function avg(rows, key) {
    var s = 0, n = 0;
    (rows || []).forEach(function (r) { var v = toNum(r[key]); if (v !== null) { s += v; n++; } });
    return n ? s / n : 0;
  }
  function countBy(rows, key) {
    var out = {};
    (rows || []).forEach(function (r) {
      var k = r[key] == null ? '未知' : String(r[key]);
      out[k] = (out[k] || 0) + 1;
    });
    return out;
  }
  function unique(rows, key) {
    var seen = {}, out = [];
    (rows || []).forEach(function (r) {
      var k = r[key] == null ? '' : String(r[key]);
      if (k && !seen[k]) { seen[k] = 1; out.push(r[key]); }
    });
    return out;
  }
  function fmtInt(n) {
    n = toNum(n);
    return n === null ? '-' : Math.round(n).toLocaleString('zh-CN');
  }
  function fmtNum(n, digits) {
    n = toNum(n);
    if (n === null) return '-';
    return n.toLocaleString('zh-CN', {
      minimumFractionDigits: digits == null ? 0 : digits,
      maximumFractionDigits: digits == null ? 2 : digits,
    });
  }
  function fmtPct(n, digits) {
    n = toNum(n);
    if (n === null) return '-';
    if (Math.abs(n) > 1) n = n / 100;      // 兼容 0-100 输入
    return (n * 100).toFixed(digits == null ? 1 : digits) + '%';
  }

  var SitUtil = {
    esc: esc, escapeHtml: esc,
    fmtInt: fmtInt, fmtNum: fmtNum, fmtPct: fmtPct,
    groupBy: groupBy, sum: sum, avg: avg, countBy: countBy, unique: unique,
  };

  // ────────────────────────────────────────────────────────────────
  // SitChart —— ECharts 高层封装
  // ────────────────────────────────────────────────────────────────
  function baseGrid(spec) {
    return { left: 56, right: 28, top: spec.title ? 46 : 30, bottom: spec.showDataZoom ? 64 : 42, containLabel: true };
  }
  function axisCommon() {
    return {
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      axisLabel: { color: '#475569' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    };
  }
  function legend(series) {
    return series.length > 1 ? {
      top: 8, right: 12, icon: 'roundRect', itemWidth: 12, itemHeight: 8,
      textStyle: { color: '#475569', fontSize: 12 },
    } : undefined;
  }
  function tooltip(extra) {
    return Object.assign({
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,.96)',
      borderColor: '#e2e8f0', textStyle: { color: '#1e293b', fontSize: 12 },
      confine: true,
    }, extra || {});
  }

  function buildOption(spec) {
    var type = spec.type;
    var option = { color: PALETTE, title: undefined, tooltip: undefined, grid: baseGrid(spec) };
    if (spec.title) {
      option.title = { text: spec.title, left: 12, top: 6, textStyle: { fontSize: 14, color: '#0f172a', fontWeight: 600 } };
    }
    var series = spec.series || [];

    if (type === 'bar') {
      var horizontal = !!spec.horizontal;
      var xAxis, yAxis, xData = spec.xData || [];
      if (!horizontal) {
        xAxis = Object.assign({ type: 'category', data: xData, axisLabel: { color: '#475569', interval: 0 } }, axisCommon());
        yAxis = Object.assign({ type: 'value', name: spec.yName || '' }, axisCommon());
      } else {
        xAxis = Object.assign({ type: 'value', name: spec.yName || '' }, axisCommon());
        yAxis = Object.assign({ type: 'category', data: xData.slice().reverse() }, axisCommon());
      }
      option.tooltip = tooltip();
      option.legend = legend(series);
      option.xAxis = xAxis;
      option.yAxis = yAxis;
      option.series = series.map(function (s, idx) {
        var data = s.data || [];
        if (horizontal) data = data.slice().reverse();
        if (spec.percent) {
          var totals = xData.map(function (_, i) {
            return series.reduce(function (acc, ss) { return acc + (toNum((ss.data || [])[i]) || 0); }, 0);
          });
          if (horizontal) totals = totals.slice().reverse();
          data = data.map(function (v, i) { return totals[i] ? +(v / totals[i] * 100).toFixed(2) : 0; });
        }
        return {
          name: s.name || ('系列' + (idx + 1)), type: 'bar', data: data,
          barMaxWidth: 34,
          itemStyle: {
            color: factionColor(s.name, PALETTE[idx % PALETTE.length]),
            borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
          },
          emphasis: { focus: 'series' },
          stack: spec.stack ? 'total' : undefined,
        };
      });
      if (spec.showDataZoom) {
        option.dataZoom = [
          { type: 'slider', height: 16, bottom: 14, borderColor: '#e2e8f0', fillerColor: 'rgba(29,78,216,.12)' },
          { type: 'inside' },
        ];
      }
      return option;
    }

    if (type === 'line') {
      option.tooltip = tooltip({ trigger: 'axis' });
      option.legend = legend(series);
      option.xAxis = Object.assign({ type: 'category', boundaryGap: false, data: spec.xData || [], axisLabel: { color: '#475569' } }, axisCommon());
      option.yAxis = Object.assign({ type: 'value', name: spec.yName || '' }, axisCommon());
      option.series = series.map(function (s, idx) {
        var color = factionColor(s.name, PALETTE[idx % PALETTE.length]);
        return {
          name: s.name || ('系列' + (idx + 1)), type: 'line', smooth: true,
          symbol: 'circle', symbolSize: 6, data: s.data || [],
          lineStyle: { width: 2.5, color: color },
          itemStyle: { color: color },
          areaStyle: series.length === 1 ? { opacity: 0.08 } : undefined,
          emphasis: { focus: 'series' },
        };
      });
      if (spec.showDataZoom) {
        option.dataZoom = [
          { type: 'slider', height: 16, bottom: 14, borderColor: '#e2e8f0', fillerColor: 'rgba(29,78,216,.12)' },
          { type: 'inside' },
        ];
      }
      return option;
    }

    if (type === 'pie') {
      var pieData = ((series[0] || {}).data || []).map(function (d, idx) {
        var item = (d && typeof d === 'object')
          ? { name: d.name, value: toNum(d.value) || 0 }
          : { name: String(d[0]), value: toNum(d[1]) || 0 };
        item.itemStyle = { color: factionColor(item.name, PALETTE[idx % PALETTE.length]) };
        return item;
      }).filter(function (d) { return d.value > 0; });
      option.grid = undefined;
      option.tooltip = tooltip({ trigger: 'item', formatter: '{b}: {c} ({d}%)' });
      option.legend = { orient: 'vertical', right: 10, top: 'middle', icon: 'circle', textStyle: { color: '#475569', fontSize: 12 } };
      option.series = [{
        name: (series[0] || {}).name || '占比', type: 'pie', radius: ['42%', '68%'],
        center: ['42%', '54%'], avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
        label: { color: '#475569', fontSize: 12 },
        data: pieData,
      }];
      return option;
    }

    if (type === 'radar') {
      option.grid = undefined;
      option.tooltip = { confine: true };
      option.legend = legend(series);
      option.radar = {
        indicator: (spec.indicators || []).map(function (n) { return { name: n, max: spec.max }; }),
        radius: '62%', center: ['50%', '55%'],
        axisName: { color: '#475569', fontSize: 12 },
        splitLine: { lineStyle: { color: '#e2e8f0' } },
        splitArea: { areaStyle: { color: ['#fff', '#f8fafc'] } },
      };
      option.series = [{
        type: 'radar',
        data: series.map(function (s, idx) {
          var color = factionColor(s.name, PALETTE[idx % PALETTE.length]);
          return {
            name: s.name, value: s.data || [],
            lineStyle: { color: color },
            itemStyle: { color: color },
            areaStyle: { color: color, opacity: 0.08 },
          };
        }),
      }];
      return option;
    }

    if (type === 'scatter') {
      option.tooltip = tooltip({
        trigger: 'item',
        formatter: function (p) {
          var d = p.data || [];
          return esc(p.seriesName) + '<br/>' + esc(d[2] != null ? d[2] : ('(' + d[0] + ', ' + d[1] + ')'));
        },
      });
      option.legend = legend(series);
      option.xAxis = Object.assign({ type: 'value', scale: true, name: spec.xName || '' }, axisCommon());
      option.yAxis = Object.assign({ type: 'value', scale: true, name: spec.yName || '' }, axisCommon());
      option.series = series.map(function (s, idx) {
        var color = factionColor(s.name, PALETTE[idx % PALETTE.length]);
        return {
          name: s.name || '分布', type: 'scatter', symbolSize: 9,
          data: (s.data || []).map(function (d) {
            return Array.isArray(d) ? d : [toNum(d.x), toNum(d.y), d.name];
          }),
          itemStyle: { color: color },
          emphasis: { focus: 'series' },
        };
      });
      return option;
    }

    // 未知类型：空 option，由调用方兜底
    return option;
  }

  var SitChart = {
    render: function (el, spec) {
      var node = resolveEl(el);
      if (!node || !window.echarts) { reportError('图表容器或 ECharts 运行时不可用'); return null; }
      spec = spec || {};
      var existing = chartByEl.filter(function (pair) { return pair[0] === node; })[0];
      var inst;
      if (existing) {
        inst = existing[1];
      } else {
        inst = window.echarts.init(node);
        chartByEl.push([node, inst]);
        echartsInstances.push(inst);
      }
      try {
        inst.setOption(buildOption(spec), true);
      } catch (e) { reportError('图表渲染失败: ' + e.message); }
      return {
        on: function (event, fn) {
          inst.on(event, function (params) {
            try {
              fn({
                name: params.name, seriesName: params.seriesName,
                value: params.value, data: params.data, dataIndex: params.dataIndex,
              });
            } catch (e) { reportError('图表事件处理异常: ' + e.message); }
          });
        },
        resize: function () { try { inst.resize(); } catch (e) { } },
      };
    },
  };

  // ────────────────────────────────────────────────────────────────
  // SitMap —— Leaflet 封装（瓦片托管 / 坐标转换 / 点航迹圈 / 联动）
  // ────────────────────────────────────────────────────────────────
  function addTiles(map) {
    (tileLayers || []).forEach(function (cfg) {
      try {
        var opts = {
          opacity: cfg.opacity != null ? cfg.opacity : 1,
          minZoom: cfg.minZoom != null ? cfg.minZoom : 3,
          maxZoom: cfg.maxZoom != null ? cfg.maxZoom : 18,
          tms: !!cfg.tms, attribution: cfg.attribution || '',
        };
        if (cfg.subdomains) opts.subdomains = cfg.subdomains;
        window.L.tileLayer(cfg.urlTemplate, opts).addTo(map);
      } catch (e) { /* 单层失败跳过 */ }
    });
  }

  function featureOf(layer, kind, name, props) {
    return { kind: kind, name: name || '', props: props || {} };
  }

  // ────────────────────────────────────────────────────────────────
  // SitIcons —— 军事实体象形符号（内联 SVG + L.divIcon）
  // 单位类别 unitKind：aircraft/base/threat/target/
  //                   event_strike/event_damage/event_recon/other
  // 数据库出现新单位类别时自动回退圆点，不影响渲染。
  // ────────────────────────────────────────────────────────────────
  var MAP_STYLE_ID = 'ipage-map-style';
  function ensureMapStyle() {
    if (document.getElementById(MAP_STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = MAP_STYLE_ID;
    style.textContent = [
      '.sit-unit{background:none;border:none}',
      '.sit-ic{border-radius:50%;border:1.6px solid #fff;box-sizing:border-box;position:relative;',
      '  box-shadow:0 1px 4px rgba(15,23,42,.45);}',
      '.sit-ic svg{width:100%;height:100%;display:block}',
      '.sit-ic-x{position:absolute;left:0;top:0;width:100%;height:100%}',
      '.sit-ic-badge{position:absolute;right:-2px;bottom:-2px;width:9px;height:9px;border-radius:50%;',
      '  border:1.5px solid #fff;box-sizing:content-box}',
      '.sit-unit.sit-hl .sit-ic{box-shadow:0 0 0 3px rgba(250,204,21,.95),0 1px 6px rgba(15,23,42,.5);',
      '  transform:scale(1.12);}',
      '.sit-unit .sit-ic{transition:transform .12s ease}',
      '.sit-ic-tip{background:rgba(255,255,255,.94)!important;border:1px solid #cbd5e1!important;',
      '  border-radius:5px!important;color:#0f172a!important;font-size:11px!important;',
      '  box-shadow:0 1px 4px rgba(15,23,42,.2)!important;padding:1px 6px!important;}',
      '.sit-ic-tip::before{display:none!important}',
      // 图例面板
      '.sit-legend{background:rgba(255,255,255,.94);border:1px solid #e2e8f0;border-radius:8px;',
      '  box-shadow:0 2px 10px rgba(15,23,42,.12);padding:8px 10px;font-size:12px;color:#1e293b;',
      '  max-width:210px;max-height:60%;overflow:auto;}',
      '.sit-legend-title{font-weight:600;font-size:12px;margin-bottom:5px;display:flex;',
      '  justify-content:space-between;align-items:center;cursor:pointer;user-select:none;}',
      '.sit-legend-title .sit-legend-toggle{color:#64748b;font-size:11px}',
      '.sit-legend-group{margin-top:5px;padding-top:5px;border-top:1px dashed #e2e8f0}',
      '.sit-legend-row{display:flex;align-items:center;gap:7px;padding:2px 0;white-space:nowrap}',
      '.sit-legend-sw{width:20px;height:20px;flex:none;display:inline-flex;align-items:center;justify-content:center}',
      '.sit-legend-sw svg{width:20px;height:20px}',
      '.sit-legend-line{width:22px;height:0;border-top-style:solid;flex:none;margin:0 2px}',
      '.sit-legend-circle{width:16px;height:16px;border-radius:50%;flex:none;margin:0 3px}',
      // 时间轴播放条（内置播放器）
      '.sit-playback{background:rgba(255,255,255,.94);border:1px solid #e2e8f0;border-radius:8px;',
      '  box-shadow:0 2px 10px rgba(15,23,42,.12);padding:6px 9px;display:flex;align-items:center;',
      '  gap:8px;font-size:12px;color:#1e293b;max-width:min(420px,72vw);}',
      '.sit-playback .sit-pb-btn{border:1px solid #cbd5e1;background:#fff;color:#334155;border-radius:5px;',
      '  padding:2px 8px;cursor:pointer;font-size:12px;line-height:18px;white-space:nowrap;}',
      '.sit-playback .sit-pb-btn:hover{background:#f1f5f9}',
      '.sit-playback .sit-pb-range{flex:1;min-width:90px;accent-color:#1d4ed8;cursor:pointer}',
      '.sit-playback .sit-pb-time{color:#475569;white-space:nowrap;font-variant-numeric:tabular-nums}',
    ].join('');
    document.head.appendChild(style);
  }

  // SVG 内部图形（viewBox 0 0 24 24，白色绘于阵营色圆底上）
  var SIT_SHAPES = {
    fighter: '<path fill="#fff" d="M12 2c.8 3 1.6 7 2 10.5l7 4.3c.3.2 0 .8-.5.7L14 16v3.2l2.6 2c.3.2.1.8-.3.7L12 21l-4.3.9c-.4.1-.6-.5-.3-.7L10 19.2V16l-6.5 1.5c-.5.1-.8-.5-.5-.7l7-4.3C10.4 9 11.2 5 12 2z"/>',
    awacs: '<path fill="#fff" d="M12 2c.8 3 1.6 7 2 10.5l7 4.3c.3.2 0 .8-.5.7L14 16v3.2l2.6 2c.3.2.1.8-.3.7L12 21l-4.3.9c-.4.1-.6-.5-.3-.7L10 19.2V16l-6.5 1.5c-.5.1-.8-.5-.5-.7l7-4.3C10.4 9 11.2 5 12 2z"/><ellipse cx="12" cy="7.6" rx="4.8" ry="1.5" fill="none" stroke="#fff" stroke-width="1.4"/>',
    recon: '<path fill="#fff" d="M12 2c.8 3 1.6 7 2 10.5l7 4.3c.3.2 0 .8-.5.7L14 16v3.2l2.6 2c.3.2.1.8-.3.7L12 21l-4.3.9c-.4.1-.6-.5-.3-.7L10 19.2V16l-6.5 1.5c-.5.1-.8-.5-.5-.7l7-4.3C10.4 9 11.2 5 12 2z"/><ellipse cx="12" cy="15.4" rx="2.5" ry="1.3" fill="none" stroke="#fff" stroke-width="1.4"/>',
    bomber: '<path fill="#fff" d="M12 2c.8 3 1.6 7 2 10.5l7 4.3c.3.2 0 .8-.5.7L14 16v3.2l2.6 2c.3.2.1.8-.3.7L12 21l-4.3.9c-.4.1-.6-.5-.3-.7L10 19.2V16l-6.5 1.5c-.5.1-.8-.5-.5-.7l7-4.3C10.4 9 11.2 5 12 2z"/><circle cx="8.3" cy="13.6" r="1.25" fill="#fff"/><circle cx="15.7" cy="13.6" r="1.25" fill="#fff"/>',
    base: '<g fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 19.5 12 7.5l7.5 12"/><path d="M8 19.5v-4.3h8v4.3"/><path d="M4.5 19.5h15"/></g>',
    sam: '<g fill="none" stroke="#fff" stroke-linecap="round" stroke-linejoin="round"><path stroke-width="1.8" d="M5.5 20h13M12 20V10.6"/><path stroke-width="2.3" d="M11.3 11.4 18.6 4"/><path d="M11.3 11.4l-2.7-.3M11.3 11.4l-.3-2.7"/></g><path fill="#fff" d="M18.6 4 15.4 4.7l2.5 2.5z"/>',
    radar: '<g fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round"><path d="M6.8 17.2A7 7 0 0 1 17.2 17.2"/><path d="M9.4 17.2a3.4 3.4 0 0 1 5.2 0"/><path d="M12 17.2 16.4 11.4"/></g><circle cx="12" cy="18.6" r="1.3" fill="#fff"/>',
    coastal: '<rect x="3.4" y="14" width="11.6" height="4.6" rx=".9" fill="#fff"/><g fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round"><path d="M10 14 17.4 5.8"/></g><path fill="#fff" d="M17.4 5.8 14.4 6.5l2.3 2.3z"/><g fill="#fff"><circle cx="6.8" cy="19.6" r="1.2"/><circle cx="11.8" cy="19.6" r="1.2"/></g>',
    flag: '<path fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" d="M7.5 3.2V20.6"/><path fill="#fff" d="M7.5 4H18l-2.6 3L18 10H7.5z"/>',
    depot: '<g fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 19 12 9.5 19.5 19"/><path d="M7 19v-4.5h10V19"/></g><circle cx="12" cy="7.3" r="1.4" fill="#fff"/>',
    fuel: '<g fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9.6 4.4h4.8M10.6 4.4v15.2h2.8V4.4M9.4 8.6h5.2M9.4 15.6h5.2"/></g>',
    anchor: '<g fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4.6" r="1.6"/><path d="M12 6.2V20M8 8.6h8M5.6 12.8a6.4 6.4 0 0 0 12.8 0M10 18l2 2 2-2"/></g>',
    runway: '<g fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round"><path d="M4 20 20 4M6.2 21.4 22 5.6"/><path stroke-width="2.2" d="M9.2 14.8l1.6-1.6M12 12l1.6-1.6M14.8 9.2l1.6-1.6"/></g>',
    tower: '<g fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.6 6.5 20M12 3.6 17.5 20M8.6 13.6h6.8"/><path d="M8.6 6.8A5 5 0 0 0 5.6 10.8M15.4 6.8a5 5 0 0 1 3 4"/></g>',
    boom: '<path fill="#fff" d="m12 2.6 2 6 5.8-3-2.9 6 5.6 2-6 1.1 2.1 5.7-5.6-2.7L10 23l-1.1-6.1-6 2.4 2.3-5.5-4-2.7 5.7-1L6.4 3.6l5.3 3z"/>',
    cross: '<path fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" d="M6.2 6.2 17.8 17.8M17.8 6.2 6.2 17.8"/>',
    magnifier: '<g fill="none" stroke="#fff" stroke-width="2.1" stroke-linecap="round"><circle cx="10.6" cy="10.6" r="5.4"/><path d="m14.6 14.6 4.4 4.4"/></g>',
    ring: '<g fill="none" stroke="#fff" stroke-width="1.8"><circle cx="12" cy="12" r="6.4"/><circle cx="12" cy="12" r="2.2" fill="#fff" stroke="none"/><path d="M12 2.6v3M12 18.4v3M2.6 12h3M18.4 12h3"/></g>',
    dot: '<circle cx="12" cy="12" r="3.4" fill="#fff"/>',
  };

  var EVENT_COLORS = {
    event_strike: '#ea580c', event_damage: '#dc2626', event_recon: '#0891b2',
  };
  var BADGE_COLORS = {
    // 受损/压制 → 琥珀；中损 → 橙；重损 → 红
    light: '#f59e0b', heavy: '#ea580c', critical: '#ef4444',
  };

  function hasText(s, kw) { return String(s || '').indexOf(kw) >= 0; }

  function aircraftShapeOf(cat) {
    if (hasText(cat, '预警')) return 'awacs';
    if (hasText(cat, '侦察')) return 'recon';
    if (hasText(cat, '轰炸')) return 'bomber';
    return 'fighter';
  }

  function targetShapeOf(cat) {
    if (hasText(cat, '雷达')) return 'radar';
    if (hasText(cat, '岸舰')) return 'coastal';
    if (hasText(cat, '防空') || hasText(cat, '导弹阵地')) return 'sam';
    if (hasText(cat, '指挥')) return 'flag';
    if (hasText(cat, '弹药')) return 'depot';
    if (hasText(cat, '燃油') || hasText(cat, '油库')) return 'fuel';
    if (hasText(cat, '港')) return 'anchor';
    if (hasText(cat, '跑道') || hasText(cat, '机场')) return 'runway';
    if (hasText(cat, '通信') || hasText(cat, '中继')) return 'tower';
    return 'ring';
  }

  // 旧 point kind（target/threat/base/event）→ unitKind 兼容映射
  function normalizeUnitKind(u) {
    var k = String(u.unitKind || '').trim();
    if (k) return k;
    k = String(u.kind || '').trim();
    if (k === 'event') return 'event_strike';
    if (['aircraft', 'base', 'threat', 'target', 'facility',
         'event_strike', 'event_damage', 'event_recon'].indexOf(k) >= 0) return k;
    return 'other';
  }

  // 解析单位视觉：shape / color / 中文类别名 / 状态叠加
  // forLegend=true 时忽略状态变色/角标（图例按类别合并，状态差异只在地图符号上体现）
  // 数据源注解优先：units[].symbol 直驱符号注册表、units[].factionColor 直驱配色、
  // units[].statusKey 直驱状态视觉；三者缺失时一律回落原有推断逻辑（存量页面零变化）。
  function resolveUnitVisual(u, forLegend) {
    var kind = normalizeUnitKind(u);
    var type = String(u.type || '');
    var faction = String(u.faction || '').trim();
    var status = String(u.status || '').trim();
    var customColor = String(u.factionColor || '').trim();
    var shape, color, label;

    if (kind === 'aircraft') {
      shape = aircraftShapeOf(type);
      label = type || '战机';
      color = customColor || FACTION_COLORS[faction] || KIND_COLORS.threat;
    } else if (kind === 'base') {
      shape = 'base'; label = '基地';
      color = customColor || FACTION_COLORS[faction] || '#059669';
    } else if (kind === 'threat') {
      if (hasText(type, '雷达')) shape = 'radar';
      else if (hasText(type, '岸舰')) shape = 'coastal';
      else shape = 'sam';
      label = type || '防空单位';
      color = customColor || FACTION_COLORS[faction] || '#dc2626';
    } else if (kind === 'facility') {
      // 注解 entityKind=ground_facility 的默认视觉：地面设施用环+紫，区分于防空单位/打击目标
      shape = 'ring'; label = type || '地面设施';
      color = customColor || FACTION_COLORS[faction] || KIND_COLORS.facility;
    } else if (kind === 'target') {
      shape = targetShapeOf(type);
      label = type || '打击目标';
      color = customColor || '#d97706';
    } else if (kind === 'event_strike') {
      shape = 'boom'; label = '打击事件'; color = customColor || EVENT_COLORS.event_strike;
    } else if (kind === 'event_damage') {
      if (hasText(status, '坠毁') || hasText(type, '击落') || hasText(type, '坠毁')) {
        shape = 'cross'; label = '坠毁';
      } else {
        shape = aircraftShapeOf(type); label = status ? status + '战损' : '战损事件';
      }
      color = customColor || FACTION_COLORS[faction] || EVENT_COLORS.event_damage;
    } else if (kind === 'event_recon') {
      shape = 'magnifier'; label = '侦察发现'; color = customColor || EVENT_COLORS.event_recon;
    } else {
      shape = 'dot'; label = type || '其它单位'; color = customColor || '#64748b';
    }

    // 注解指定的象形符号直驱（须在注册表内，否则继续用上面的推断结果）
    var customShape = String(u.symbol || '').trim();
    if (customShape && SIT_SHAPES[customShape]) shape = customShape;

    // 状态叠加：摧毁 → 灰底+叉；受损/压制/维修 → 角标
    // 图例按类别合并，不应用状态变色
    var badge = null, overlayCross = false, dim = false;
    var statusStyle = u.statusKey ? STATUS_STYLES[String(u.statusKey).trim()] : null;
    var styleApplies = !!statusStyle
      && (!statusStyle.kinds || statusStyle.kinds.indexOf(kind) >= 0);
    if (forLegend) {
      // 坠毁是独立图义，保留叉形；其余状态一律按类别本色出图例
      if (kind === 'event_damage' && shape === 'cross') { overlayCross = true; }
    } else if (styleApplies) {
      // 注解状态键优先
      if (statusStyle.color) color = statusStyle.color;
      badge = statusStyle.badge || null;
      overlayCross = !!statusStyle.overlayCross;
      dim = !!statusStyle.dim;
    } else if (hasText(status, '摧毁')) { overlayCross = true; dim = true; color = '#94a3b8'; }
    else if (kind === 'event_strike' && hasText(status, '未命中')) { color = '#94a3b8'; }
    else if (hasText(status, '重损')) badge = BADGE_COLORS.critical;
    else if (hasText(status, '中损') || hasText(status, '受损') || hasText(status, '压制')) badge = BADGE_COLORS.heavy;
    else if (hasText(status, '轻损') || hasText(status, '战损') || hasText(status, '维修')) badge = BADGE_COLORS.light;

    return { kind: kind, shape: shape, color: color, label: label,
             badge: badge, overlayCross: overlayCross, dim: dim };
  }

  function unitIconHtml(v, size, heading) {
    var rot = toNum(heading);
    var svg = '<svg viewBox="0 0 24 24" style="' + (rot !== null ? 'transform:rotate(' + rot + 'deg)' : '') + '">'
      + (SIT_SHAPES[v.shape] || SIT_SHAPES.dot) + '</svg>';
    var badge = v.badge ? '<span class="sit-ic-badge" style="background:' + v.badge + '"></span>' : '';
    var cross = v.overlayCross ? '<svg class="sit-ic-x" viewBox="0 0 24 24">' + SIT_SHAPES.cross + '</svg>' : '';
    return '<div class="sit-ic" style="width:' + size + 'px;height:' + size + 'px;background:' + v.color
      + (v.dim ? ';opacity:.7' : '') + '">' + svg + cross + badge + '</div>';
  }

  function createUnitIcon(L, u, opts) {
    opts = opts || {};
    var size = opts.size || 26;
    var v = resolveUnitVisual(u);
    var heading = opts.heading != null ? opts.heading : u.heading;
    return L.divIcon({
      className: 'sit-unit',
      html: unitIconHtml(v, size, heading),
      iconSize: [size, size], iconAnchor: [size / 2, size / 2],
    });
  }

  function unitPopupHtml(u, v) {
    var rows = [];
    if (u.faction) rows.push(['阵营', u.faction]);
    if (v.label && v.label !== u.name) rows.push(['类型', v.label]);
    if (u.status) rows.push(['状态', u.status]);
    if (u.time) rows.push(['时间', u.time]);
    var html = '<b>' + esc(u.name || '军事单位') + '</b>';
    rows.forEach(function (r) { html += '<br/>' + esc(r[0]) + '：' + esc(r[1]); });
    return html;
  }

  // ── 图例：按地图上实际出现的类别自动生成 ──
  function buildLegendItems(spec) {
    var seen = {}, units = [];
    function addUnit(u) {
      var v = resolveUnitVisual(u, true);
      var key = v.kind + '|' + v.shape + '|' + v.color + '|' + v.label;
      if (!seen[key]) { seen[key] = 1; units.push({ v: v }); }
    }
    (spec.units || spec.points || []).forEach(addUnit);
    (spec.tracks || []).forEach(function (t) {
      // 航迹终点即当前机位，纳入符号图例
      var last = (t.points || [])[(t.points || []).length - 1];
      if (last) addUnit({ unitKind: 'aircraft', type: t.category, faction: t.faction,
                          factionColor: t.factionColor, symbol: t.symbol,
                          name: t.name, heading: last.heading });
    });
    var trackColors = {};
    (spec.tracks || []).forEach(function (t) {
      var c = t.factionColor || FACTION_COLORS[t.faction] || hashColor(t.name);
      trackColors[t.faction || '其它'] = c;
    });
    var rangeItems = [];
    function addRange(label, faction, dashed, color) {
      var key = label + '|' + (faction || '');
      if (seen[key]) return;
      seen[key] = 1;
      rangeItems.push({
        label: label,
        color: color || FACTION_COLORS[faction] || (dashed ? '#d97706' : '#dc2626'),
        dashed: !!dashed,
      });
    }
    (spec.circles || []).forEach(function (c) {
      var isRecon = c.kind === 'recon' || (c.rangeType || '').indexOf('侦察') >= 0;
      addRange(c.rangeType || (c.kind === 'strike' ? '打击范围' : '侦察范围'),
               c.faction, isRecon, c.factionColor);
    });
    // 动态能力圈（随飞机运动）单独出图例，与静态范围圈区分
    if (spec.playback) {
      var pb = spec.playback === true ? {} : (spec.playback || {});
      var mode = pb.radius || 'both';
      (spec.tracks || []).forEach(function (t) {
        var sv = toNum(t.strikeRadiusKm), rv = toNum(t.reconRadiusKm);
        if (mode !== 'recon' && sv !== null && sv > 0) {
          addRange('打击范围（动态）', t.faction, false, t.factionColor);
        }
        if (mode !== 'strike' && rv !== null && rv > 0) {
          addRange('侦察范围（动态）', t.faction, true, t.factionColor);
        }
      });
    }
    return { units: units, trackColors: trackColors, ranges: rangeItems };
  }

  function addLegendControl(L, map, spec) {
    var data = buildLegendItems(spec);
    if (!data.units.length && !data.ranges.length && !Object.keys(data.trackColors).length) return;
    var LegendCtl = L.Control.extend({
      options: { position: 'bottomright' },
      onAdd: function () {
        var box = L.DomUtil.create('div', 'sit-legend');
        var unitSw = function (v) {
          return '<span class="sit-legend-sw" style="background:transparent">'
            + '<svg viewBox="0 0 24 24"><g transform="translate(2,2) scale(0.84)">'
            + '<circle cx="12" cy="12" r="11.4" fill="' + v.color + '" stroke="#fff" stroke-width="1.6"/>'
            + (SIT_SHAPES[v.shape] || SIT_SHAPES.dot) + '</g></svg></span>';
        };
        var rows = '';
        data.units.forEach(function (it) {
          rows += '<div class="sit-legend-row">' + unitSw(it.v) + '<span>' + esc(it.v.label) + '</span></div>';
        });
        var trackRows = Object.keys(data.trackColors).map(function (name) {
          return '<div class="sit-legend-row"><span class="sit-legend-line" style="border-top:3px solid '
            + data.trackColors[name] + '"></span><span>' + esc(name === '其它' ? '航迹' : name + '航迹')
            + '</span></div>';
        }).join('');
        var rangeRows = data.ranges.map(function (r) {
          return '<div class="sit-legend-row"><span class="sit-legend-circle" style="background:'
            + r.color + '22;border:1.6px ' + (r.dashed ? 'dashed' : 'solid') + ' ' + r.color
            + '"></span><span>' + esc(r.label) + '</span></div>';
        }).join('');
        box.innerHTML =
          '<div class="sit-legend-title"><span>图例</span>'
          + '<span class="sit-legend-toggle">收起 ▼</span></div>'
          + '<div class="sit-legend-body">' + rows
          + (trackRows ? '<div class="sit-legend-group">' + trackRows + '</div>' : '')
          + (rangeRows ? '<div class="sit-legend-group">' + rangeRows + '</div>' : '')
          + '</div>';
        var titleEl = box.querySelector('.sit-legend-title');
        var bodyEl = box.querySelector('.sit-legend-body');
        var toggleEl = box.querySelector('.sit-legend-toggle');
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.disableScrollPropagation(box);
        titleEl.addEventListener('click', function () {
          var hidden = bodyEl.style.display === 'none';
          bodyEl.style.display = hidden ? '' : 'none';
          toggleEl.textContent = hidden ? '收起 ▼' : '展开 ▲';
        });
        return box;
      },
    });
    var ctl = new LegendCtl();
    map.addControl(ctl);
    return ctl;
  }

  // 清除地图上一次渲染的所有业务图层（单位/航迹/范围圈/图例/聚合组），保留底图与视图
  function clearBusinessLayers(map, api) {
    if (!map || !api || !api._layers) return;
    var ly = api._layers;
    try {
      (ly.featureLayers || []).forEach(function (item) {
        try { map.removeLayer(item.layer); } catch (e) { }
      });
      ly.featureLayers = [];
      (ly.trackLines || []).forEach(function (l) { try { map.removeLayer(l); } catch (e) { } });
      ly.trackLines = [];
      (ly.startMarkers || []).forEach(function (m) { try { map.removeLayer(m); } catch (e) { } });
      ly.startMarkers = [];
      if (ly.cluster) { try { map.removeLayer(ly.cluster); } catch (e) { } ly.cluster = null; }
      if (ly.legendControl) { try { map.removeControl(ly.legendControl); } catch (e) { } ly.legendControl = null; }
      // 播放器需先销毁：停止计时器并移除动态能力圈/扫掠走廊/播放条
      if (ly.playback) { try { ly.playback.destroy(); } catch (e) { } ly.playback = null; }
    } catch (e) {
      reportError('地图图层清理异常: ' + (e && e.message));
    }
  }

  // ────────────────────────────────────────────────────────────────
  // 时间轴回放：内置播放器 + 动态能力圈 + turf 扫掠留痕
  //
  // 由 spec.playback 开启（缺省时行为与历史版本完全一致）：
  //   playback: { speed, interval, radius:'strike'|'recon'|'both',
  //               trail:true, trailSteps:16, showBar:true, dayNormalize:auto }
  // 开启后**不再预画整条航迹**（静态 polyline/起点点/终点图标全部由本播放器接管）：
  //   1. 每个在空架次画一个飞机图标（按机型象形符号 + 机头朝航向）随播放移动；
  //   2. 已飞航迹从起点渐进延长——飞机到哪航迹画到哪，不走完整条不出现；
  //   3. 能力圈圆心 = 该机当前位置（半径取机型定值）；扫掠留痕 = 已飞航段
  //      的 turf.buffer 走廊，从起飞累积到当前时刻（拖动回退随之收缩），不预展示全程。
  // 日内归一化：多架次真实日期分散在多个自然日时，按"当日 0 点起的毫秒数"把
  // 全部航迹叠加到同一虚拟日演示（跨 >1 自然日且 ≥2 条航迹自动启用，
  // cfg.dayNormalize 可显式 true/false 覆盖）；播放轴时间按"虚拟基准日（最早真实
  // 日期）+ 日内毫秒"显示完整年月日时分秒，航迹弹窗仍显示真实日期（数据不篡改）。
  // 生命周期：当前时刻早于首点（未出动）或晚于末点（已返航）→ 该架次不画图标不留航迹、
  // 不画圈不留带，已创建的图层即时从地图移除（"有多少在空飞机就有多少圈"）。
  // 播放条：播放/暂停、进度拖动、完整时间标签、0.5×/1×/2×/4× 倍速、重置。
  // ────────────────────────────────────────────────────────────────

  function lerp(a, b, r) { return a + (b - a) * r; }

  // 航向插值：按最短弧跨越 0/360 边界
  function lerpHeading(a, b, r) {
    if (a === null) return b;
    if (b === null) return a;
    var d = ((b - a + 540) % 360) - 180;
    return (a + d * r + 360) % 360;
  }

  // 时间字符串 → 毫秒（空值/非法值返回 null）
  function parseTime(s) {
    if (s === null || s === undefined || s === '') return null;
    var v = Date.parse(String(s).replace(' ', 'T'));
    return isFinite(v) ? v : null;
  }

  // 当日 0 点（本地时区）的毫秒时刻，用于日内归一化
  function dayStartMs(v) {
    var d = new Date(v);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }

  // 毫秒 → YYYY-MM-DD HH:MM:SS（本地时区，播放条时间标签用）
  function fmtDateTime(ms) {
    var v = toNum(ms);
    if (v === null) return '—';
    var d = new Date(v);
    function p2(x) { return (x < 10 ? '0' : '') + x; }
    return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate())
      + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes()) + ':' + p2(d.getSeconds());
  }

  // 航迹线宽随缩放自适应（静态航迹与回放渐进航迹共用同一档位）：
  // 全景低倍用细线避免几十条航迹焊成线团，放大到城市级再加粗
  function trackWeight(z) {
    return z <= 7 ? 1.6 : (z <= 9 ? 2.2 : 3);
  }

  // 轻量更新飞机图标机头朝向：直接改写内层 <svg> 的 transform，
  // 避免逐帧重建 divIcon 造成的 DOM 抖动与开销；返回新的朝向缓存值
  function applyHeading(marker, heading, prev) {
    var h = toNum(heading);
    if (h === null || h === prev) return prev;
    var el = marker && marker.getElement ? marker.getElement() : null;
    var svg = el && el.querySelector ? el.querySelector('svg') : null;
    if (svg) svg.style.transform = 'rotate(' + h + 'deg)';
    return h;
  }

  // turf 几何 → Leaflet latlngs（WGS84 → GCJ02 与其它图层口径一致）
  function turfToLatLngs(geom) {
    if (!geom) return null;
    function ring(coords) {
      return coords.map(function (c) { return toLatLng(c[0], c[1]); });
    }
    if (geom.type === 'Polygon') return geom.coordinates.map(ring);
    if (geom.type === 'MultiPolygon') {
      var out = [];
      geom.coordinates.forEach(function (poly) {
        poly.forEach(function (r) { out.push(ring(r)); });
      });
      return out;
    }
    return null;
  }

  function createPlayback(L, map, spec, api) {
    var cfg = spec.playback === true ? {} : (spec.playback || {});
    var tracks = (spec.tracks || []).filter(function (t) { return (t.points || []).length >= 2; });
    if (!tracks.length) return null;

    var mode = cfg.radius || 'both';
    var wantStrike = mode !== 'recon';
    var wantRecon = mode !== 'strike';
    var wantTrail = cfg.trail !== false && !!window.turf;
    var steps = Math.max(4, toNum(cfg.trailSteps) || 16);
    var interval = Math.max(80, toNum(cfg.interval) || 500);
    var THROTTLE = 250;   // 扫掠多边形重算节流（turf.buffer 基于 JSTS，逐帧调用会卡顿）
    // 倍速档位（播放条按钮循环切换）；初始值取 cfg.speed 最接近的一档
    var SPEEDS = [0.5, 1, 2, 4];
    var wantSpeed = Math.max(0.25, toNum(cfg.speed) || 1);
    var speedIdx = 0;
    SPEEDS.forEach(function (s, i) {
      if (Math.abs(s - wantSpeed) < Math.abs(SPEEDS[speedIdx] - wantSpeed)) speedIdx = i;
    });
    var speed = SPEEDS[speedIdx];
    function speedLabel(v) { return (v === Math.floor(v) ? String(v) : v.toFixed(1)) + '×'; }

    // 逐架次预解析时间戳，避免播放中反复 Date.parse
    var items = [];
    tracks.forEach(function (t) {
      var pts = t.points || [];
      var ts = pts.map(function (p) { return parseTime(p.time); });
      var hasTime = ts.some(function (v) { return v !== null; });
      var defs = [];
      var strike = wantStrike ? toNum(t.strikeRadiusKm) : null;
      var recon = wantRecon ? toNum(t.reconRadiusKm) : null;
      // 半径必须为正：0/负值代表该机型无此能力，画出来是无意义的零半径圆
      if (strike !== null && strike > 0) defs.push({ r: strike, kind: 'strike' });
      if (recon !== null && recon > 0) defs.push({ r: recon, kind: 'recon' });
      items.push({ track: t, pts: pts, ts: ts, hasTime: hasTime, defs: defs, slots: [],
                   vis: { plane: null, line: null, rot: null, weight: null } });
    });

    // ── 日内归一化（auto + cfg.dayNormalize 可覆盖）──
    // 多架次真实日期分散在多个自然日时，同轴播放会出现"同一时刻仅 1 架在空"，
    // 故把全部航迹按"当日 0 点起的毫秒数"叠加到同一虚拟日演示。
    var daySet = {};
    items.forEach(function (it) {
      it.ts.forEach(function (v) {
        if (v !== null) daySet[dayStartMs(v)] = 1;
      });
    });
    var dayCount = Object.keys(daySet).length;
    var dayNorm = cfg.dayNormalize === true ? true
      : cfg.dayNormalize === false ? false
        : (dayCount > 1 && items.length >= 2);

    // 生效时刻 et：归一化时为"当日 0 点起毫秒"（跨零点航迹累加一天保持单调递增，
    // 避免插值倒退），否则为真实毫秒；posAt/axis/airborneAt 统一使用 et
    items.forEach(function (it) {
      if (dayNorm) {
        var carry = 0, prev = null;
        it.et = it.ts.map(function (v) {
          if (v === null) return null;
          var nts = v - dayStartMs(v) + carry;
          if (prev !== null && nts < prev) { carry += 86400000; nts += 86400000; }
          prev = nts;
          return nts;
        });
      } else {
        it.et = it.ts;
      }
      // 预计算该机在空时间窗 [firstEt, lastEt]，供生命周期判定 O(1) 查询
      var first = null, last = null;
      it.et.forEach(function (v) {
        if (v === null) return;
        if (first === null) first = v;
        last = v;
      });
      it.firstEt = first;
      it.lastEt = last;
    });

    // 虚拟基准日：归一化时取时间轴最早的真实日期（跨零点已由 et 加天保持单调），
    // 时间标签 = 基准日 0 点 + 日内毫秒；非归一化时直接用真实毫秒
    var baseMs = 0;
    if (dayNorm) {
      var minReal = null;
      items.forEach(function (it) {
        it.ts.forEach(function (v) {
          if (v !== null && (minReal === null || v < minReal)) minReal = v;
        });
      });
      baseMs = minReal === null ? 0 : dayStartMs(minReal);
    }

    // 事件类点的生效时刻：与航迹同一口径（归一化时 = 当日 0 点起毫秒）。
    // 只收事件语义（打击/战损/侦察发现）的点——静态阵地即便带记录时间也保持常显。
    var eventMoments = [];
    (spec.units || spec.points || []).forEach(function (p) {
      if (normalizeUnitKind(p).indexOf('event_') !== 0) return;
      if (toNum(p.lng) === null || toNum(p.lat) === null) return;
      var v = parseTime(p.time);
      if (v === null) return;
      eventMoments.push(dayNorm ? (v - dayStartMs(v)) : v);
    });

    // 全局时间轴：所有航迹点时间去重排序，标签统一为 YYYY-MM-DD HH:MM:SS
    var axisMap = {};
    items.forEach(function (it) {
      it.pts.forEach(function (p, i) {
        var v = it.et[i];
        if (v !== null && axisMap[v] === undefined) axisMap[v] = fmtDateTime(baseMs + v);
      });
    });
    // 事件时刻一并并入时间轴：否则晚于全部航迹末点的事件等不到自己的时刻，会被播放吞掉
    eventMoments.forEach(function (v) {
      if (axisMap[v] === undefined) axisMap[v] = fmtDateTime(baseMs + v);
    });
    var axis = Object.keys(axisMap).map(Number)
      .sort(function (a, b) { return a - b; })
      .map(function (v) { return { t: v, label: axisMap[v] }; });
    if (axis.length < 2) return null;

    var total = axis.length;
    var idx = 0;
    var playing = false;
    var timer = null;
    var lastBuffer = 0;
    var listeners = [];

    // 当前时刻沿航迹的插值位置（无时间字段的航迹固定停在最后一点）
    // 使用生效时刻 et（归一化时为虚拟日内毫秒），两端仍 clamp 供航迹末端符号使用
    function posAt(it, t) {
      var pts = it.pts, ts = it.et, n = pts.length;
      function at(i, frac) {
        return {
          lng: toNum(pts[i].lng), lat: toNum(pts[i].lat),
          heading: toNum(pts[i].heading), index: i, frac: frac,
        };
      }
      if (!it.hasTime) return at(n - 1, 1);
      if (t <= ts[0]) return at(0, 0);
      if (t >= ts[n - 1]) return at(n - 1, 1);
      for (var i = 0; i < n - 1; i++) {
        var a = ts[i], b = ts[i + 1];
        if (a === null || b === null || a > t || t > b) continue;
        var r = b > a ? (t - a) / (b - a) : 0;
        return {
          lng: lerp(toNum(pts[i].lng), toNum(pts[i + 1].lng), r),
          lat: lerp(toNum(pts[i].lat), toNum(pts[i + 1].lat), r),
          heading: lerpHeading(toNum(pts[i].heading), toNum(pts[i + 1].heading), r),
          index: i, frac: r,
        };
      }
      return at(n - 1, 1);
    }

    // 生命周期判定：当前时刻早于首点（未出动）或晚于末点（已返航）→ 不在空；
    // 无时间字段或时间窗缺失的航迹无法判定，视为始终在空（与历史行为一致）
    function airborneAt(it, t) {
      if (it.firstEt === null) return true;
      return t >= it.firstEt && t <= it.lastEt;
    }

    // 已飞航段 → 扫掠走廊多边形（一次 buffer 即含两端半圆帽）
    function trailLatLngs(it, pos, radiusKm) {
      var coords = [];
      for (var i = 0; i <= pos.index && i < it.pts.length; i++) {
        var lng = toNum(it.pts[i].lng), lat = toNum(it.pts[i].lat);
        if (lng !== null && lat !== null) coords.push([lng, lat]);
      }
      // 补上插值后的当前位置，使走廊尾端始终跟着飞机
      if (pos.frac > 0 && pos.index < it.pts.length - 1
          && pos.lng !== null && pos.lat !== null) {
        coords.push([pos.lng, pos.lat]);
      }
      if (coords.length < 2) return null;
      try {
        var line = window.turf.lineString(coords);
        var buf = window.turf.buffer(line, Math.abs(radiusKm),
          { units: 'kilometers', steps: steps });
        return buf ? turfToLatLngs(buf.geometry) : null;
      } catch (e) {
        return null;   // 几何异常不影响播放，仅本次不留痕
      }
    }

    function rangeColor(track, kind) {
      return track.factionColor || FACTION_COLORS[track.faction]
        || (kind === 'recon' ? KIND_COLORS.recon : KIND_COLORS.strike);
    }

    // 航迹线颜色：与静态航迹口径一致（阵营色，缺省按名称哈希兜底）
    function trackColorOf(track) {
      return track.factionColor || FACTION_COLORS[track.faction] || hashColor(track.name);
    }

    // 已飞航段的 Leaflet 坐标：起点 → 当前索引点，并补上插值位置使线尾贴住机头
    function flownCoords(it, pos) {
      var out = [];
      for (var i = 0; i <= pos.index && i < it.pts.length; i++) {
        var lng = toNum(it.pts[i].lng), lat = toNum(it.pts[i].lat);
        if (lng !== null && lat !== null) out.push(toLatLng(lng, lat));
      }
      if (pos.frac > 0 && pos.index < it.pts.length - 1
          && pos.lng !== null && pos.lat !== null) {
        out.push(toLatLng(pos.lng, pos.lat));
      }
      return out;
    }

    // 移除单个架次的飞机图标与渐进航迹层
    function clearItemVis(it) {
      var vis = it.vis;
      if (vis.plane) {
        try { map.removeLayer(vis.plane); } catch (e) { }
        vis.plane = null; vis.rot = null;
      }
      if (vis.line) {
        try { map.removeLayer(vis.line); } catch (e) { }
        vis.line = null; vis.weight = null;
      }
    }

    // 飞机图标 + 渐进航迹："飞机到哪航迹画到哪"，从不预画整条航迹
    function renderItemVis(it, pos) {
      var vis = it.vis;
      var ll = toLatLng(pos.lng, pos.lat);

      // 飞机图标：机型象形符号、机头朝当前航向；只更新位置与朝向，不重建 DOM
      if (!vis.plane) {
        vis.plane = L.marker(ll, {
          icon: createUnitIcon(L, {
            unitKind: 'aircraft', name: it.track.name, faction: it.track.faction,
            factionColor: it.track.factionColor, symbol: it.track.symbol,
            type: it.track.category, heading: pos.heading,
          }, { size: 30, heading: pos.heading }),
          zIndexOffset: 600, keyboard: false,
        });
        vis.plane.bindTooltip(esc(it.track.name || '飞机'), {
          direction: 'top', offset: [0, -16], className: 'sit-ic-tip',
        });
        vis.plane.addTo(map);
        vis.rot = toNum(pos.heading);
      } else {
        vis.plane.setLatLng(ll);
        vis.rot = applyHeading(vis.plane, pos.heading, vis.rot);
      }

      // 渐进航迹：不足 2 点时（刚起飞 / 重置回起点）只留飞机图标，不画线
      var coords = flownCoords(it, pos);
      if (coords.length < 2) {
        if (vis.line) { try { map.removeLayer(vis.line); } catch (e) { } vis.line = null; vis.weight = null; }
        return;
      }
      var w = trackWeight(map.getZoom());
      if (!vis.line) {
        vis.line = L.polyline(coords, {
          color: trackColorOf(it.track), weight: w, opacity: 0.95,
          lineCap: 'round', lineJoin: 'round', interactive: false,
        });
        vis.line.addTo(map);
        vis.weight = w;
      } else {
        vis.line.setLatLngs(coords);
        if (vis.weight !== w) { vis.line.setStyle({ weight: w }); vis.weight = w; }
      }
    }

    // ── 事件类点的时间可见性 ──
    // 打击/战损/侦察发现等事件点在其"事件时刻"加入地图，此后常显（不再消失）；
    // 静态单位/阵地与时间不可解析的点由调用方直接常显，不进入本列表。
    var eventRefs = [];

    function setEventShown(ref, visible) {
      if (ref.shown === visible) return;
      try {
        if (visible) {
          if (ref.container) ref.container.addLayer(ref.marker);
          else ref.marker.addTo(map);
        } else if (ref.container) {
          ref.container.removeLayer(ref.marker);
        } else {
          map.removeLayer(ref.marker);
        }
      } catch (e) {
        reportError('事件点显隐失败: ' + e.message);
      }
      ref.shown = visible;
    }

    // 按当前播放时刻刷新全部事件点显隐（回退/重置时未到时刻的事件点会重新隐藏）
    function applyEventVisibility(t) {
      eventRefs.forEach(function (ref) { setEventShown(ref, t >= ref.et); });
    }

    // 由 SitMap.render 的 units 渲染调用：把事件点交给播放器按时刻显隐
    function registerEvent(marker, timeText, container) {
      var v = parseTime(timeText);
      if (v === null) {
        // 时间缺失/不可解析：常显（与历史行为一致）
        if (container) container.addLayer(marker); else marker.addTo(map);
        return;
      }
      var ref = {
        marker: marker, et: dayNorm ? (v - dayStartMs(v)) : v,
        container: container || null, shown: false,
      };
      eventRefs.push(ref);
      // 播放器创建时已渲染过首帧，这里按当前时刻立即判定，避免首帧闪出未到时刻的事件
      setEventShown(ref, axis[idx].t >= ref.et);
    }

    function renderAt(t, force) {
      var now = Date.now();
      var doBuffer = wantTrail && (force || now - lastBuffer >= THROTTLE);
      if (doBuffer) lastBuffer = now;

      items.forEach(function (it) {
        var pos = posAt(it, t);
        // 生命周期：未出动/已返航或坐标缺失 → 图标/航迹/能力圈/扫掠带一并移除
        var airborne = airborneAt(it, t)
          && pos.lng !== null && pos.lat !== null;

        if (!airborne) {
          clearItemVis(it);
          it.slots.forEach(function (slot) {
            if (!slot) return;
            if (slot.circle) { try { map.removeLayer(slot.circle); } catch (e) { } slot.circle = null; }
            if (slot.trail) { try { map.removeLayer(slot.trail); } catch (e) { } slot.trail = null; }
          });
          return;
        }

        // 飞机图标 + 渐进航迹：与能力半径无关，无机型半径的架次同样显示
        renderItemVis(it, pos);
        if (!it.defs.length) return;

        var ll = toLatLng(pos.lng, pos.lat);
        it.defs.forEach(function (def, i) {
          var slot = it.slots[i];
          if (!slot) slot = it.slots[i] = { circle: null, trail: null };
          var color = rangeColor(it.track, def.kind);

          // 动态能力圈：圆心=飞机当前位置；侦察虚线、打击实线
          if (!slot.circle) {
            var isRecon = def.kind === 'recon';
            slot.circle = L.circle(ll, {
              pane: 'sitRangePane',
              radius: Math.abs(def.r) * 1000,
              color: color, weight: 1.6, opacity: 0.9,
              dashArray: isRecon ? '6 5' : null,
              fillColor: color, fillOpacity: 0.04,
              interactive: false,
            });
            slot.circle.addTo(map);
          } else {
            slot.circle.setLatLng(ll);
          }

          // 扫掠留痕：已飞航段的 buffer 走廊（节流重算，暂停拖动时强制重算）
          if (!doBuffer) return;
          var latlngs = trailLatLngs(it, pos, def.r);
          if (!latlngs) return;
          if (!slot.trail) {
            slot.trail = L.polygon(latlngs, {
              pane: 'sitTrailPane',
              stroke: false, fill: true,
              fillColor: color, fillOpacity: 0.12,
              interactive: false,
            });
            slot.trail.addTo(map);
          } else {
            slot.trail.setLatLngs(latlngs);
          }
        });
      });

      // 事件点显隐与航迹/能力圈同一时刻口径
      applyEventVisibility(t);
    }

    // 清空全部回放可视层（飞机图标 + 渐进航迹 + 扫掠带），供重播/重置使用
    function clearVis() {
      items.forEach(function (it) {
        clearItemVis(it);
        it.slots.forEach(function (slot) {
          if (!slot || !slot.trail) return;
          try { map.removeLayer(slot.trail); } catch (e) { }
          slot.trail = null;
        });
      });
    }

    function emit() {
      var payload = {
        index: idx, total: total,
        ratio: total > 1 ? idx / (total - 1) : 0,
        time: axis[idx] ? axis[idx].label : '',
        playing: playing,
        speed: speed,
      };
      listeners.forEach(function (fn) {
        try { fn(payload); } catch (e) { reportError('播放器事件处理异常: ' + e.message); }
      });
    }

    function stopTimer() {
      if (timer) { clearInterval(timer); timer = null; }
    }

    // 按当前倍速重启计时器（倍速切换时调用；仅在播放中生效）
    function startTimer() {
      stopTimer();
      timer = setInterval(step, Math.max(80, interval / speed));
    }

    // 切换播放倍速（0.5×/1×/2×/4×）：播放中即时生效
    function setSpeed(v) {
      var i = SPEEDS.indexOf(v);
      if (i < 0) return;
      speedIdx = i;
      speed = SPEEDS[i];
      if (playing) startTimer();
      emit();
    }

    function step() {
      if (idx >= total - 1) { pause(); return; }
      idx += 1;
      renderAt(axis[idx].t, false);
      emit();
    }

    function play() {
      if (playing) return;
      if (idx >= total - 1) { idx = 0; clearVis(); renderAt(axis[0].t, true); }
      playing = true;
      startTimer();
      emit();
    }

    function pause() {
      stopTimer();
      playing = false;
      emit();
    }

    function seek(ratio) {
      var r = toNum(ratio);
      r = r === null ? 0 : Math.max(0, Math.min(1, r));
      idx = Math.round(r * (total - 1));
      renderAt(axis[idx].t, true);
      emit();
    }

    function reset() {
      pause();
      idx = 0;
      clearVis();
      renderAt(axis[0].t, true);
      emit();
    }

    var playback = {
      play: play, pause: pause, reset: reset, seek: seek,
      toggle: function () { if (playing) pause(); else play(); },
      isPlaying: function () { return playing; },
      total: total,
      on: function (fn) { if (typeof fn === 'function') listeners.push(fn); return playback; },
      off: function (fn) { listeners = listeners.filter(function (f) { return f !== fn; }); return playback; },
      current: function () { return { index: idx, time: axis[idx] ? axis[idx].label : '' }; },
      // 把事件类点交给播放器按事件时刻显隐（由 units 渲染调用）
      registerEvent: registerEvent,
      // 整图重渲染前销毁：停止计时器、移除播放条与全部动态图层
      destroy: function () {
        stopTimer();
        playing = false;
        listeners = [];
        items.forEach(function (it) {
          it.slots.forEach(function (slot) {
            if (!slot) return;
            if (slot.circle) { try { map.removeLayer(slot.circle); } catch (e) { } }
            if (slot.trail) { try { map.removeLayer(slot.trail); } catch (e) { } }
          });
          clearItemVis(it);
        });
        if (control) { try { map.removeControl(control); } catch (e) { } control = null; }
      },
    };

    // ── 内置播放条（LLM 不必自己写播放器）──
    var control = null;
    if (cfg.showBar !== false) {
      var PlaybackCtl = L.Control.extend({
        options: { position: 'bottomleft' },
        onAdd: function () {
          var box = L.DomUtil.create('div', 'sit-playback');
          box.innerHTML =
            '<button class="sit-pb-btn" data-act="toggle">▶ 播放</button>'
            + '<input class="sit-pb-range" type="range" min="0" max="1000" step="1" value="0">'
            + '<span class="sit-pb-time">—</span>'
            + '<button class="sit-pb-btn sit-pb-speed" data-act="speed" title="切换播放倍速">'
            + speedLabel(speed) + '</button>'
            + '<button class="sit-pb-btn" data-act="reset">重置</button>';
          L.DomEvent.disableClickPropagation(box);
          L.DomEvent.disableScrollPropagation(box);
          var btn = box.querySelector('[data-act="toggle"]');
          var range = box.querySelector('.sit-pb-range');
          var label = box.querySelector('.sit-pb-time');
          var speedBtn = box.querySelector('[data-act="speed"]');
          btn.addEventListener('click', function () { playback.toggle(); });
          box.querySelector('[data-act="reset"]').addEventListener('click', function () { reset(); });
          // 倍速按钮：循环切换 0.5×/1×/2×/4×，播放中即时生效
          speedBtn.addEventListener('click', function () {
            setSpeed(SPEEDS[(speedIdx + 1) % SPEEDS.length]);
          });
          range.addEventListener('input', function () {
            // 必须先取值再 pause()：pause 会 emit 一次并把滑块重置回当前进度，
            // 若先 pause 再读 range.value，拖动会被"还原"成原地不动（seek 失效）。
            var v = parseInt(range.value, 10) / 1000;
            pause();
            seek(v);
          });
          playback.on(function (s) {
            range.value = Math.round(s.ratio * 1000);
            label.textContent = s.time || '—';
            speedBtn.textContent = speedLabel(s.speed);
            btn.textContent = s.playing ? '⏸ 暂停' : '▶ 播放';
          });
          return box;
        },
      });
      control = new PlaybackCtl();
      map.addControl(control);
    }

    renderAt(axis[0].t, true);
    emit();
    return playback;
  }

  var SitMap = {
    render: function (el, spec) {
      var node = resolveEl(el);
      if (!node || !window.L) { reportError('地图容器或 Leaflet 运行时不可用'); return null; }
      spec = spec || {};

      var L = window.L;
      ensureMapStyle();

      // 同一容器重渲染：复用地图实例，仅清除业务图层，**保留用户的缩放/拖动视图**。
      // 时间轴播放时反复调用 render，若每次重建地图 + fitBounds 会导致地图不断缩放。
      var oldPair = mapByEl.filter(function (p) { return p[0] === node; })[0];
      var map, api, isFirstRender;
      if (oldPair) {
        map = oldPair[1]._map;
        api = oldPair[1];
        isFirstRender = false;
        clearBusinessLayers(map, api);
      } else {
        map = L.map(node, { zoomControl: true, preferCanvas: true }).setView([35, 105], 4);
        addTiles(map);
        // 范围圈专用低层级窗格（瓦片 200 < 范围圈 310 < 航迹线 400 < 单位符号 600），
        // 避免大范围圈（如上千公里战略圈）遮盖航迹线与单位符号
        var rangePane = map.createPane('sitRangePane');
        rangePane.style.zIndex = 310;
        // 扫掠走廊专用窗格：位于瓦片之上、范围圈之下，避免半透明填充盖住动态能力圈
        var trailPane = map.createPane('sitTrailPane');
        trailPane.style.zIndex = 300;
        api = {
          _map: map,
          _layers: { featureLayers: [], trackLines: [], startMarkers: [], cluster: null,
                     legendControl: null, playback: null },
          _clickFns: [],
          _userInteracted: false,
        };
        // 用户一旦交互（拖动/缩放/双击），永久锁定视图，后续重渲染不再自动适配
        map.on('mousedown touchstart wheel dblclick', function () { api._userInteracted = true; });
        mapByEl.push([node, api]);
        isFirstRender = true;
      }

      var clickFns = api._clickFns = [];
      var featureLayers = api._layers.featureLayers = [];
      var trackLines = api._layers.trackLines = [];
      var startMarkers = api._layers.startMarkers = [];
      var bounds = [];
      function pushBounds(ll) { bounds.push(ll); }

      // ── 时间轴回放（内置播放器 + 动态能力圈 + 扫掠留痕 + 事件点按时刻显隐）──
      // 必须先创建播放器：它是否真的建得起来（有时间轴且航迹可用）决定静态整条航迹
      // 是否交给播放器接管（playbackOn），也决定事件类点是否交给播放器按时刻显隐。
      // 缺省（未传 spec.playback）时不注入播放条、不画能力圈，行为与历史版本一致。
      api.playback = null;
      if (spec.playback && (spec.tracks || []).length) {
        api.playback = createPlayback(L, map, spec, api);
        api._layers.playback = api.playback;
      }
      var playbackOn = !!api.playback;

      // ── 单位/事件点（象形符号，超阈值自动聚合）──
      // 回放开启时，带可解析时间的事件类点（打击/战损/侦察发现）交给播放器按"事件时刻"
      // 加入地图并此后常显；单位/阵地等非事件点、以及时间不可解析的点保持常显。
      var units = spec.units || spec.points || [];
      var useCluster = !!L.markerClusterGroup && (spec.clusterPoints || units.length > 300);
      var cluster = useCluster ? L.markerClusterGroup({
        chunkedLoading: true, maxClusterRadius: 56, showCoverageOnHover: false, zoomToBoundsOnClick: true,
      }) : null;
      api._layers.cluster = cluster;
      units.forEach(function (p) {
        if (toNum(p.lng) === null || toNum(p.lat) === null) return;
        var ll = toLatLng(p.lng, p.lat);
        pushBounds(ll);
        var unit = {
          unitKind: p.unitKind || p.kind, name: p.name, faction: p.faction,
          type: p.type, status: p.status, time: p.time, heading: p.heading,
          props: p.props || {},
        };
        var visual = resolveUnitVisual(unit);
        var marker = L.marker(ll, { icon: createUnitIcon(L, unit), riseOnHover: true, keyboard: false });
        marker.bindPopup(unitPopupHtml(unit, visual));
        marker.bindTooltip(esc(unit.name || ''), {
          direction: 'top', offset: [0, -12], className: 'sit-ic-tip',
          permanent: !!spec.showLabels,
        });
        var feat = {
          kind: 'unit', name: unit.name || '', faction: unit.faction || '',
          unitKind: visual.kind, type: unit.type || '', status: unit.status || '',
          time: unit.time || '', lng: toNum(p.lng), lat: toNum(p.lat),
          props: unit.props,
        };
        marker.on('click', function () {
          clickFns.forEach(function (fn) { fn(feat); });
        });
        featureLayers.push({ layer: marker, feature: feat });
        // 事件语义判定复用 normalizeUnitKind，避免与符号解析各自维护一套类别映射
        var eventGated = playbackOn && normalizeUnitKind(unit).indexOf('event_') === 0;
        if (eventGated) {
          api.playback.registerEvent(marker, unit.time, cluster);
        } else if (cluster) {
          cluster.addLayer(marker);
        } else {
          marker.addTo(map);
        }
      });
      if (cluster) map.addLayer(cluster);

      // ── 航迹：柔和折线 + 起点小点 + 终点飞机符号（按航向旋转）──
      // 是否预画整条航迹取决于播放器是否接管（playbackOn = 播放器真的建起来了）：
      // 回放模式下不预画，改由 createPlayback 渲染"飞机图标 + 已飞航迹渐进显示"
      // （飞机到哪航迹画到哪）；未进入回放时保持历史行为，整条航迹照画。
      // 线宽随缩放自适应（trackWeight）避免几十条航迹在全景下焊成线团。
      (spec.tracks || []).forEach(function (track) {
        var pts = track.points || [];
        var coords = pts.map(function (p) {
          if (toNum(p.lng) === null || toNum(p.lat) === null) return null;
          var ll = toLatLng(p.lng, p.lat);
          pushBounds(ll);
          return ll;
        }).filter(function (c) { return c; });
        if (coords.length < 2) return;
        if (playbackOn) return;
        var color = track.factionColor || FACTION_COLORS[track.faction] || hashColor(track.name);
        // round 线帽/拐点，避免硬边折线
        var line = L.polyline(coords, {
          color: color, weight: trackWeight(map.getZoom()), opacity: 0.85,
          lineCap: 'round', lineJoin: 'round',
        });
        trackLines.push(line);
        var firstPoint = pts[0] || {}, lastPoint = pts[pts.length - 1] || {};
        var feat = {
          kind: 'track', name: track.name || '', faction: track.faction || '',
          category: track.category || '', missionId: track.missionId || '',
          strikeRadiusKm: track.strikeRadiusKm, reconRadiusKm: track.reconRadiusKm,
          props: lastPoint.props || firstPoint.props || {},
        };
        var timeRange = firstPoint.time && lastPoint.time
          ? '<br/>' + esc(firstPoint.time) + ' ～ ' + esc(lastPoint.time) : '';
        var catInfo = track.category ? '<br/>机型：' + esc(track.category) : '';
        var missionInfo = track.missionId ? '<br/>任务：' + esc(track.missionId) : '';
        var radiusInfo = '';
        if (track.strikeRadiusKm != null) {
          radiusInfo += '<br/>打击半径：' + esc(track.strikeRadiusKm) + ' km';
        }
        if (track.reconRadiusKm != null) {
          radiusInfo += '<br/>侦察半径：' + esc(track.reconRadiusKm) + ' km';
        }
        line.bindPopup('<b>' + esc(track.name || '航迹') + '</b>'
          + (track.faction ? '（' + esc(track.faction) + '）' : '')
          + catInfo + missionInfo + radiusInfo + timeRange);
        line.on('click', function () { clickFns.forEach(function (fn) { fn(feat); }); });
        line.addTo(map);
        featureLayers.push({ layer: line, feature: feat });
        // 起点：白色描边实心小点
        var startMarker = L.circleMarker(coords[0], {
          radius: 4, color: '#fff', weight: 1.2, fillColor: color, fillOpacity: 1,
        }).bindTooltip(esc(track.name || '') + ' 起点').addTo(map);
        startMarkers.push(startMarker);
        // 终点（最新位置）：机型象形符号，机头朝向最后一点的航向
        var endUnit = {
          unitKind: 'aircraft', name: track.name, faction: track.faction,
          factionColor: track.factionColor, symbol: track.symbol,
          type: track.category, heading: lastPoint.heading,
        };
        var endMarker = L.marker(coords[coords.length - 1], {
          icon: createUnitIcon(L, endUnit, { size: 30 }),
          zIndexOffset: 500, keyboard: false,
        });
        endMarker.bindTooltip(esc(track.name || '') + ' 最新位置', {
          direction: 'top', offset: [0, -14], className: 'sit-ic-tip', permanent: !!spec.showAircraftLabels,
        });
        endMarker.on('click', function () { clickFns.forEach(function (fn) { fn(feat); }); });
        endMarker.addTo(map);
        featureLayers.push({ layer: endMarker, feature: feat });
      });
      // 缩放档位变化时统一切换航迹线宽；监听器只绑定一次（复用地图实例避免重复注册）
      if (!api._zoomBound) {
        api._lastTrackW = trackWeight(map.getZoom());
        map.on('zoomend', function () {
          var w = trackWeight(map.getZoom());
          if (w === api._lastTrackW) return;
          api._lastTrackW = w;
          (api._layers.trackLines || []).forEach(function (l) {
            try { l.setStyle({ weight: w }); } catch (e) { }
          });
        });
        api._zoomBound = true;
      }

      // ── 范围圈（阵营色；侦察范围虚线、打击范围实线）──
      (spec.circles || []).forEach(function (c) {
        if (toNum(c.lng) === null || toNum(c.lat) === null || toNum(c.radiusKm) === null) return;
        var ll = toLatLng(c.lng, c.lat);
        pushBounds(ll);
        var isRecon = c.kind === 'recon' || String(c.rangeType || '').indexOf('侦察') >= 0;
        var color = c.factionColor || FACTION_COLORS[c.faction]
          || (isRecon ? KIND_COLORS.recon : KIND_COLORS.strike);
        var circle = L.circle(ll, {
          pane: 'sitRangePane',
          radius: Math.abs(c.radiusKm) * 1000,
          color: color, weight: 1.8, opacity: 0.85,
          dashArray: isRecon ? '6 5' : null,
          fillColor: color, fillOpacity: 0.03,
        });
        var feat = { kind: 'circle', name: c.name || '', faction: c.faction || '',
                     rangeType: c.rangeType || '', props: { radiusKm: c.radiusKm } };
        circle.bindPopup('<b>' + esc(c.name || '范围') + '</b>'
          + (c.faction ? '（' + esc(c.faction) + '）' : '')
          + '<br/>' + esc(c.rangeType || (isRecon ? '侦察范围' : '打击范围'))
          + '<br/>半径 ' + esc(c.radiusKm) + ' km');
        circle.on('click', function () { clickFns.forEach(function (fn) { fn(feat); }); });
        circle.addTo(map);
        featureLayers.push({ layer: circle, feature: feat });
      });

      // ── 图例（按实际出现的单位/航迹/范围自动生成，可折叠）──
      api._layers.legendControl = addLegendControl(L, map, spec);

      // ── 视野：仅首次渲染自动适配；重渲染时保留用户视图 ──
      // 时间轴播放反复调用 render，若每次都 fitBounds 会导致地图不断缩放。
      // 规则：
      //   1. 首次渲染：autoFit 时 fitBounds；显式 center 时 setView；
      //   2. 重渲染且用户已交互：完全不动视图（用户锁定）；
      //   3. 重渲染且用户未交互 + 显式 center：尊重 LLM 指定视图；
      //   4. 其余情况：保留当前视图，不做任何适配。
      // 回放模式下把能力圈半径计入视野范围，避免圆被地图边缘裁掉
      if (playbackOn && bounds.length) {
        var maxR = 0;
        (spec.tracks || []).forEach(function (t) {
          [toNum(t.strikeRadiusKm), toNum(t.reconRadiusKm)].forEach(function (v) {
            if (v !== null && Math.abs(v) > maxR) maxR = Math.abs(v);
          });
        });
        if (maxR > 0) {
          var minLat = bounds[0][0], maxLat = bounds[0][0];
          var minLng = bounds[0][1], maxLng = bounds[0][1];
          bounds.forEach(function (b) {
            if (b[0] < minLat) minLat = b[0];
            if (b[0] > maxLat) maxLat = b[0];
            if (b[1] < minLng) minLng = b[1];
            if (b[1] > maxLng) maxLng = b[1];
          });
          var dLat = maxR / 111.32;
          var dLng = maxR / (111.32 * Math.max(0.2, Math.cos((minLat + maxLat) / 2 * Math.PI / 180)));
          bounds = bounds.concat([[minLat - dLat, minLng - dLng], [maxLat + dLat, maxLng + dLng]]);
        }
      }

      var fitOpts = { padding: [30, 30], maxZoom: 11 };
      var autoFit = (spec.center === 'auto' || (!spec.center && spec.fit !== false)) && bounds.length > 0;
      var explicitCenter = Array.isArray(spec.center) && spec.center.length === 2;
      if (isFirstRender) {
        if (autoFit) {
          map.fitBounds(bounds, fitOpts);
        } else if (explicitCenter) {
          map.setView([spec.center[1], spec.center[0]], toNum(spec.zoom) || 6);
        }
        // 首次延迟校正：iframe 内容器可能尚未布局完成（尺寸为 0），fitBounds 会失准；
        // 用户一旦交互就停止校正
        [200, 600].forEach(function (ms) {
          setTimeout(function () {
            try {
              map.invalidateSize();
              if (autoFit && !api._userInteracted) map.fitBounds(bounds, fitOpts);
            } catch (e) { }
          }, ms);
        });
      } else if (!api._userInteracted && explicitCenter) {
        // 重渲染 + 用户未交互 + LLM 显式指定 center → 尊重指定视图
        map.setView([spec.center[1], spec.center[0]], toNum(spec.zoom) || 6);
      }
      // 其余情况（含用户已交互）：什么都不做，保留当前视图

      // 复用入口处创建的 api 实例，仅挂载/更新公共方法
      api.on = function (event, fn) {
        if (event === 'featureClick' && typeof fn === 'function') clickFns.push(fn);
        return api;
      };
      api.flyTo = function (lng, lat, zoom) {
        if (toNum(lng) === null || toNum(lat) === null) return;
        var ll = toLatLng(lng, lat);   // 已转为 [lat, lng]
        map.flyTo(ll, toNum(zoom) || 10);
      };
      api.highlight = function (predicate) {
        if (typeof predicate !== 'function') return;
        var firstHit = null;
        featureLayers.forEach(function (item) {
          var hit = false;
          try { hit = !!predicate(item.feature); } catch (e) { hit = false; }
          try {
            if (item.feature.kind === 'unit') {
              // divIcon 符号：高亮描边 + 放大；未命中降透明度
              var el = item.layer.getElement && item.layer.getElement();
              if (el) el.classList.toggle('sit-hl', hit);
              if (item.layer.setOpacity) item.layer.setOpacity(hit ? 1 : 0.35);
            } else if (item.feature.kind === 'point') {
              item.layer.setStyle({ radius: hit ? 9 : 5, fillOpacity: hit ? 1 : 0.35, weight: hit ? 2 : 1 });
            } else if (item.feature.kind === 'track') {
              item.layer.setStyle({ weight: hit ? 5 : 3, opacity: hit ? 1 : 0.25 });
            } else {
              item.layer.setStyle({ fillOpacity: hit ? 0.3 : 0.05, weight: hit ? 3 : 1.5 });
            }
          } catch (e) { }
          if (hit && !firstHit) firstHit = item;
        });
        if (firstHit && firstHit.layer.openPopup) {
          try {
            if (firstHit.layer.getLatLngs) {
              var ls = firstHit.layer.getLatLngs();
              if (ls.length) map.panTo(ls[0]);
            } else if (firstHit.layer.getLatLng) {
              map.panTo(firstHit.layer.getLatLng());
            }
            firstHit.layer.openPopup();
          } catch (e) { }
        }
      };
      return api;
    },
  };

  // ────────────────────────────────────────────────────────────────
  // SitTable —— 分页明细表（自带样式，不依赖外部框架）
  // ────────────────────────────────────────────────────────────────
  var TABLE_STYLE_ID = 'ipage-table-style';
  function ensureTableStyle() {
    if (document.getElementById(TABLE_STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = TABLE_STYLE_ID;
    style.textContent = [
      '.ip-table{width:100%;border-collapse:collapse;font-size:13px;color:#334155}',
      '.ip-table th{background:#f1f5f9;color:#0f172a;font-weight:600;text-align:left;padding:8px 10px;white-space:nowrap;border-bottom:1px solid #e2e8f0}',
      '.ip-table td{padding:7px 10px;border-bottom:1px solid #f1f5f9;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.ip-table tr:hover td{background:#f8fafc}',
      '.ip-table-wrap{border:1px solid #e2e8f0;border-radius:8px;overflow:hidden}',
      '.ip-pager{display:flex;align-items:center;gap:8px;justify-content:flex-end;padding:8px 12px;font-size:12px;color:#64748b;background:#fafbfc}',
      '.ip-pager button{border:1px solid #cbd5e1;background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer;color:#334155}',
      '.ip-pager button:disabled{opacity:.45;cursor:not-allowed}',
      '.ip-table-empty{padding:28px;text-align:center;color:#94a3b8;font-size:13px}',
    ].join('');
    document.head.appendChild(style);
  }

  var SitTable = {
    render: function (el, spec) {
      var node = resolveEl(el);
      if (!node) return;
      spec = spec || {};
      ensureTableStyle();
      var rawCols = spec.columns || [];
      var cols = rawCols.map(function (c) {
        return typeof c === 'string' ? { key: c, label: c } : { key: c.key, label: c.label || c.key };
      });
      var rows = spec.rows || [];
      var pageSize = Math.max(1, toNum(spec.pageSize) || 10);
      var page = 0;
      var maxHeight = spec.maxHeight ? 'max-height:' + spec.maxHeight + 'px;overflow:auto;' : '';

      function draw() {
        var totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
        if (page >= totalPages) page = totalPages - 1;
        var slice = rows.slice(page * pageSize, page * pageSize + pageSize);
        var html = '<div class="ip-table-wrap">';
        if (!cols.length || !rows.length) {
          html += '<div class="ip-table-empty">暂无相关数据</div></div>';
          node.innerHTML = html;
          return;
        }
        html += '<div style="' + maxHeight + '"><table class="ip-table"><thead><tr>';
        cols.forEach(function (c) { html += '<th>' + esc(c.label) + '</th>'; });
        html += '</tr></thead><tbody>';
        slice.forEach(function (r) {
          html += '<tr>';
          cols.forEach(function (c) {
            var v = r[c.key];
            html += '<td title="' + esc(v) + '">' + (v == null || v === '' ? '-' : esc(v)) + '</td>';
          });
          html += '</tr>';
        });
        html += '</tbody></table></div>';
        html += '<div class="ip-pager">'
          + '<span>共 ' + rows.length + ' 行</span>'
          + '<button data-ip-page="prev"' + (page === 0 ? ' disabled' : '') + '>上一页</button>'
          + '<span>' + (page + 1) + ' / ' + totalPages + '</span>'
          + '<button data-ip-page="next"' + (page >= totalPages - 1 ? ' disabled' : '') + '>下一页</button>'
          + '</div></div>';
        node.innerHTML = html;
        var btns = node.querySelectorAll('[data-ip-page]');
        btns.forEach(function (b) {
          b.addEventListener('click', function () {
            if (b.getAttribute('data-ip-page') === 'prev') page--; else page++;
            draw(); requestHeight();
          });
        });
      }
      draw();
    },
  };

  // ────────────────────────────────────────────────────────────────
  // SitApp —— 启动入口 / 错误上报 / 父页通信
  // ────────────────────────────────────────────────────────────────
  function reportError(message) {
    try { window.parent.postMessage({ type: 'ipage:error', message: String(message || '').slice(0, 300) }, '*'); } catch (e) { }
  }
  window.onerror = function (msg) { reportError(msg); };

  var heightTimer = null;
  function postHeight() {
    try {
      var h = Math.max(
        document.body ? document.body.scrollHeight : 0,
        document.documentElement ? document.documentElement.scrollHeight : 0
      );
      if (h > 0) window.parent.postMessage({ type: 'ipage:height', height: h }, '*');
    } catch (e) { }
  }
  function requestHeight() {
    clearTimeout(heightTimer);
    heightTimer = setTimeout(postHeight, 120);
  }

  function boot() {
    if (booted || !state || !state.data) return;
    booted = true;
    try {
      bootCallbacks.forEach(function (fn) {
        try { fn(state.data); } catch (e) { reportError('页面启动逻辑异常: ' + (e && e.message)); }
      });
    } finally {
      // 多轮事件循环后量高，等待图表/地图挂载完成
      [60, 220, 600].forEach(function (t) { setTimeout(postHeight, t); });
    }
  }

  var SitApp = {
    bootstrap: function (fn) {
      if (typeof fn === 'function') bootCallbacks.push(fn);
      if (booted) { try { fn(state.data); } catch (e) { reportError(e.message); } }
      requestHeight();
    },
    ready: function () { requestHeight(); },
    reportError: reportError,
  };

  // ── 窗口 resize → 图表重排 + 高度重报 ──
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      echartsInstances.forEach(function (inst) { try { inst.resize(); } catch (e) { } });
      postHeight();
    }, 150);
  });
  if (window.ResizeObserver && document.body) {
    new ResizeObserver(requestHeight).observe(document.body);
  }

  // ── 与父页握手：ready 周期重发直到数据到达（防竞态丢数据）──
  function sendReady() {
    try {
      window.parent.postMessage({
        type: 'ipage:ready',
        diag: {
          readyState: document.readyState,
          hasEcharts: !!window.echarts,
          hasL: !!window.L,
          hasGcoord: !!window.gcoord,
        },
      }, '*');
    } catch (e) { }
  }
  [0, 300, 900, 1800, 3200, 5000].forEach(function (t) {
    setTimeout(function () { if (!state) sendReady(); }, t);
  });

  window.addEventListener('message', function (e) {
    var msg = e.data || {};
    if (msg.type !== 'ipage:data' || !msg.payload) return;
    state = msg.payload;
    tileLayers = state.tileLayers || [];
    boot();
  });

  // ── 暴露受限 API（只读，不可重写）──
  Object.defineProperty(window, 'SitApp', { value: SitApp, writable: false, configurable: false });
  Object.defineProperty(window, 'SitChart', { value: SitChart, writable: false, configurable: false });
  Object.defineProperty(window, 'SitMap', { value: SitMap, writable: false, configurable: false });
  Object.defineProperty(window, 'SitBus', { value: SitBus, writable: false, configurable: false });
  Object.defineProperty(window, 'SitUtil', { value: SitUtil, writable: false, configurable: false });
  Object.defineProperty(window, 'SitTable', { value: SitTable, writable: false, configurable: false });

  if (document.readyState !== 'loading') sendReady();
  else document.addEventListener('DOMContentLoaded', sendReady);
})();
