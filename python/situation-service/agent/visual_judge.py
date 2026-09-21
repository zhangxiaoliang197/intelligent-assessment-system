"""视觉评审器 —— playwright 渲染 + 规则取证 + VLM rubric 评分 + 强制择优。

对应方案：态势图-版式骨架与视觉反馈循环方案 §四。吸收的业界实践：
- SheetDesigner：规则反思 + 视觉反思双通道（对齐/溢出用规则，平衡/美观用 VLM）；
- ReLook：Forced Optimization——仅接受严格提升的修订，保留最佳而非最新；
- Tenten UI 修复实践：诊断先行（最大问题→元素→改法），小步定向补丁；
- vanja.io：契约先行——确定性 gate 先跑，品味留给 VLM。

可选依赖设计：playwright/chromium 未安装时 is_available()=False，
adaptive_layout 返回 None，调用方走现有降级链（artifact → 布局树 → 固定三段），
行为与现状完全兼容。
"""
import asyncio
import base64
import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional

import config
from llm_client import call_llm_vision

logger = logging.getLogger("situation-service")

# ── 可选依赖探测（结果缓存） ──
_playwright_available: Optional[bool] = None


def is_available() -> bool:
    """探测 playwright + chromium 是否真正可用（结果缓存）。

    只 import 成功不够：Docker 镜像可能装了 playwright Python 包但未下载浏览器，
    此时 chromium.executable_path 不存在，应直接判定不可用（调用方零开销降级）。
    探测期间临时屏蔽 asyncio 清理竞态日志（sync_playwright 退出时的已知噪声）。
    """
    global _playwright_available
    if _playwright_available is None:
        asyncio_logger = logging.getLogger("asyncio")
        asyncio_disabled = asyncio_logger.disabled
        asyncio_logger.disabled = True
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                exe = pw.chromium.executable_path
                _playwright_available = bool(exe and os.path.exists(str(exe)))
            if not _playwright_available:
                logger.warning(
                    "playwright 已安装但 chromium 浏览器未下载，视觉评审循环停用"
                    "（如需启用请执行 playwright install chromium）"
                )
        except Exception as exc:
            logger.warning("playwright 不可用，视觉评审循环整体停用: %s", exc)
            _playwright_available = False
        finally:
            asyncio_logger.disabled = asyncio_disabled
    return _playwright_available


async def is_available_async() -> bool:
    """异步探测：探测本身放到工作线程执行。

    sync_playwright 不允许运行在 asyncio 事件循环内（会抛
    "Sync API inside the asyncio loop"），而编排器（orchestrator）在 async
    上下文中调用探测，必须经 to_thread 隔离，否则视觉循环会被误判为不可用。
    """
    return await asyncio.to_thread(is_available)


# ── 本地 echarts 资产（评委渲染注入真实图表用，与前端 vendor 同源） ──
_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"
)
_echarts_js_cache: Optional[str] = None


def _load_echarts_js() -> str:
    """读取本地 echarts.min.js（首次读取后缓存）；缺失时图表槽位按空处理。"""
    global _echarts_js_cache
    if _echarts_js_cache is None:
        path = os.path.join(_ASSETS_DIR, "echarts.min.js")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _echarts_js_cache = fh.read()
        except Exception as exc:
            logger.warning("读取评委渲染用 echarts.min.js 失败（图表槽位将渲染为空框）: %s", exc)
            _echarts_js_cache = ""
    return _echarts_js_cache


# ── 浏览器单例管理（sync playwright 跑在工作线程；锁保证串行渲染） ──
_browser_lock = threading.Lock()
_playwright_ctx: Optional[tuple] = None


def _get_browser():
    """惰性启动 headless chromium 单例。"""
    global _playwright_ctx
    with _browser_lock:
        if _playwright_ctx is None:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            _playwright_ctx = (pw, browser)
        return _playwright_ctx[1]


