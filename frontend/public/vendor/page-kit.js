/**
 * page-kit.js —— 智能交互页面（ipage）沙箱受限运行时。
 *
 * 运行在 iframe sandbox="allow-scripts" 中（无同源权限、CSP connect-src 'none'）：
 * 1. 与父页 postMessage 握手，接收 'ipage:data'（dataBundle + 瓦片配置）；
 * 2. 向业务页面暴露且仅暴露：SitApp / SitTimeline / SitChart / SitMap / SitBus / SitUtil / SitTable；
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
  var fallbackTileLayers = [];  // 底图瓦片不可达时的备用图层（GeoWebCache）

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

  // 页面级阵营筛选（宿主浮层下发）：空字符串 = 全部
  var activeFaction = '';
  var FACTION_ALIASES = { red: '红方', blue: '蓝方', '红方': '红方', '蓝方': '蓝方' };
  // 逐机图层子项 → 全局组开关键
  var TRACK_PART_GROUPS = {
    track: 'trackLine',
    reconSweep: 'reconSweep', strikeSweep: 'strikeSweep',
    reconCircle: 'reconRange', strikeCircle: 'strikeRange',
  };

  function normalizeFaction(v) {
    var s = String(v == null ? '' : v).trim();
    return FACTION_ALIASES[s] || FACTION_ALIASES[s.toLowerCase()] || '';
  }

  // 阵营过滤：未选择阵营、元素无阵营（如静态设施）、或阵营一致时可见
  function factionAllowed(faction) {
    if (!activeFaction) return true;
    var raw = String(faction == null ? '' : faction).trim();
    if (!raw) return true;
    return (normalizeFaction(raw) || raw) === activeFaction;
  }

  // 架次稳定键：任务编号优先，其次飞机编号，最后呼号
  function trackKeyOf(t) {
    t = t || {};
    return String(t.missionId || t.id || t.name || '');
  }

  function defaultTrackParts() {
    return {
      all: true, aircraft: true, track: true,
      reconCircle: true, strikeCircle: true,
      reconSweep: true, strikeSweep: true,
    };
  }

  function ensureLayerState(api) {
    if (!api._layerState) {
      api._layerState = {
        groups: {
          trackLine: true, reconSweep: true, strikeSweep: true,
          reconRange: true, strikeRange: true,
        },
        tracks: {}, units: {}, circles: {},
      };
    }
    return api._layerState;
  }

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
  // 图表容器所在的卡片若已有 HTML 标题（.ip-title / h3 / *title*），
  // 再让 ECharts 画一次 title 会与图例、坐标轴文字挤在同一块画布上，造成"重影/压字"。
  function cardHeadingOf(node) {
    var el = node.parentElement;
    for (var depth = 0; el && depth < 3; depth++, el = el.parentElement) {
      for (var i = 0; i < el.children.length; i++) {
        var c = el.children[i];
        if (c === node || (c.contains && c.contains(node))) continue;
        var tag = (c.tagName || '').toLowerCase();
        var cls = String(c.className || '');
        if (tag === 'h1' || tag === 'h2' || tag === 'h3' || tag === 'h4' || /title/i.test(cls)) {
          var text = String(c.textContent || '').trim();
          if (text) return text;
        }
      }
    }
    return '';
  }

  function baseGrid(spec) {
    var compact = !!spec._compact;
    return {
      left: compact ? 46 : 56, right: compact ? 16 : 28,
      top: spec.title ? (compact ? 34 : 46) : (compact ? 24 : 30),
      bottom: spec.showDataZoom ? 64 : (compact ? 32 : 42), containLabel: true,
    };
  }
  function axisCommon(compact) {
    return {
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      axisLabel: { color: '#475569', fontSize: compact ? 10 : 12 },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    };
  }
  function legend(series, compact) {
    if (!series || series.length <= 1) return undefined;
    return {
      type: 'scroll', top: compact ? 0 : 8, left: 8, right: 8,
      icon: 'roundRect', itemWidth: compact ? 10 : 12, itemHeight: compact ? 6 : 8,
      itemGap: compact ? 8 : 12, pageIconSize: 8,
      textStyle: { color: '#475569', fontSize: compact ? 10 : 12 },
    };
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
    var compact = !!spec._compact;
    if (spec.title) {
      option.title = {
        text: spec.title, left: 8, top: 4,
        textStyle: { fontSize: compact ? 12 : 14, color: '#0f172a', fontWeight: 600 },
      };
    }
    var series = spec.series || [];

    if (type === 'bar') {
      var horizontal = !!spec.horizontal;
      var xAxis, yAxis, xData = spec.xData || [];
      if (!horizontal) {
        xAxis = Object.assign({ type: 'category', data: xData, axisLabel: { color: '#475569', interval: 0 } }, axisCommon(compact));
        yAxis = Object.assign({ type: 'value', name: spec.yName || '' }, axisCommon(compact));
      } else {
        xAxis = Object.assign({ type: 'value', name: spec.yName || '' }, axisCommon(compact));
        yAxis = Object.assign({ type: 'category', data: xData.slice().reverse() }, axisCommon(compact));
      }
      option.tooltip = tooltip();
      option.legend = legend(series, compact);
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
      option.legend = legend(series, compact);
      option.xAxis = Object.assign({ type: 'category', boundaryGap: false, data: spec.xData || [], axisLabel: { color: '#475569' } }, axisCommon(compact));
      option.yAxis = Object.assign({ type: 'value', name: spec.yName || '' }, axisCommon(compact));
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
      option.legend = {
        orient: 'vertical', right: compact ? 4 : 10, top: 'middle', icon: 'circle',
        itemWidth: compact ? 8 : 14, itemGap: compact ? 6 : 10,
        textStyle: { color: '#475569', fontSize: compact ? 10 : 12 },
      };
      option.series = [{
        name: (series[0] || {}).name || '占比', type: 'pie',
        radius: compact ? ['36%', '58%'] : ['42%', '68%'],
        center: ['42%', '54%'], avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
        label: { color: '#475569', fontSize: compact ? 10 : 12, show: !compact },
        data: pieData,
      }];
      return option;
    }

    if (type === 'radar') {
      option.grid = undefined;
      option.tooltip = { confine: true };
      // 雷达的轴名环绕在四周，图例放上方会压住轴名；统一放到底部
      option.legend = legend(series, compact);
      if (option.legend) {
        option.legend.top = undefined;
        option.legend.bottom = 0;
      }
      option.radar = {
        indicator: (spec.indicators || []).map(function (n) { return { name: n, max: spec.max }; }),
        radius: compact ? '56%' : '62%',
        center: ['50%', compact ? '50%' : '55%'],
        axisName: { color: '#475569', fontSize: compact ? 10 : 12 },
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
      option.legend = legend(series, compact);
      option.xAxis = Object.assign({ type: 'value', scale: true, name: spec.xName || '' }, axisCommon(compact));
      option.yAxis = Object.assign({ type: 'value', scale: true, name: spec.yName || '' }, axisCommon(compact));
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

  // ────────────────────────────────────────────────────────────────
  // 时间桶图表 —— SitChart 与页面时间轴（SitTimeline）联动
  //
  // spec.timeline：
  //   mode        'trend'（时间趋势：累积到当前桶并高亮）| 'bucket'（只看当前桶）
  //   bucketField 行上的时间桶键列（默认 bucketKey）
  //   valueField  数值列（默认 value）
  //   categoryField 可选分类列；为空则单系列
  // 数据来自后端预聚合的时序数据集（rows），页面端只做筛选/透视，不做业务聚合。
  // 未传 spec.timeline 的图表保持静态，不订阅时钟。
  // ────────────────────────────────────────────────────────────────
  var chartTimelineByEl = [];   // [el, unsubscribe]，重渲染时解除旧订阅
  var chartEntries = [];        // [{ node, repaint }]，阵营切换时统一重绘

  // ── 图表阵营过滤：系列名 / 类目轴 / 饼图项命中阵营时按当前阵营裁剪 ──
  function isFactionValue(v) {
    return !!normalizeFaction(v);
  }

  // 只保留当前阵营的系列；若一个系列都不剩则保持原样（避免整图空白）
  function applyFactionFilter(option) {
    if (!activeFaction || !option) return option;

    // 1. 类目轴全部是阵营值（如阵营对比柱图）→ 裁剪类目与各系列数据
    ['xAxis', 'yAxis'].forEach(function (key) {
      var axis = option[key];
      if (!axis || Array.isArray(axis)) return;
      var data = axis.data;
      if (!Array.isArray(data) || !data.length) return;
      var allFaction = data.every(function (v) { return isFactionValue(v); });
      if (!allFaction) return;
      var keep = [];
      data.forEach(function (v, i) {
        if (normalizeFaction(v) === activeFaction) keep.push(i);
      });
      if (!keep.length) return;
      axis.data = keep.map(function (i) { return data[i]; });
      (option.series || []).forEach(function (s) {
        if (Array.isArray(s.data)) s.data = keep.map(function (i) { return s.data[i]; });
      });
    });

    // 2. 系列名是阵营 → 只保留当前阵营系列（类目轴规则已裁剪时跳过）
    var series = option.series || [];
    var factionSeries = series.filter(function (s) { return isFactionValue(s.name); });
    if (factionSeries.length) {
      option.series = series.filter(function (s) {
        return !isFactionValue(s.name) || normalizeFaction(s.name) === activeFaction;
      });
    }

    // 3. 饼图/单系列数据项名为阵营 → 只保留当前阵营项
    series = option.series || [];
    if (series.length === 1 && Array.isArray(series[0].data)) {
      var items = series[0].data;
      var factionItems = items.filter(function (d) {
        return d && typeof d === 'object' && isFactionValue(d.name);
      });
      if (factionItems.length === items.length && items.length > 1) {
        series[0].data = items.filter(function (d) {
          return normalizeFaction(d.name) === activeFaction;
        });
      }
    }

    return option;
  }

  // 阵营切换后统一重绘所有已注册图表（时间轴图沿用最近一次 tick 的时刻）
  function repaintCharts() {
    chartEntries.slice().forEach(function (entry) {
      try { entry.repaint(); } catch (e) { reportError('图表阵营重绘失败: ' + (e && e.message)); }
    });
  }

  function registerChart(node, repaint) {
    chartEntries = chartEntries.filter(function (e) { return e.node !== node; });
    chartEntries.push({ node: node, repaint: repaint });
  }

  function timelineBucketLabel(key) {
    var s = String(key == null ? '' : key);
    return s.length >= 16 ? s.slice(11, 16) : s;
  }

  // 行字段读取：精确匹配优先，失败时按大小写不敏感兜底
  // （PostgreSQL 会把未加引号的别名折叠成小写，如 bucketKey → bucketkey）
  function timelineRowValue(row, field) {
    if (!row || !field) return null;
    if (row[field] != null) return row[field];
    var lower = String(field).toLowerCase();
    for (var k in row) {
      if (Object.prototype.hasOwnProperty.call(row, k) && k.toLowerCase() === lower) {
        return row[k];
      }
    }
    return null;
  }

  function buildTimelineModel(spec) {
    var tl = spec.timeline || {};
    var rows = spec.rows || [];
    var bucketField = tl.bucketField || 'bucketKey';
    var valueField = tl.valueField || 'value';
    var categoryField = tl.categoryField || '';
    var mode = tl.mode === 'bucket' ? 'bucket' : 'trend';
    var map = {};
    var buckets = [];
    rows.forEach(function (r) {
      var rawKey = timelineRowValue(r, bucketField);
      var key = String(rawKey == null ? '' : rawKey);
      if (!key) return;
      var t = parseTime(key);
      if (t === null) return;
      var b = map[key];
      if (!b) {
        b = map[key] = { key: key, t: t, label: timelineBucketLabel(key), values: {} };
        buckets.push(b);
      }
      var rawCat = categoryField ? timelineRowValue(r, categoryField) : null;
      var cat = categoryField ? String(rawCat == null ? '未知' : rawCat) : '';
      var v = toNum(timelineRowValue(r, valueField));
      b.values[cat] = (b.values[cat] || 0) + (v === null ? 0 : v);
    });
    buckets.sort(function (a, b) { return a.t - b.t; });
    return {
      mode: mode, valueField: valueField, categoryField: categoryField,
      buckets: buckets,
      categories: (function () {
        if (!categoryField) return [];
        var seen = {}, out = [];
        buckets.forEach(function (b) {
          Object.keys(b.values).forEach(function (c) {
            if (!seen[c]) { seen[c] = 1; out.push(c); }
          });
        });
        return out;
      })(),
    };
  }

  function buildTimelineChartOption(spec, model, timeText) {
    var tMs = parseTime(timeText);
    if (tMs === null) tMs = Infinity;
    var current = -1;
    for (var i = 0; i < model.buckets.length; i++) {
      if (model.buckets[i].t <= tMs) current = i;
    }
    if (current < 0) current = 0;
    var buckets = model.buckets;
    var cats = model.categories;
    var base = {
      type: spec.type, title: spec.title, yName: spec.yName,
      horizontal: spec.horizontal, stack: spec.stack,
      showDataZoom: spec.showDataZoom, percent: spec.percent,
      _compact: spec._compact,
    };

    if (model.mode === 'trend') {
      var xData = buckets.map(function (b) { return b.label; });
      var series;
      if (cats.length) {
        series = cats.map(function (c) {
          return {
            name: c,
            data: buckets.map(function (b, idx) {
              return idx <= current ? (b.values[c] || 0) : null;
            }),
          };
        });
      } else {
        series = [{
          name: model.valueField,
          data: buckets.map(function (b, idx) {
            return idx <= current ? (b.values[''] || 0) : null;
          }),
        }];
      }
      // 组装成 SitChart 的 spec 再走统一 buildOption，避免把裸 option 直接交给 ECharts
      var opt = buildOption(Object.assign({}, base, { xData: xData, series: series }));
      // 当前时刻标记：图表与地图同一 tick，视觉上明确"现在播到哪"
      if (current >= 0 && opt.series && opt.series.length) {
        opt.series[0].markLine = {
          symbol: 'none', silent: true, label: { show: false },
          lineStyle: { color: '#1d4ed8', type: 'dashed', width: 1.5 },
          data: [{ xAxis: current }],
        };
      }
      return opt;
    }

    // bucket：只取覆盖当前时刻的那一个桶
    var b = buckets[current] || { label: '', values: {} };
    var xData, series;
    if (spec.type === 'pie') {
      xData = [];
      series = [{
        name: model.valueField || '占比',
        data: (cats.length ? cats : [b.label]).map(function (c) {
          return { name: c || b.label || '—', value: b.values[c] || 0 };
        }),
      }];
    } else if (cats.length) {
      xData = cats;
      series = [{
        name: model.valueField,
        data: cats.map(function (c) { return b.values[c] || 0; }),
      }];
    } else {
      xData = [b.label];
      series = [{ name: model.valueField, data: [b.values[''] || 0] }];
    }
    return buildOption(Object.assign({}, base, { xData: xData, series: series }));
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
      // 解除同一容器的旧时间轴订阅（重渲染不叠加监听）
      var oldTl = chartTimelineByEl.filter(function (pair) { return pair[0] === node; })[0];
      if (oldTl) {
        try { oldTl[1](); } catch (e) { }
        chartTimelineByEl = chartTimelineByEl.filter(function (pair) { return pair[0] !== node; });
      }
      // 卡片已有 HTML 标题时不再让 ECharts 重画标题；容器过小时切换紧凑排版，
      // 避免标题、图例、坐标轴文字在同一块画布上互相压字
      var heading = cardHeadingOf(node);
      var boxW = node.clientWidth || 0;
      var boxH = node.clientHeight || 0;
      var compact = (boxH > 0 && boxH < 220) || (boxW > 0 && boxW < 380);
      var renderSpec = spec;
      if (spec.title && heading) renderSpec = Object.assign({}, spec, { title: '' });
      if (compact) renderSpec = Object.assign({}, renderSpec, { _compact: true });

      var tl = spec.timeline ? SitTimeline.current() : null;
      var model = (spec.timeline && spec.type !== 'radar' && spec.type !== 'scatter')
        ? buildTimelineModel(renderSpec) : null;
      if (model && !model.buckets.length) model = null;

      if (model && tl) {
        // 绑定页面时钟：只按桶索引变化重绘，避免每个 tick 空转 ECharts
        var paint = function (tick) {
          try {
            inst.setOption(applyFactionFilter(
              buildTimelineChartOption(renderSpec, model, tick && tick.t)), true);
          } catch (e) { reportError('图表时间轴渲染失败: ' + e.message); }
        };
        var lastTickIndex = tl.current().index;
        paint({ t: tl.current().t });
        var handler = function (s) {
          if (s.index === lastTickIndex) return;
          lastTickIndex = s.index;
          paint(s);
        };
        SitBus.on('timeline:tick', handler);
        chartTimelineByEl.push([node, function () { SitBus.off('timeline:tick', handler); }]);
        // 阵营切换时按当前时刻重绘，保证与地图同刻
        registerChart(node, function () { paint({ t: tl.current().t }); });
      } else if (model) {
        // 页面此时还没有时间轴（常见于 SitTimeline.render 写在脚本末尾）：
        // 先按"全部桶"静态展示避免空白，等时间轴创建后自动重绘并绑定
        var paintAll = function () {
          inst.setOption(applyFactionFilter(
            buildTimelineChartOption(renderSpec, model, '')), true);
        };
        try { paintAll(); } catch (e) { reportError('图表渲染失败: ' + e.message); }
        registerChart(node, paintAll);
        if (spec.timeline) {
          deferTimelineRebind(node, function () { SitChart.render(node, spec); });
        }
      } else {
        var repaintStatic = function () {
          inst.setOption(applyFactionFilter(buildOption(renderSpec)), true);
        };
        try { repaintStatic(); } catch (e) { reportError('图表渲染失败: ' + e.message); }
        registerChart(node, repaintStatic);
      }
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
  // 挂载一组瓦片图层，返回已挂载的图层实例
  function mountTiles(map, list) {
    var mounted = [];
    (list || []).forEach(function (cfg) {
      try {
        var opts = {
          opacity: cfg.opacity != null ? cfg.opacity : 1,
          minZoom: cfg.minZoom != null ? cfg.minZoom : 3,
          maxZoom: cfg.maxZoom != null ? cfg.maxZoom : 18,
          tms: !!cfg.tms, attribution: cfg.attribution || '',
        };
        if (cfg.subdomains) opts.subdomains = cfg.subdomains;
        mounted.push(window.L.tileLayer(cfg.urlTemplate, opts).addTo(map));
      } catch (e) { /* 单层失败跳过 */ }
    });
    return mounted;
  }

  // 挂载底图：主图层瓦片连续失败 6 次时，自动替换为备用图层（只回退一次）
  function addTiles(map) {
    var mounted = mountTiles(map, tileLayers);
    var fallback = fallbackTileLayers || [];
    if (!mounted.length || !fallback.length) return;
    var errorCount = 0;
    var applied = false;
    mounted.forEach(function (ly) {
      ly.on('tileerror', function () {
        errorCount += 1;
        if (applied || errorCount < 6) return;
        applied = true;
        mounted.forEach(function (l) { try { map.removeLayer(l); } catch (e) { } });
        mountTiles(map, fallback);
        console.warn('[SitMap] 底图瓦片加载失败，已回退为 GeoWebCache 备用图层');
      });
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
      // 图例 / 图层开关面板
      '.sit-legend{background:rgba(255,255,255,.94);border:1px solid #e2e8f0;border-radius:8px;',
      '  box-shadow:0 2px 10px rgba(15,23,42,.12);padding:8px 10px;font-size:12px;color:#1e293b;',
      '  max-width:260px;max-height:70%;overflow:auto;}',
      '.sit-legend-title{font-weight:600;font-size:12px;margin-bottom:5px;display:flex;',
      '  justify-content:space-between;align-items:center;cursor:pointer;user-select:none;}',
      '.sit-legend-actions{display:flex;align-items:center;gap:8px}',
      '.sit-legend-title .sit-legend-toggle,.sit-legend-reset{color:#64748b;font-size:11px}',
      '.sit-legend-reset{color:#1d4ed8;cursor:pointer}',
      '.sit-legend-group{margin-top:5px;padding-top:5px;border-top:1px dashed #e2e8f0}',
      '.sit-legend-sub{color:#64748b;font-size:11px;margin:2px 0 3px;font-weight:600}',
      '.sit-legend-row{display:flex;align-items:center;gap:6px;padding:2px 0;white-space:nowrap}',
      '.sit-legend-row label{display:flex;align-items:center;gap:6px;cursor:pointer;min-width:0}',
      '.sit-legend-cb{width:13px;height:13px;margin:0;accent-color:#1d4ed8;flex:none;cursor:pointer}',
      '.sit-legend-sw{width:20px;height:20px;flex:none;display:inline-flex;align-items:center;justify-content:center}',
      '.sit-legend-sw svg{width:20px;height:20px}',
      '.sit-legend-line{width:22px;height:0;border-top-style:solid;flex:none;margin:0 2px}',
      '.sit-legend-circle{width:16px;height:16px;border-radius:50%;flex:none;margin:0 3px}',
      '.sit-legend-air-head{cursor:pointer}',
      '.sit-legend-caret{width:12px;color:#94a3b8;font-size:10px;flex:none}',
      '.sit-legend-name{overflow:hidden;text-overflow:ellipsis;max-width:118px}',
      '.sit-legend-subs{padding-left:26px}',
      '.sit-legend-subrow{padding:1px 0;color:#475569}',
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

  // ── 图例：按地图上实际出现的要素生成可交互图层开关 ──
  function circleMetaOf(c) {
    var isRecon = c.kind === 'recon' || String(c.rangeType || '').indexOf('侦察') >= 0;
    var label = c.rangeType || (isRecon ? '侦察范围' : '打击范围');
    return {
      key: ['circle', label, String(c.faction || ''), isRecon ? 'recon' : 'strike'].join('|'),
      label: label, isRecon: isRecon,
      color: c.factionColor || FACTION_COLORS[c.faction] || (isRecon ? '#d97706' : '#dc2626'),
    };
  }

  function buildLegendModel(spec, playbackOn) {
    var pb = spec.playback === true ? {} : (spec.playback || {});
    var radiusMode = pb.radius || 'both';
    var trailOn = playbackOn && pb.trail !== false && !!window.turf;
    var aircraft = [];
    var seenTracks = {};
    (spec.tracks || []).forEach(function (t) {
      if ((t.points || []).length < 2) return;
      var key = trackKeyOf(t);
      if (!key || seenTracks[key]) return;
      seenTracks[key] = 1;
      var sv = toNum(t.strikeRadiusKm), rv = toNum(t.reconRadiusKm);
      var parts = defaultTrackParts();
      parts.reconCircle = playbackOn && radiusMode !== 'strike' && rv !== null && rv > 0;
      parts.strikeCircle = playbackOn && radiusMode !== 'recon' && sv !== null && sv > 0;
      parts.reconSweep = trailOn && parts.reconCircle;
      parts.strikeSweep = trailOn && parts.strikeCircle;
      var last = (t.points || [])[(t.points || []).length - 1] || {};
      aircraft.push({
        key: key, name: t.name || key,
        color: t.factionColor || FACTION_COLORS[t.faction] || hashColor(t.name),
        visual: resolveUnitVisual({
          unitKind: 'aircraft', type: t.category, faction: t.faction,
          factionColor: t.factionColor, symbol: t.symbol,
          name: t.name, heading: last.heading,
        }, true),
        parts: parts,
      });
    });

    var units = [], seenUnits = {};
    (spec.units || spec.points || []).forEach(function (u) {
      var v = resolveUnitVisual(u, true);
      var key = [v.kind, v.label, String(u.faction || ''), v.color].join('|');
      var row = seenUnits[key];
      if (!row) {
        row = seenUnits[key] = {
          key: key, label: v.label, visual: v, count: 0,
        };
        units.push(row);
      }
      row.count += 1;
    });

    var circles = [], seenCircles = {};
    (spec.circles || []).forEach(function (c) {
      var meta = circleMetaOf(c);
      if (!seenCircles[meta.key]) {
        seenCircles[meta.key] = 1;
        circles.push(meta);
      }
    });

    // 全局组只在确实存在对应要素时出现
    var hasReconCircle = circles.some(function (c) { return c.isRecon; })
      || aircraft.some(function (a) { return a.parts.reconCircle; });
    var hasStrikeCircle = circles.some(function (c) { return !c.isRecon; })
      || aircraft.some(function (a) { return a.parts.strikeCircle; });
    var groups = [];
    if (aircraft.length || circles.length) groups.push({ key: 'trackLine', label: '航迹线' });
    if (aircraft.some(function (a) { return a.parts.reconSweep; })) {
      groups.push({ key: 'reconSweep', label: '侦察扫掠区域' });
    }
    if (aircraft.some(function (a) { return a.parts.strikeSweep; })) {
      groups.push({ key: 'strikeSweep', label: '打击扫掠区域' });
    }
    if (hasReconCircle) groups.push({ key: 'reconRange', label: '侦察范围圈' });
    if (hasStrikeCircle) groups.push({ key: 'strikeRange', label: '打击范围圈' });
    return { groups: groups, aircraft: aircraft, units: units, circles: circles };
  }

  function addLayerControl(L, map, spec, api, playbackOn) {
    var model = buildLegendModel(spec, playbackOn);
    if (!model.groups.length && !model.units.length && !model.aircraft.length && !model.circles.length) return null;
    var state = ensureLayerState(api);

    function trackState(key) {
      if (!state.tracks[key]) state.tracks[key] = defaultTrackParts();
      return state.tracks[key];
    }
    function unitSw(v) {
      return '<span class="sit-legend-sw" style="background:transparent">'
        + '<svg viewBox="0 0 24 24"><g transform="translate(2,2) scale(0.84)">'
        + '<circle cx="12" cy="12" r="11.4" fill="' + v.color + '" stroke="#fff" stroke-width="1.6"/>'
        + (SIT_SHAPES[v.shape] || SIT_SHAPES.dot) + '</g></svg></span>';
    }
    function cb(scope, key, part, checked) {
      var attrs = ' type="checkbox" data-scope="' + scope + '" data-key="' + esc(key) + '"';
      if (part) attrs += ' data-part="' + esc(part) + '"';
      return '<input class="sit-legend-cb"' + attrs + (checked ? ' checked' : '') + '>';
    }
    function circleSw(c) {
      return '<span class="sit-legend-circle" style="background:' + c.color
        + '22;border:1.6px ' + (c.isRecon ? 'dashed' : 'solid') + ' ' + c.color + '"></span>';
    }

    var groupRows = model.groups.map(function (g) {
      return '<div class="sit-legend-row"><label>' + cb('group', g.key, '', state.groups[g.key] !== false)
        + '<span>' + esc(g.label) + '</span></label></div>';
    }).join('');

    var airRows = model.aircraft.map(function (a) {
      var st = trackState(a.key);
      var subs = [];
      subs.push({ part: 'aircraft', label: '飞机图标' });
      subs.push({ part: 'track', label: '航迹线' });
      if (a.parts.reconCircle) subs.push({ part: 'reconCircle', label: '侦察范围圈' });
      if (a.parts.strikeCircle) subs.push({ part: 'strikeCircle', label: '打击范围圈' });
      if (a.parts.reconSweep) subs.push({ part: 'reconSweep', label: '侦察扫掠带' });
      if (a.parts.strikeSweep) subs.push({ part: 'strikeSweep', label: '打击扫掠带' });
      var subRows = subs.map(function (s) {
        return '<div class="sit-legend-row sit-legend-subrow"><label>'
          + cb('track', a.key, s.part, st[s.part] !== false)
          + '<span>' + esc(s.label) + '</span></label></div>';
      }).join('');
      return '<div class="sit-legend-air">'
        + '<div class="sit-legend-row sit-legend-air-head">'
        + cb('track', a.key, 'all', st.all !== false)
        + '<span class="sit-legend-caret">▶</span>' + unitSw(a.visual)
        + '<span class="sit-legend-name">' + esc(a.name) + '</span>'
        + '</div>'
        + '<div class="sit-legend-subs" style="display:none">' + subRows + '</div>'
        + '</div>';
    }).join('');

    var unitRows = model.units.map(function (u) {
      return '<div class="sit-legend-row"><label>'
        + cb('unit', u.key, '', state.units[u.key] !== false)
        + unitSw(u.visual) + '<span>' + esc(u.label) + '</span>'
        + '</label></div>';
    }).join('');

    var circleRows = model.circles.map(function (c) {
      return '<div class="sit-legend-row"><label>'
        + cb('circle', c.key, '', state.circles[c.key] !== false)
        + circleSw(c) + '<span>' + esc(c.label) + '</span>'
        + '</label></div>';
    }).join('');

    var LegendCtl = L.Control.extend({
      options: { position: 'bottomright' },
      onAdd: function () {
        var box = L.DomUtil.create('div', 'sit-legend');
        box.innerHTML =
          '<div class="sit-legend-title"><span>图层 / 图例</span>'
          + '<span class="sit-legend-actions">'
          + '<span class="sit-legend-reset" title="全部显示">全显</span>'
          + '<span class="sit-legend-toggle">收起 ▼</span></span></div>'
          + '<div class="sit-legend-body">'
          + (groupRows ? '<div class="sit-legend-group"><div class="sit-legend-sub">图层开关</div>' + groupRows + '</div>' : '')
          + (airRows ? '<div class="sit-legend-group"><div class="sit-legend-sub">飞机（逐架次）</div>' + airRows + '</div>' : '')
          + (unitRows ? '<div class="sit-legend-group"><div class="sit-legend-sub">其它要素</div>' + unitRows + '</div>' : '')
          + (circleRows ? '<div class="sit-legend-group"><div class="sit-legend-sub">范围圈</div>' + circleRows + '</div>' : '')
          + '</div>';
        var bodyEl = box.querySelector('.sit-legend-body');
        var toggleEl = box.querySelector('.sit-legend-toggle');
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.disableScrollPropagation(box);
        box.querySelector('.sit-legend-title').addEventListener('click', function (e) {
          if (e.target && e.target.classList.contains('sit-legend-reset')) return;
          var hidden = bodyEl.style.display === 'none';
          bodyEl.style.display = hidden ? '' : 'none';
          toggleEl.textContent = hidden ? '收起 ▼' : '展开 ▲';
        });
        // 全显：恢复所有开关与勾选状态
        box.querySelector('.sit-legend-reset').addEventListener('click', function () {
          Object.keys(state.groups).forEach(function (k) { state.groups[k] = true; });
          Object.keys(state.tracks).forEach(function (k) {
            var parts = defaultTrackParts();
            Object.keys(parts).forEach(function (p) { state.tracks[k][p] = parts[p]; });
          });
          Object.keys(state.units).forEach(function (k) { state.units[k] = true; });
          Object.keys(state.circles).forEach(function (k) { state.circles[k] = true; });
          Array.prototype.forEach.call(box.querySelectorAll('input[type="checkbox"]'), function (el) {
            el.checked = true;
          });
          api._applyVisibility();
        });
        // 逐机展开/收起（点复选框本身不触发）
        box.addEventListener('click', function (e) {
          var head = e.target && e.target.closest ? e.target.closest('.sit-legend-air-head') : null;
          if (!head || (e.target.tagName === 'INPUT')) return;
          var subs = head.parentNode.querySelector('.sit-legend-subs');
          var caret = head.querySelector('.sit-legend-caret');
          var open = subs.style.display === 'none';
          subs.style.display = open ? '' : 'none';
          if (caret) caret.textContent = open ? '▼' : '▶';
        });
        box.addEventListener('change', function (e) {
          var t = e.target;
          if (!t || t.tagName !== 'INPUT') return;
          var scope = t.getAttribute('data-scope');
          var key = t.getAttribute('data-key');
          var part = t.getAttribute('data-part');
          var on = !!t.checked;
          if (scope === 'group') state.groups[key] = on;
          else if (scope === 'track') {
            var st = trackState(key);
            if (part === 'all') st.all = on; else st[part] = on;
          } else if (scope === 'unit') state.units[key] = on;
          else if (scope === 'circle') state.circles[key] = on;
          api._applyVisibility();
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
      // 图层引用只对本次渲染有效；可见性状态 api._layerState 保留（重渲染不丢开关）
      api._refs = { units: [], tracks: [], circles: [] };
      // 页面时间轴订阅需先解除，避免重渲染后旧地图实例继续接收 tick
      if (api._timelineOff) { try { api._timelineOff(); } catch (e) { } api._timelineOff = null; }
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
  //   playback: { interval, radius:'strike'|'recon'|'both',
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
  // 播放条：播放/暂停、进度拖动、完整时间标签、重置（不提供倍速）。
  // 回放为逐帧离散显示：每帧对齐一条真实航迹采样点，不做插值。
  // ────────────────────────────────────────────────────────────────

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
    // 页面级时间轴模式：由 SitTimeline 提供统一刻度与时钟，地图只负责"按 t 重绘"，
    // 不创建自带播放条、不使用日内归一化（cfg.external / cfg.axis 由 SitMap.render 注入）
    var externalAxis = Array.isArray(cfg.axis) && cfg.axis.length ? cfg.axis : null;
    var tracks = (spec.tracks || []).filter(function (t) { return (t.points || []).length >= 2; });
    if (!tracks.length) return null;

    var mode = cfg.radius || 'both';
    var wantStrike = mode !== 'recon';
    var wantRecon = mode !== 'strike';
    var wantTrail = cfg.trail !== false && !!window.turf;
    var steps = Math.max(4, toNum(cfg.trailSteps) || 16);
    var interval = Math.max(80, toNum(cfg.interval) || 500);
    var THROTTLE = 250;   // 扫掠多边形重算节流（turf.buffer 基于 JSTS，逐帧调用会卡顿）

    // 逐架次图层开关查询（由 SitMap 注入 api._partVisible；缺失时视为全显）
    function allow(it, part) {
      if (!factionAllowed(it.track && it.track.faction)) return false;
      return api._partVisible ? api._partVisible(it.track, part) : true;
    }

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
    var dayNorm = externalAxis ? false
      : cfg.dayNormalize === true ? true
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

    // 时间刻度：
    // 1. 页面级时间轴（externalAxis）直接沿用 SitTimeline 的统一桶刻度，保证地图与图表同刻；
    // 2. 旧式回放由航迹点/事件时刻去重排序生成，标签统一为 YYYY-MM-DD HH:MM:SS。
    var axis;
    if (externalAxis) {
      axis = externalAxis.map(function (b) {
        return { t: parseTime(b && b.t), label: String((b && b.label) || '') };
      }).filter(function (b) { return b.t !== null; })
        .sort(function (a, b) { return a.t - b.t })
        .map(function (b) { return { t: b.t, label: b.label || fmtDateTime(b.t) }; });
    } else {
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
      axis = Object.keys(axisMap).map(Number)
        .sort(function (a, b) { return a - b; })
        .map(function (v) { return { t: v, label: axisMap[v] }; });
    }
    if (axis.length < 2) return null;

    var total = axis.length;
    var idx = 0;
    var playing = false;
    var timer = null;
    var lastBuffer = 0;
    var listeners = [];

    // 当前帧对应的真实航迹采样点：取不晚于 t 的最后一个有效点，不做插值。
    // 使用生效时刻 et（归一化时为虚拟日内毫秒）；无时间字段的航迹固定停在最后一点。
    // 早于首点的位置仍返回首点，是否在空由 airborneAt() 判定。
    function posAt(it, t) {
      var pts = it.pts, ts = it.et, n = pts.length;
      function at(i) {
        return {
          lng: toNum(pts[i].lng), lat: toNum(pts[i].lat),
          heading: toNum(pts[i].heading), index: i,
        };
      }
      if (!it.hasTime) return at(n - 1);
      if (t <= ts[0]) return at(0);
      var lo = 0, hi = n - 1, hit = 0;
      while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (ts[mid] !== null && ts[mid] <= t) { hit = mid; lo = mid + 1; }
        else { hi = mid - 1; }
      }
      return at(hit);
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

    // 已飞航段的 Leaflet 坐标：起点 → 当前帧对应的真实采样点（不做插值补点）
    function flownCoords(it, pos) {
      var out = [];
      for (var i = 0; i <= pos.index && i < it.pts.length; i++) {
        var lng = toNum(it.pts[i].lng), lat = toNum(it.pts[i].lat);
        if (lng !== null && lat !== null) out.push(toLatLng(lng, lat));
      }
      return out;
    }

    function clearPlane(it) {
      var vis = it.vis;
      if (vis.plane) {
        try { map.removeLayer(vis.plane); } catch (e) { }
        vis.plane = null; vis.rot = null;
      }
    }

    function clearLine(it) {
      var vis = it.vis;
      if (vis.line) {
        try { map.removeLayer(vis.line); } catch (e) { }
        vis.line = null; vis.weight = null;
      }
    }

    // 移除单个架次的飞机图标与渐进航迹层
    function clearItemVis(it) {
      clearPlane(it);
      clearLine(it);
    }

    // 飞机图标：机型象形符号、机头朝当前航向；只更新位置与朝向，不重建 DOM
    function renderPlane(it, pos) {
      var vis = it.vis;
      var ll = toLatLng(pos.lng, pos.lat);
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
    }

    // 渐进航迹："飞机到哪航迹画到哪"，从不预画整条航迹
    function renderTrackLine(it, pos) {
      var vis = it.vis;
      var coords = flownCoords(it, pos);
      if (coords.length < 2) {
        clearLine(it);
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

    // 事件点可见性 = 时间门控 && 阵营匹配 && 所属要素分组开关
    function eventAllowed(ref) {
      if (ref.faction && !factionAllowed(ref.faction)) return false;
      if (ref.unitKey && api._unitVisible && !api._unitVisible(ref.unitKey)) return false;
      return true;
    }

    // 按当前播放时刻刷新全部事件点显隐（回退/重置时未到时刻的事件点会重新隐藏）
    function applyEventVisibility(t) {
      eventRefs.forEach(function (ref) {
        setEventShown(ref, t >= ref.et && eventAllowed(ref));
      });
    }

    // 由 SitMap.render 的 units 渲染调用：把事件点交给播放器按时刻显隐
    // meta: { faction, unitKey } —— 供阵营筛选与图例分组开关使用
    function registerEvent(marker, timeText, container, meta) {
      var v = parseTime(timeText);
      var info = meta || {};
      if (v === null) {
        // 时间缺失/不可解析：常显（与历史行为一致），但仍受阵营/分组开关控制
        var ref0 = { marker: marker, et: null, container: container || null, shown: false,
                     faction: info.faction || '', unitKey: info.unitKey || '' };
        eventRefs.push(ref0);
        setEventShown(ref0, eventAllowed(ref0));
        return;
      }
      var ref = {
        marker: marker, et: dayNorm ? (v - dayStartMs(v)) : v,
        container: container || null, shown: false,
        faction: info.faction || '', unitKey: info.unitKey || '',
      };
      eventRefs.push(ref);
      // 播放器创建时已渲染过首帧，这里按当前时刻立即判定，避免首帧闪出未到时刻的事件
      setEventShown(ref, axis[idx].t >= ref.et && eventAllowed(ref));
    }

    function renderAt(t, force) {
      var now = Date.now();
      var doBuffer = wantTrail && (force || now - lastBuffer >= THROTTLE);
      if (doBuffer) lastBuffer = now;

      items.forEach(function (it) {
        var pos = posAt(it, t);
        // 生命周期：未出动/已返航、坐标缺失或阵营不匹配 → 全部图层一并移除
        var airborne = airborneAt(it, t) && factionAllowed(it.track && it.track.faction)
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

        // 飞机图标 + 渐进航迹：逐项受图层开关控制（关闭时即时移除已建图层）
        if (allow(it, 'aircraft')) renderPlane(it, pos); else clearPlane(it);
        if (allow(it, 'track')) renderTrackLine(it, pos); else clearLine(it);
        if (!it.defs.length) return;

        var ll = toLatLng(pos.lng, pos.lat);
        it.defs.forEach(function (def, i) {
          var slot = it.slots[i];
          if (!slot) slot = it.slots[i] = { circle: null, trail: null };
          var color = rangeColor(it.track, def.kind);
          var isRecon = def.kind === 'recon';
          var circlePart = isRecon ? 'reconCircle' : 'strikeCircle';
          var sweepPart = isRecon ? 'reconSweep' : 'strikeSweep';

          // 动态能力圈：圆心=飞机当前位置；侦察虚线、打击实线
          if (!allow(it, circlePart)) {
            if (slot.circle) { try { map.removeLayer(slot.circle); } catch (e) { } slot.circle = null; }
          } else if (!slot.circle) {
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
          if (!allow(it, sweepPart)) {
            if (slot.trail) { try { map.removeLayer(slot.trail); } catch (e) { } slot.trail = null; }
            return;
          }
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
      };
      listeners.forEach(function (fn) {
        try { fn(payload); } catch (e) { reportError('播放器事件处理异常: ' + e.message); }
      });
    }

    function stopTimer() {
      if (timer) { clearInterval(timer); timer = null; }
    }

    // 固定节奏逐帧前进（不提供倍速）
    function startTimer() {
      stopTimer();
      timer = setInterval(step, Math.max(80, interval));
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
      current: function () {
        return { index: idx, time: axis[idx] ? axis[idx].label : '',
                 t: axis[idx] ? fmtDateTime(axis[idx].t) : '' };
      },
      // 页面级时间轴联动：外部时钟直接按桶索引驱动重绘（不改动内部计时器）
      seekIndex: function (i, silent) {
        var n = toNum(i);
        if (n === null) return;
        idx = Math.max(0, Math.min(total - 1, Math.round(n)));
        renderAt(axis[idx].t, true);
        if (!silent) emit();
      },
      axis: function () {
        return axis.map(function (b) { return { t: fmtDateTime(b.t), label: b.label }; });
      },
      // 把事件类点交给播放器按事件时刻显隐（由 units 渲染调用）
      registerEvent: registerEvent,
      // 图层开关/阵营变化后按当前帧重绘（不改变播放状态）
      refresh: function () { renderAt(axis[idx].t, true); emit(); },
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
    // 页面级时间轴模式（cfg.external）不建地图内播放条：播放控件统一由 SitTimeline 提供
    var control = null;
    if (cfg.showBar !== false && !cfg.external) {
      var PlaybackCtl = L.Control.extend({
        options: { position: 'bottomleft' },
        onAdd: function () {
          var box = L.DomUtil.create('div', 'sit-playback');
          box.innerHTML =
            '<button class="sit-pb-btn" data-act="toggle">▶ 播放</button>'
            + '<input class="sit-pb-range" type="range" min="0" max="1000" step="1" value="0">'
            + '<span class="sit-pb-time">—</span>'
            + '<button class="sit-pb-btn" data-act="reset">重置</button>';
          L.DomEvent.disableClickPropagation(box);
          L.DomEvent.disableScrollPropagation(box);
          var btn = box.querySelector('[data-act="toggle"]');
          var range = box.querySelector('.sit-pb-range');
          var label = box.querySelector('.sit-pb-time');
          btn.addEventListener('click', function () { playback.toggle(); });
          box.querySelector('[data-act="reset"]').addEventListener('click', function () { reset(); });
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
            btn.textContent = s.playing ? '⏸ 暂停' : '▶ 播放';
          });
          return box;
        },
      });
      control = new PlaybackCtl();
      map.addControl(control);
    }

    renderAt(axis[0].t, true);
    if (!cfg.external) emit();
    return playback;
  }

  // ────────────────────────────────────────────────────────────────
  // SitTimeline —— 页面级时间轴（与 SitChart / SitMap / SitTable 同级）
  //
  // 页面唯一时钟：负责刻度、播放/暂停/拖动，并通过 SitBus 广播
  // 'timeline:tick'（payload 含 index/total/ratio/time/t/playing）。
  // 逐帧回放：固定 1 秒/帧，不提供倍速；每帧对齐一条真实采样时刻。
  // **无头时钟**：控件由宿主页面（PageSandbox 底部浮层）渲染，这里只维护状态，
  // 不再生成播放条 DOM，避免页内与宿主出现两套控件、两个时钟源。
  // 地图与图表只订阅事件，不再各自维护时钟：
  //   - SitMap.render(el, { timeline: true }) 绑定本时钟，不创建地图内播放条；
  //   - SitChart.render(el, { timeline: {...} }) 按当前时刻过滤/切片时间桶数据；
  //   - 未传 timeline 的图表保持静态。
  // 刻度来源：spec.axis 优先，否则读取注入数据包 data.timeline.buckets。
  // ────────────────────────────────────────────────────────────

  var timelineInstance = null;
  // 固定帧间隔：逐帧回放，不提供倍速
  var TIMELINE_FRAME_MS = 1000;

  // 延迟绑定队列：页面常把 SitTimeline.render 写在脚本末尾（先画图表/地图），
  // 此时 SitChart/SitMap 取不到页面时钟，会退化为静态渲染。这里记下待重绑的渲染调用，
  // 等时间轴创建后统一重绘，避免"能拖动时间轴但图表地图不动"。
  var pendingTimelineRebinds = [];
  function deferTimelineRebind(node, rerender) {
    pendingTimelineRebinds = pendingTimelineRebinds.filter(function (p) { return p.node !== node; });
    pendingTimelineRebinds.push({ node: node, rerender: rerender });
  }
  function flushTimelineRebinds() {
    var list = pendingTimelineRebinds;
    pendingTimelineRebinds = [];
    list.forEach(function (p) {
      try { p.rerender(); } catch (e) { reportError('时间轴延迟绑定失败: ' + (e && e.message)); }
    });
  }

  // 向宿主浮层同步当前时刻（宿主据此绘制进度线、时刻与按钮状态）
  function postTimelineState(s) {
    try {
      window.parent.postMessage({
        type: 'ipage:timeline',
        index: s.index, total: s.total, ratio: s.ratio,
        time: s.time, t: s.t, playing: s.playing,
      }, '*');
    } catch (e) { }
  }

  function normalizeTimelineAxis(list) {
    var out = [];
    (list || []).forEach(function (b) {
      var t = parseTime(b && b.t);
      if (t === null) return;
      out.push({ t: t, label: String((b && b.label) || fmtDateTime(t)) });
    });
    out.sort(function (a, b) { return a.t - b.t; });
    return out;
  }

  function timelineAxisFromData() {
    var data = state && state.data;
    var buckets = data && data.timeline && data.timeline.buckets;
    return normalizeTimelineAxis(buckets);
  }

  function createTimelineInstance(axis) {
    var idx = 0;
    var playing = false;
    var timer = null;
    var listeners = [];
    var node = null;

    var axisOut = axis.map(function (b) { return { t: fmtDateTime(b.t), label: b.label }; });
    var total = axis.length;

    function payload() {
      return {
        index: idx, total: total,
        ratio: total > 1 ? idx / (total - 1) : 0,
        time: axis[idx] ? axis[idx].label : '',
        t: axis[idx] ? fmtDateTime(axis[idx].t) : '',
        playing: playing,
      };
    }

    function notify() {
      var s = payload();
      postTimelineState(s);
      listeners.forEach(function (fn) {
        try { fn(s); } catch (e) { reportError('时间轴事件处理异常: ' + e.message); }
      });
      SitBus.emit('timeline:tick', s);
    }

    function stopTimer() { if (timer) { clearInterval(timer); timer = null; } }
    // 固定 1 秒/帧：逐帧回放，不提供倍速
    function startTimer() { stopTimer(); timer = setInterval(step, TIMELINE_FRAME_MS); }

    function step() {
      if (idx >= total - 1) { pause(); return; }
      idx += 1;
      notify();
    }

    function play() {
      if (playing || total < 2) return;
      if (idx >= total - 1) idx = 0;
      playing = true;
      startTimer();
      notify();
    }

    function pause() {
      stopTimer();
      playing = false;
      notify();
    }

    function seekIndex(i) {
      var n = toNum(i);
      if (n === null) return;
      idx = Math.max(0, Math.min(total - 1, Math.round(n)));
      notify();
    }

    function seek(ratio) {
      var r = toNum(ratio);
      r = r === null ? 0 : Math.max(0, Math.min(1, r));
      seekIndex(Math.round(r * (total - 1)));
    }

    function reset() {
      pause();
      idx = 0;
      notify();
    }

    function mount(el) {
      // 无头时钟：不再向页面容器绘制播放条，控件统一由宿主浮层提供。
      node = el;
    }

    var api = {
      play: play, pause: pause, reset: reset, seek: seek, seekIndex: seekIndex,
      toggle: function () { if (playing) pause(); else play(); },
      isPlaying: function () { return playing; },
      total: total,
      current: payload,
      axis: function () { return axisOut.slice(); },
      on: function (fn) {
        if (typeof fn === 'function') listeners.push(fn);
        return function () {
          listeners = listeners.filter(function (f) { return f !== fn; });
        };
      },
      attach: mount,
      // 首次挂载后主动向宿主同步一次，宿主浮层无需等到第一次 tick 才出现
      postState: function () { postTimelineState(payload()); },
      destroy: function () {
        stopTimer();
        playing = false;
        listeners = [];
        if (timelineInstance === api) timelineInstance = null;
      },
    };
    return api;
  }

  var SitTimeline = {
    render: function (el, spec) {
      var node = resolveEl(el);
      spec = spec || {};
      var axis = normalizeTimelineAxis(spec.axis && spec.axis.length ? spec.axis : timelineAxisFromData());
      if (!node) { reportError('时间轴容器不可用'); return null; }
      if (axis.length < 2) {
        // 单桶/无刻度时退回静态页面：清空容器并销毁旧实例，避免遗留僵尸计时器
        if (timelineInstance) timelineInstance.destroy();
        node.innerHTML = '';
        return null;
      }
      if (!timelineInstance) timelineInstance = createTimelineInstance(axis);
      timelineInstance.attach(node);
      timelineInstance.postState();
      // 时间轴创建前已渲染的图表/地图在这里补绑，保证拖动立刻生效
      flushTimelineRebinds();
      return timelineInstance;
    },
    current: function () { return timelineInstance; },
    destroy: function () { if (timelineInstance) timelineInstance.destroy(); },
  };

  // 宿主浮层下发的时间轴操作（播放/暂停/seek/重置）→ 驱动唯一时钟
  function applyTimelineCommand(msg) {
    var inst = timelineInstance;
    if (!inst) return;
    try {
      if (msg.action === 'toggle') inst.toggle();
      else if (msg.action === 'play') inst.play();
      else if (msg.action === 'pause') inst.pause();
      else if (msg.action === 'reset') inst.reset();
      // 拖动进度先暂停（与原页内播放条行为一致），避免播放计时器覆盖用户拖动位置
      else if (msg.action === 'seek') { inst.pause(); inst.seek(msg.value); }
      else if (msg.action === 'seekIndex') inst.seekIndex(msg.value);
    } catch (e) { reportError('时间轴命令执行失败: ' + (e && e.message)); }
  }

  // 页面级阵营筛选：宿主浮层下发后同时作用于地图与图表
  function applyFaction(value) {
    var next = normalizeFaction(value) || String(value || '').trim();
    if (next === activeFaction) return;
    activeFaction = next;
    mapByEl.forEach(function (pair) {
      var api = pair[1];
      try {
        if (api._applyVisibility) api._applyVisibility();
      } catch (e) { reportError('阵营筛选应用失败: ' + (e && e.message)); }
    });
    repaintCharts();
    // 通知业务页面：KPI/表格等可自行订阅做扩展联动
    SitBus.emit('filter', { faction: activeFaction });
    SitBus.emit('faction:change', activeFaction);
  }

  // 宿主下发可视高度：写入 --ipage-vh 供页面做"一屏"布局，并重排图表
  function applyViewportHeight(h) {
    var n = toNum(h);
    if (n === null || n <= 0) return;
    document.documentElement.style.setProperty('--ipage-vh', Math.round(n) + 'px');
    setTimeout(function () {
      echartsInstances.forEach(function (inst) { try { inst.resize(); } catch (e) { } });
      postHeight();
    }, 60);
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
          _refs: { units: [], tracks: [], circles: [] },
          _clickFns: [],
          _userInteracted: false,
        };
        // 图层可见性状态在同一容器重渲染间保留（默认全显）
        ensureLayerState(api);
        // 用户一旦交互（拖动/缩放/双击），永久锁定视图，后续重渲染不再自动适配
        map.on('mousedown touchstart wheel dblclick', function () { api._userInteracted = true; });
        mapByEl.push([node, api]);
        isFirstRender = true;
      }

      var clickFns = api._clickFns = [];
      var featureLayers = api._layers.featureLayers = [];
      var trackLines = api._layers.trackLines = [];
      var startMarkers = api._layers.startMarkers = [];
      var refs = api._refs = { units: [], tracks: [], circles: [] };
      var layerState = ensureLayerState(api);
      var bounds = [];
      function pushBounds(ll) { bounds.push(ll); }

      // 逐机图层可见性：阵营 && 总开关 && 全局组 && 子项
      api._partVisible = function (track, part) {
        if (!factionAllowed(track && track.faction)) return false;
        var key = trackKeyOf(track);
        var st = layerState.tracks[key];
        if (!st) st = layerState.tracks[key] = defaultTrackParts();
        if (st.all === false) return false;
        var group = TRACK_PART_GROUPS[part];
        if (group && layerState.groups[group] === false) return false;
        return st[part] !== false;
      };
      api._unitVisible = function (key) {
        return !key || layerState.units[key] !== false;
      };
      // 统一应用静态图层显隐，并刷新回放当前帧
      api._applyVisibility = function () {
        refs.units.forEach(function (ref) {
          var show = factionAllowed(ref.faction) && layerState.units[ref.key] !== false;
          try {
            if (ref.cluster) {
              if (show) ref.cluster.addLayer(ref.layer); else ref.cluster.removeLayer(ref.layer);
            } else if (show) {
              if (!map.hasLayer(ref.layer)) ref.layer.addTo(map);
            } else if (map.hasLayer(ref.layer)) {
              map.removeLayer(ref.layer);
            }
          } catch (e) { }
        });
        refs.tracks.forEach(function (ref) {
          var showLine = api._partVisible(ref.track, 'track');
          var showPlane = api._partVisible(ref.track, 'aircraft');
          function setLayer(layer, show) {
            if (!layer) return;
            try {
              if (show) { if (!map.hasLayer(layer)) layer.addTo(map); }
              else if (map.hasLayer(layer)) map.removeLayer(layer);
            } catch (e) { }
          }
          setLayer(ref.line, showLine);
          setLayer(ref.startMarker, showLine);
          setLayer(ref.endMarker, showPlane);
        });
        refs.circles.forEach(function (ref) {
          var groupOk = layerState.groups[ref.isRecon ? 'reconRange' : 'strikeRange'] !== false;
          var show = factionAllowed(ref.faction) && groupOk
            && layerState.circles[ref.key] !== false;
          try {
            if (show) { if (!map.hasLayer(ref.layer)) ref.layer.addTo(map); }
            else if (map.hasLayer(ref.layer)) map.removeLayer(ref.layer);
          } catch (e) { }
        });
        if (api.playback) { try { api.playback.refresh(); } catch (e) { } }
      };

      // ── 时间轴回放（内置播放器 + 动态能力圈 + 扫掠留痕 + 事件点按时刻显隐）──
      // 新契约：spec.timeline=true 时绑定页面级 SitTimeline，只按 tick 重绘，不建地图内播放条；
      // 兼容：spec.playback 仍走旧式地图内播放器，历史页面行为不变。
      // 必须先创建播放器：它是否真的建得起来（有时间轴且航迹可用）决定静态整条航迹
      // 是否交给播放器接管（playbackOn），也决定事件类点是否交给播放器按时刻显隐。
      api.playback = null;
      api._timelineOff = null;
      var pageTimeline = spec.timeline ? SitTimeline.current() : null;
      if (spec.timeline && !pageTimeline) {
        // 时间轴可能写在脚本末尾：先静态渲染，等时钟创建后自动重绘并绑定
        deferTimelineRebind(node, function () { SitMap.render(node, spec); });
      }
      var playbackSpec = spec;
      if (pageTimeline) {
        // 把页面统一刻度注入旧播放器的渲染层：外部时钟 + 关闭归一化 + 不建自带播放条
        playbackSpec = Object.assign({}, spec, {
          playback: Object.assign({}, (spec.playback === true ? {} : (spec.playback || {})), {
            axis: pageTimeline.axis(), external: true, showBar: false, dayNormalize: false,
          }),
        });
      }
      if ((spec.playback || pageTimeline) && (spec.tracks || []).length) {
        api.playback = createPlayback(L, map, playbackSpec, api);
        api._layers.playback = api.playback;
      }
      if (api.playback && pageTimeline) {
        // 首帧对齐页面时钟当前索引，之后仅按桶索引变化重绘（避免地图与图表不同刻）
        try { api.playback.seekIndex(pageTimeline.current().index, true); } catch (e) { }
        var lastTimelineIndex = pageTimeline.current().index;
        api._timelineOff = pageTimeline.on(function (s) {
          if (s.index === lastTimelineIndex) return;   // 仅播放状态变化时不做多余重绘
          lastTimelineIndex = s.index;
          try { api.playback.seekIndex(s.index, true); } catch (e) { }
        });
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
        // 单位分组开关键：与图例 buildLegendModel 的口径保持一致
        var unitKey = [visual.kind, visual.label, String(unit.faction || ''), visual.color].join('|');
        // 事件语义判定复用 normalizeUnitKind，避免与符号解析各自维护一套类别映射
        var eventGated = playbackOn && normalizeUnitKind(unit).indexOf('event_') === 0;
        if (eventGated) {
          api.playback.registerEvent(marker, unit.time, cluster,
            { faction: unit.faction || '', unitKey: unitKey });
        } else {
          refs.units.push({ layer: marker, key: unitKey, faction: unit.faction || '', cluster: cluster });
          var unitShow = factionAllowed(unit.faction) && layerState.units[unitKey] !== false;
          if (cluster) { if (unitShow) cluster.addLayer(marker); }
          else if (unitShow) marker.addTo(map);
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
        refs.tracks.push({
          track: track, line: line, startMarker: startMarker, endMarker: endMarker,
        });
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
        var circleMeta = circleMetaOf(c);
        refs.circles.push({
          layer: circle, key: circleMeta.key, faction: c.faction || '',
          isRecon: circleMeta.isRecon,
        });
      });

      // ── 图例 / 图层开关（全局组 + 逐机子项 + 单位组 + 静态圈）──
      api._layers.legendControl = addLayerControl(L, map, spec, api, playbackOn);
      // 应用当前图层状态（含阵营与历史开关）
      api._applyVisibility();

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
    // 业务脚本已创建时间轴时，再补发一次初始状态（宿主可能早于脚本就绪）
    if (timelineInstance) timelineInstance.postState();
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
    if (msg.type === 'ipage:viewport') { applyViewportHeight(msg.height); return; }
    if (msg.type === 'ipage:timeline-cmd') { applyTimelineCommand(msg); return; }
    if (msg.type === 'ipage:faction') { applyFaction(msg.value); return; }
    if (msg.type !== 'ipage:data' || !msg.payload) return;
    state = msg.payload;
    tileLayers = state.tileLayers || [];
    fallbackTileLayers = state.fallbackTileLayers || [];
    boot();
  });

  // ── 暴露受限 API（只读，不可重写）──
  Object.defineProperty(window, 'SitApp', { value: SitApp, writable: false, configurable: false });
  Object.defineProperty(window, 'SitChart', { value: SitChart, writable: false, configurable: false });
  Object.defineProperty(window, 'SitMap', { value: SitMap, writable: false, configurable: false });
  Object.defineProperty(window, 'SitBus', { value: SitBus, writable: false, configurable: false });
  Object.defineProperty(window, 'SitTimeline', { value: SitTimeline, writable: false, configurable: false });
  Object.defineProperty(window, 'SitUtil', { value: SitUtil, writable: false, configurable: false });
  Object.defineProperty(window, 'SitTable', { value: SitTable, writable: false, configurable: false });

  if (document.readyState !== 'loading') sendReady();
  else document.addEventListener('DOMContentLoaded', sendReady);
})();