# ── 页内规则取证 JS：对齐/溢出/结构类问题用确定性检查（SheetDesigner 结论） ──
_RULE_JS = """
() => {
  const doc = document.documentElement;
  const overflowBlocks = [];
  document.querySelectorAll('.card, .kpi-row, .wrap > *').forEach((el) => {
    if (el.scrollWidth > el.clientWidth + 2) {
      overflowBlocks.push((el.className || el.tagName).toString().slice(0, 60));
    }
  });
  const zeroHeight = [];
  document.querySelectorAll('[data-sit="chart"], [data-sit="map"]').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.height < 40) {
      zeroHeight.push(el.getAttribute('data-ref') || el.getAttribute('data-sit') || '?');
    }
  });
  return {
    pageOverflow: doc.scrollWidth > doc.clientWidth + 2,
    scrollWidth: doc.scrollWidth,
    clientWidth: doc.clientWidth,
    overflowBlocks: overflowBlocks.slice(0, 8),
    zeroHeight: zeroHeight.slice(0, 8),
    bodyBlocks: document.querySelectorAll('.card, .kpi-row').length,
    hasContent: (document.body.innerText || '').trim().length > 20,
  };
}
"""

# ── 评委页地图要素渲染 JS（离线 SVG，无瓦片无依赖） ──
# 用简单等距圆柱投影把真实 points/routes/circles/areas 画成 SVG——
# 评审只需相对密度与分布形态，不需要精确地理；解决"VLM 看不到地图"的盲区。
_MAP_SVG_JS = """
(mapLayer) => {
  const containers = document.querySelectorAll('[data-sit="map"]');
  if (!containers.length) return { rendered: false, features: 0 };
  const pts = (mapLayer && mapLayer.points) || [];
  const routes = (mapLayer && mapLayer.routes) || [];
  const circles = (mapLayer && mapLayer.circles) || [];
  const areas = (mapLayer && mapLayer.areas) || [];
  const featureCount = pts.length + routes.length + circles.length + areas.length;
  if (!featureCount) {
    containers.forEach((el) => {
      el.style.background = 'linear-gradient(135deg,#dfe9f3 0%,#f6f9fc 100%)';
      el.textContent = '地图区域（无要素）';
    });
    return { rendered: false, features: 0 };
  }
  // 收集全部坐标定 bounds
  const all = [];
  pts.forEach((p) => all.push([+p.lng, +p.lat]));
  routes.forEach((r) => (r.points || []).forEach((p) => all.push([+p.lng, +p.lat])));
  circles.forEach((c) => all.push([+c.lng, +c.lat]));
  areas.forEach((a) => (a.points || []).forEach((p) => all.push([+p.lng, +p.lat])));
  const lngs = all.map((c) => c[0]), lats = all.map((c) => c[1]);
  let minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  let minLat = Math.min(...lats), maxLat = Math.max(...lats);
  // 单点/零跨度时给一个最小视野，避免除零
  if (maxLng - minLng < 0.01) { minLng -= 0.05; maxLng += 0.05; }
  if (maxLat - minLat < 0.01) { minLat -= 0.05; maxLat += 0.05; }
  const padLng = (maxLng - minLng) * 0.08, padLat = (maxLat - minLat) * 0.08;
  minLng -= padLng; maxLng += padLng; minLat -= padLat; maxLat += padLat;
  const esc = (s) => String(s == null ? '' : s).replace(/[<>&"]/g, '');
  let svgParts = '';
  // 面（区域多边形）
  areas.forEach((a) => {
    const ptsAttr = (a.points || []).map((p) => ((+p.lng - minLng) / (maxLng - minLng) * 100).toFixed(2)
      + ',' + ((maxLat - +p.lat) / (maxLat - minLat) * 100).toFixed(2)).join(' ');
    if (ptsAttr) {
      svgParts += '<polygon points="' + ptsAttr + '" fill="#0f766e" fill-opacity="0.10" '
        + 'stroke="#0f766e" stroke-opacity="0.4" stroke-width="0.3" vector-effect="non-scaling-stroke"/>';
    }
  });
  // 范围圈（半径 km → 度 ≈ /111，横向按投影比例换算）
  circles.forEach((c) => {
    const cx = (+c.lng - minLng) / (maxLng - minLng) * 100;
    const cy = (maxLat - +c.lat) / (maxLat - minLat) * 100;
    const r = (+(c.radius_km || c.radiusKm || 50)) / 111 / (maxLng - minLng) * 100;
    svgParts += '<circle cx="' + cx.toFixed(2) + '" cy="' + cy.toFixed(2) + '" r="' + r.toFixed(2)
      + '" fill="#dc2626" fill-opacity="0.06" stroke="#dc2626" stroke-opacity="0.5" stroke-width="0.4"'
      + ' vector-effect="non-scaling-stroke"/>'
      + '<text x="' + cx.toFixed(2) + '" y="' + cy.toFixed(2) + '" font-size="2.2" fill="#dc2626"'
      + ' text-anchor="middle">' + esc(c.name) + '</text>';
  });
  // 航线（折线 + 端点）
  routes.forEach((r) => {
    const ptsAttr = (r.points || []).map((p) => ((+p.lng - minLng) / (maxLng - minLng) * 100).toFixed(2)
      + ',' + ((maxLat - +p.lat) / (maxLat - minLat) * 100).toFixed(2)).join(' ');
    if (ptsAttr) {
      svgParts += '<polyline points="' + ptsAttr + '" fill="none" stroke="#d97706" stroke-opacity="0.75"'
        + ' stroke-width="0.45" vector-effect="non-scaling-stroke"/>';
    }
  });
  // 标点（最后画，压在最上层）
  pts.forEach((p) => {
    const cx = (+p.lng - minLng) / (maxLng - minLng) * 100;
    const cy = (maxLat - +p.lat) / (maxLat - minLat) * 100;
    svgParts += '<circle cx="' + cx.toFixed(2) + '" cy="' + cy.toFixed(2) + '" r="0.5"'
      + ' fill="#2563eb" fill-opacity="0.8"/>';
  });
  containers.forEach((el) => {
    el.style.position = 'relative';
    el.style.background = '#eef3f8';
    el.innerHTML = '<svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet"'
      + ' style="position:absolute;inset:0;width:100%;height:100%">' + svgParts + '</svg>';
  });
  return { rendered: true, features: featureCount };
}
"""


# ── VLM rubric 评审 prompt（八维评分 + 最多 3 项定向诊断，契约化输出） ──
_RUBRIC_SYSTEM = (
    "你是资深的仪表盘/数据可视化排版评审员。对给定页面截图按八个维度打分（0-10 整数）：\n"
    "alignment 对齐与栅格：卡片边缘、列宽、间距是否整齐一致；\n"
    "balance 平衡与密度：各区域占比是否合理，有无过密或大片空白；\n"
    "hierarchy 视觉层次：标题、图表、说明的主次是否清晰；\n"
    "color 配色和谐：配色是否专业克制、对比度是否充分；\n"
    "space 空间利用：留白与紧凑度是否得当；\n"
    "chart_readability 图表可读性：每张图表的标签/图例/轴文字是否清晰、有无明显重叠压盖、"
    "数据量与图表形式是否匹配（如几十类画饼图、几千点画折线都算缺陷）；\n"
    "map_density 地图密度：地图内点线要素分布是否过密、主次是否可辨"
    "（无地图的页面本维度给 8 分，视为不适用而非缺陷）；\n"
    "overall 整体美观：作为态势报告页的综合印象。\n"
    "严格输出 JSON（不要任何解释文字或 markdown 标记）：\n"
    '{"scores":{"alignment":0,"balance":0,"hierarchy":0,"color":0,"space":0,'
    '"chart_readability":0,"map_density":0,"overall":0},'
    '"total":0,"issues":[{"location":"区域位置","element":"元素与CSS属性","fix":"一句话改法"}]}\n'
    "total 为八维平均（保留 1 位小数）。issues 最多 3 项，按严重程度降序，"
    "只列可操作的定向修复建议；页面已良好时 issues 返回空数组。"
)


def _parse_json(text: str) -> Dict[str, Any]:
    """解析 VLM 返回的 JSON（容忍 markdown 代码块包裹）。"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"VLM 评审结果无法解析为 JSON: {text[:200]}")


def _agg_value(rows: List[Dict[str, Any]], column: str, agg: str) -> Any:
    """对证据行做确定性聚合（count/sum/max/min/avg），供评委渲染 KPI。

    count 语义与前端 situation-kit.aggregate 对齐：返回行数（不按列过滤），
    保证评委看到的数值与用户最终看到的完全一致（同口径，防评审误判）。
    """
    try:
        if agg == "count":
            return len(rows)
        values = []
        for r in rows:
            try:
                values.append(float(r.get(column)))
            except (TypeError, ValueError):
                continue
        if not values:
            return "-"
        if agg == "sum":
            return round(sum(values), 2)
        if agg == "max":
            return max(values)
        if agg == "min":
            return min(values)
        if agg == "avg":
            return round(sum(values) / len(values), 2)
        return "-"
    except Exception:
        return "-"


def _kpi_fill_from_html(html: str, store) -> List[Dict[str, Any]]:
    """解析 HTML 中的 kpi 占位符（data-ref + data-metrics），基于证据行计算填充值。

    与前端 situation-kit 的 kpi 语义对齐：评委渲染给 VLM 看到真实数值，
    避免占位空白被误判为布局问题。
    """
    fills: List[Dict[str, Any]] = {}
    for m in re.finditer(r'<div[^>]*data-sit="kpi"[^>]*>', html or ""):
        tag = m.group(0)
        ref_m = re.search(r'data-ref="([^"]+)"', tag)
        if not ref_m:
            continue
        ref = ref_m.group(1)
        metrics_m = re.search(r"data-metrics='([^']*)'|data-metrics=\"([^\"]*)\"", tag)
        raw_metrics = metrics_m.group(1) if metrics_m and metrics_m.group(1) is not None else (
            metrics_m.group(2) if metrics_m else "[]"
        )
        try:
            metrics = json.loads((raw_metrics or "[]").replace("&quot;", '"'))
        except json.JSONDecodeError:
            metrics = []
        if ref in fills:
            continue
        try:
            ev = store.get_evidence(ref)
            rows = list(ev.rows or []) if ev else []
        except Exception:
            rows = []
        parts = []
        for metric in metrics[:4]:
            if not isinstance(metric, dict):
                continue
            label = str(metric.get("label") or metric.get("column") or "")
            value = _agg_value(rows, str(metric.get("column") or ""), str(metric.get("agg") or "count"))
            parts.append(
                f'<div class="sit-kpi"><div class="sit-kpi-label">{label}</div>'
                f"<div class=\"sit-kpi-value\">{value}</div></div>"
            )
        fills[ref] = {"ref": ref, "html": "".join(parts) or "<div class='sit-kpi'><div class='sit-kpi-value'>-</div></div>"}
    return list(fills.values())


def _render_sync(
    html: str,
    option_map: Dict[str, Dict[str, Any]],
    narrative: Optional[Dict[str, Any]],
    kpi_fills: List[Dict[str, Any]],
    map_layer: Optional[Dict[str, Any]] = None,
) -> tuple:
    """同步渲染 + 截图 + 页内规则取证（工作线程内执行）。

    挂载逻辑为 situation-kit 的简化版：charts 用真实 ECharts option 初始化，
    kpi/narrative 填真实文本；地图用离线 SVG 画真实点线要素（等距圆柱投影，
    无瓦片无依赖），让 VLM 能直接看到密度与分布形态。
    """
    timeout_ms = config.SITUATION_JUDGE_TIMEOUT * 1000
    browser = _get_browser()
    with _browser_lock:  # 串行渲染：共享浏览器实例不接受并发页面操作
        page = browser.new_page(
            viewport={"width": config.SITUATION_JUDGE_VIEWPORT_WIDTH, "height": 1000},
        )
        try:
            page.set_content(html, wait_until="load", timeout=timeout_ms)
            echarts_js = _load_echarts_js()
            if echarts_js:
                page.add_script_tag(content=echarts_js)
                page.evaluate(
                    """(optionMap) => {
                      if (typeof echarts === 'undefined') return;
                      for (const [cid, opt] of Object.entries(optionMap)) {
                        document.querySelectorAll(
                          '[data-sit="chart"][data-ref="' + CSS.escape(cid) + '"]'
                        ).forEach((el) => {
                          try {
                            if (el._sitMounted) return;
                            const chart = echarts.init(el);
                            chart.setOption(opt);
                            el._sitMounted = true;
                          } catch (e) { /* 单图失败不影响整页评审 */ }
                        });
                      }
                    }""",
                    option_map,
                )
            page.evaluate(
                """(kpis) => {
                  for (const k of kpis) {
                    document.querySelectorAll(
                      '[data-sit="kpi"][data-ref="' + CSS.escape(k.ref) + '"]'
                    ).forEach((el) => { el.innerHTML = k.html; });
                  }
                }""",
                kpi_fills,
            )
            intro = ((narrative or {}).get("intro") or "").strip()
            page.evaluate(
                """(payload) => {
                  if (payload.intro) {
                    document.querySelectorAll('[data-sit="narrative"]').forEach((el) => {
                      el.textContent = payload.intro;
                    });
                  }
                  for (const [cid, text] of Object.entries(payload.explanations || {})) {
                    document.querySelectorAll(
                      '[data-sit="narrative_chart"][data-ref="' + CSS.escape(cid) + '"]'
                    ).forEach((el) => { el.textContent = text; });
                  }
                  if (payload.mapExplanation) {
                    document.querySelectorAll('[data-sit="map_explanation"]').forEach((el) => {
                      el.textContent = payload.mapExplanation;
                    });
                  }
                }""",
                {
                    "intro": intro,
                    "explanations": {
                        item.get("chartId", ""): str(item.get("text") or "")
                        for item in (narrative or {}).get("explanations") or []
                        if isinstance(item, dict) and item.get("chartId")
                    },
                    "mapExplanation": str(((narrative or {}).get("mapExplanation") or "")).strip(),
                },
            )
            # 地图真实要素渲染：离线 SVG 画 points/routes/circles/areas，
            # 让 VLM 看到真实密度；无地图时退化为中性占位块
            page.evaluate(_MAP_SVG_JS, map_layer or {})
            page.wait_for_timeout(800)  # 等待 ECharts 动画/布局稳定
            rule = page.evaluate(_RULE_JS)
            png = page.screenshot(full_page=True, type="png")
            return png, rule
        finally:
            page.close()


async def evaluate_candidate(
    html: str,
    store,
    charts: List[Dict[str, Any]],
    narrative: Optional[Dict[str, Any]],
    profile_desc: str,
    map_layer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """评审单个候选排版：渲染 → 规则取证 → 规则分 + VLM rubric 分。

    Args:
        map_layer: 地图图层 dict（points/routes/circles/areas），评委页据此
            用离线 SVG 渲染真实要素，供 VLM 评估地图密度

    Returns:
        候选 dict：html / rule / vlm(None=VLM 失败) / total / issues / report / vlm_ok / gate_fail

    Raises:
        RuntimeError: 渲染本身失败（playwright 崩溃、超时等）——调用方决定降级
    """
    option_map = {
        c.get("chartId", ""): c.get("option") or {}
        for c in charts or []
        if c.get("chartId") and isinstance(c.get("option"), dict)
    }
    kpi_fills = _kpi_fill_from_html(html, store)
    png, rule = await asyncio.to_thread(
        _render_sync, html, option_map, narrative, kpi_fills, map_layer,
    )

    # 规则分（0-10）：溢出/空容器/无内容按严重度扣分
    rule_score = 10.0
    gate_fail: List[str] = []
    if not rule.get("hasContent"):
        rule_score -= 4
        gate_fail.append("页面渲染后无实际内容")
    if rule.get("pageOverflow"):
        rule_score -= 2
        gate_fail.append("页面出现横向溢出")
    for _ in (rule.get("overflowBlocks") or [])[:3]:
        rule_score -= 1
    for _ in (rule.get("zeroHeight") or [])[:2]:
        rule_score -= 2
        gate_fail.append(f"占位容器高度为 0: {rule.get('zeroHeight')}")
    rule_score = max(0.0, rule_score)

    candidate: Dict[str, Any] = {
        "html": html,
        "rule": round(rule_score, 1),
        "vlm": None,
        "total": round(rule_score, 1),
        "issues": [],
        "report": rule,
        "vlm_ok": False,
        "gate_fail": gate_fail,
    }

    # VLM rubric 分（视觉反思通道）：失败不致命，退化为纯规则决策
    try:
        png_b64 = base64.b64encode(png).decode("ascii")
        user = (
            f"页面截图见附图。该态势报告页包含：{profile_desc}。\n"
            "页面中的地图区域用简化 SVG 投影渲染了真实点线要素（无地理底图），"
            "请重点评估其密度与可读性，底色缺失不算布局缺陷。\n"
            "请按系统约定输出评审 JSON。"
        )
        raw = await asyncio.to_thread(
            call_llm_vision, _RUBRIC_SYSTEM, user, [png_b64], 0.2, 2000, "disabled",
        )
        data = _parse_json(raw)
        scores = data.get("scores") or {}
        valid = [
            float(v) for v in scores.values()
            if isinstance(v, (int, float)) and 0 <= float(v) <= 10
        ]
        if not valid:
            # 评分全部非法时视为 VLM 评审失败（而非 0 分误杀候选），走退化路径
            raise ValueError(f"VLM 评分无有效数值: {scores}")
        total = float(data.get("total")) if isinstance(data.get("total"), (int, float)) \
            else sum(valid) / len(valid)
        issues = [
            {"location": str(i.get("location") or ""), "element": str(i.get("element") or ""),
             "fix": str(i.get("fix") or "")}
            for i in (data.get("issues") or [])
            if isinstance(i, dict) and str(i.get("fix") or "").strip()
        ][:3]
        vlm_total = round(min(10.0, max(0.0, total)), 1)
        candidate["vlm"] = vlm_total
        candidate["issues"] = issues
        candidate["vlm_ok"] = True
        # 混合总分：规则 0.4 + 视觉 0.6（SheetDesigner：视觉擅长平衡，规则擅长对齐）
        candidate["total"] = round(0.4 * rule_score + 0.6 * vlm_total, 1)
    except Exception as exc:
        logger.warning("VLM 视觉评审失败（退化纯规则决策）: %s", exc)

    return candidate


def pick_winner(skel: Dict[str, Any], cust: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """强制择优（Forced Optimization）：自定义必须严格优于骨架 + margin 才替换。

    评分口径一致性：两候选必须同为 VLM 评分或同为纯规则分才可比；
    口径不一致时退化为骨架优先（现状下限保障）。
    """
    if cust is None:
        return skel
    same_basis = (skel.get("vlm_ok") and cust.get("vlm_ok")) or (
        not skel.get("vlm_ok") and not cust.get("vlm_ok")
    )
    if not same_basis:
        return skel
    if cust["total"] > skel["total"] + config.SITUATION_LAYOUT_MARGIN:
        return cust
    return skel


async def adaptive_layout(
    query: str,
    store,
    charts: List[Dict[str, Any]],
    map_layer: Optional[Dict[str, Any]],
    narrative: Optional[Dict[str, Any]],
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """阶段 5.5 自适应排版管线：主题令牌 → 骨架库 → 视觉评审择优 → 增量修订循环。

    Args:
        semantic: Planner 叙事标签 {"polarity", "focus"}（ABT 语义匹配；None=旁路）

    Returns:
        {"html": 最终 HTML, "meta": 评审元信息}；playwright 不可用等整体性失败
        返回 None（调用方走现有 artifact → 布局树 → 固定三段降级链）。
    """
    # 局部导入避免模块加载顺序问题（writer 不依赖本模块，无循环）
    from agent import layout_skeletons
    from agent import style_tokens
    from agent import writer as writer_mod

    datasets = [
        {
            "datasetId": ev.id,
            "columns": list(ev.columns or []),
            "rowCount": int(ev.meta.get("totalRows", len(ev.rows)) or 0),
        }
        for ev in store.list_evidences()
        if ev.rows
    ]
    profile = layout_skeletons.build_profile(charts, map_layer, narrative, datasets,
                                             query=query, semantic=semantic)
    if not profile["charts"] and not profile["has_map"]:
        return None
    profile_desc = (
        f"{profile['chart_count']} 个图表（{'、'.join(c['title'] for c in profile['charts'][:5])}），"
        f"{'含地图（重要性 %.2f）' % profile['map_importance'] if profile['has_map'] else '无地图'}，"
        f"{'含KPI指标、' if profile['kpi_datasets'] else ''}"
        f"句式意图 {profile.get('question_intent') or 'overview'}，"
        f"态势介绍{'有' if profile['has_intro'] else '无'}"
    )

    # ── ⓪ 主题令牌层（StylistAgent 借鉴）：LLM 生成/预设选取，失败确定性回退 ──
    tokens: Optional[Dict[str, Any]] = None
    if config.SITUATION_STYLE_TOKENS_ENABLED:
        try:
            tokens = await asyncio.to_thread(
                style_tokens.generate_style_tokens, query, profile_desc, semantic,
            )
        except Exception as exc:
            logger.warning("主题令牌生成失败（走默认静态主题）: %s", exc)
    theme_css = tokens["css"] if tokens else ""

    # ── ① 骨架候选：按拟合分（含语义加分）取 Top2 依次渲染评审 ──
    skel_best: Optional[Dict[str, Any]] = None
    skel_id = ""
    try:
        for sk in layout_skeletons.rank_skeletons(profile, semantic, query=query)[:2]:
            html = sk["render"](profile, query, theme_css)
            try:
                cand = await evaluate_candidate(html, store, charts, narrative, profile_desc,
                                                map_layer=map_layer)
            except Exception as exc:
                logger.warning("骨架 %s 渲染/评审失败: %s", sk["id"], exc)
                continue
            cand["skeleton_id"] = sk["id"]
            if cand["gate_fail"]:
                logger.info("骨架 %s 未通过规则 gate: %s", sk["id"], "; ".join(cand["gate_fail"]))
                continue
            if skel_best is None or cand["total"] > skel_best["total"]:
                skel_best = cand
                skel_id = sk["id"]
    except Exception as exc:
        logger.warning("骨架管线整体失败: %s", exc)

    # ── ② 骨架直接达标 → 短路采用（省去 LLM 自定义，省时省 token） ──
    threshold = config.SITUATION_LAYOUT_SCORE_THRESHOLD
    if skel_best is not None and skel_best.get("vlm_ok") and skel_best["total"] >= threshold:
        logger.info(
            "排版管线：骨架 %s 直接达标（%.1f ≥ %.1f），跳过 LLM 自定义",
            skel_id, skel_best["total"], threshold,
        )
        return {
            "html": skel_best["html"],
            "meta": {
                "adopted": "skeleton", "skeleton": skel_id,
                "s_skel": skel_best["total"], "s_cust": None,
                "rounds": 0, "judge": "vlm", "shortcut": True,
                "style": tokens["source"] if tokens else "fallback",
            },
        }

    # ── ③ LLM 自定义候选（骨架不达标或骨架全部 gate 失败时触发） ──
    cust: Optional[Dict[str, Any]] = None
    try:
        custom_html = await writer_mod.write_artifact(
            query, store, charts, map_layer, narrative,
            tokens=(tokens or {}).get("tokens"), semantic=semantic,
        )
        if custom_html:
            cust = await evaluate_candidate(custom_html, store, charts, narrative, profile_desc,
                                            map_layer=map_layer)
            if cust["gate_fail"]:
                logger.info("LLM 自定义未通过规则 gate: %s", "; ".join(cust["gate_fail"]))
                cust = None
    except Exception as exc:
        logger.warning("LLM 自定义排版失败: %s", exc)

    # ── ④ 强制择优：自定义须超过骨架 + margin 才采用；骨架缺失时自定义直接用 ──
    if skel_best is None and cust is None:
        # 两条候选都失败：交回调用方走现有降级链
        return None
    winner = pick_winner(skel_best, cust) if (skel_best and cust) else (skel_best or cust)
    adopted = "custom" if (winner is cust and cust is not None) else "skeleton"

    # ── ⑤ 增量视觉反馈循环：仅对胜者做定向修订，仅严格提升才接受 ──
    rounds_used = 0
    for _ in range(config.SITUATION_VISUAL_LOOP_MAX_ROUNDS):
        if winner["total"] >= threshold:
            break
        if not winner.get("vlm_ok") or not winner.get("issues"):
            break  # 无 VLM 诊断依据不盲改
        try:
            revised_html = await writer_mod.revise_artifact(
                winner["html"], winner["issues"], query, store,
                charts, map_layer, narrative,
            )
        except Exception as exc:
            logger.warning("排版增量修订调用失败: %s", exc)
            break
        if not revised_html or revised_html == winner["html"]:
            break
        try:
            new_cand = await evaluate_candidate(
                revised_html, store, charts, narrative, profile_desc,
                map_layer=map_layer,
            )
        except Exception as exc:
            logger.warning("修订后重评审失败（保留当前最佳）: %s", exc)
            break
        rounds_used += 1
        if new_cand["total"] > winner["total"] + 0.05:
            logger.info(
                "排版增量修订第 %s 轮接受：%.1f → %.1f",
                rounds_used, winner["total"], new_cand["total"],
            )
            if adopted == "skeleton":
                new_cand["skeleton_id"] = winner.get("skeleton_id", skel_id)
            winner = new_cand
        else:
            logger.info(
                "排版增量修订第 %s 轮未提升（%.1f → %.1f），保留当前最佳",
                rounds_used, winner["total"], new_cand["total"],
            )
            break

    meta = {
        "adopted": adopted,
        "skeleton": winner.get("skeleton_id", skel_id),
        "s_skel": skel_best["total"] if skel_best else None,
        "s_cust": cust["total"] if cust else None,
        "rounds": rounds_used,
        "judge": "vlm" if winner.get("vlm_ok") else "rule_only",
        "shortcut": False,
        "style": tokens["source"] if tokens else "fallback",
    }
    logger.info("排版管线完成: %s", meta)
    return {"html": winner["html"], "meta": meta}
