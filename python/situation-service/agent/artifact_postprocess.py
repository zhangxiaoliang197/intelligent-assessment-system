"""HTML Artifact 清洗与校验（纯规则，不调 LLM）。

设计目标（HTML Artifact 沙箱渲染架构 §4）：
- LLM 产出的整页 HTML 可能包含 script / 外链资源 / 非法占位符引用，
  本模块用纯规则做剥离与补齐，保证任何输出都能收敛为安全 HTML；
- 补齐失败（整体为空 / 无有效内容）返回 None，调用方回退布局树管线；
- 本模块只接触引用与占位符属性，不接触任何数据值。

占位符契约：
  <div data-sit="chart" data-ref="chartId"></div>
  <div data-sit="map"></div>
  <div data-sit="kpi" data-ref="datasetId" data-metrics='[{"label","column","agg"}]'></div>
  <div data-sit="narrative" data-part="intro"></div>
  <div data-sit="narrative_chart" data-ref="chartId"></div>
  <div data-sit="map_explanation"></div>
"""
import html as _html
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("situation-service")

_ALLOWED_AGGS = {"sum", "count", "max", "min", "avg"}
_MAX_METRIC_ITEMS = 6
_SIT_KINDS = {"chart", "map", "kpi", "narrative", "narrative_chart", "map_explanation"}


def strip_code_fence(raw: str) -> str:
    """剥离 markdown 代码栅栏（```html ... ```），返回纯 HTML 文本。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*[ \t]*\r?\n?", "", text)
        text = re.sub(r"\r?\n?[ \t]*```\s*$", "", text)
    return text.strip()


# ── 清洗：剥离脚本 / 事件属性 / 外链资源 ──
_RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>|<script\b[^>]*/>", re.I | re.S)
_RE_EVENT_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_RE_EXTERNAL_ATTR = re.compile(
    r"""\s(src|href|poster|data)\s*=\s*(["'])\s*(?:https?:)?//[^"']*\2""", re.I)
_RE_DANGEROUS_TAGS = re.compile(
    r"<(meta|link|base|iframe|object|embed|frame)\b[^>]*>", re.I)


def _sanitize_html(raw_html: str) -> str:
    """剥离脚本、事件属性、外链资源与可覆盖 CSP 的标签（meta/link/base/iframe）。"""
    text = raw_html or ""
    text = _RE_SCRIPT.sub("", text)
    text = _RE_DANGEROUS_TAGS.sub("", text)
    text = _RE_EVENT_ATTR.sub("", text)
    text = _RE_EXTERNAL_ATTR.sub("", text)
    return text


# ── 占位符属性级处理 ──
# data-sit 属性所在元素（开标签整体），捕获 tag / 属性串 / kind
_RE_SIT_TAG = re.compile(
    r"<([a-zA-Z]\w*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?\bdata-sit=[\"'](?P<kind>[a-z_]+)[\"'](?:[^>\"']|\"[^\"]*\"|'[^']*')*)>",
    re.I)


def _get_attr(attrs: str, name: str) -> Optional[str]:
    """从开标签属性串中取属性值（已做 HTML 实体反转义）。

    属性值可能包含另一种引号（如 data-metrics='[{"a":1}]'），
    因此双引号值与单引号值分开匹配。
    """
    m = re.search(
        rf"\b{name}\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)')", attrs, re.I)
    if not m:
        return None
    val = m.group("double") if m.group("double") is not None else m.group("single")
    return _html.unescape(val).strip() if val is not None else None


def _remove_attr(attrs: str, name: str) -> str:
    """从开标签属性串中删除指定属性（用于使非法占位符失效）。"""
    return re.sub(rf"\s*\b{name}\s*=\s*(\"[^\"]*\"|'[^']*')", "", attrs, flags=re.I)


def _replace_attr(attrs: str, name: str, value: str) -> str:
    """替换或追加属性（值做 HTML 属性转义）。"""
    escaped = _html.escape(value, quote=True)
    if re.search(rf"\b{name}\s*=", attrs, re.I):
        return re.sub(rf"\b{name}\s*=\s*(\"[^\"]*\"|'[^']*')",
                      f'{name}="{escaped}"', attrs, flags=re.I)
    return f'{attrs} {name}="{escaped}"'


def _sanitize_metrics(raw_json: str, columns: Set[str]) -> List[Dict[str, str]]:
    """清洗 kpi 指标项：agg/列名白名单过滤（与布局树 metrics 同口径）。"""
    try:
        items = json.loads(raw_json) if raw_json else []
    except (TypeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    cleaned: List[Dict[str, str]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        column = str(raw.get("column") or "").strip()
        agg = str(raw.get("agg") or "").strip().lower()
        if agg not in _ALLOWED_AGGS:
            continue
        # count 只需数据集存在；其余聚合必须命中真实列名
        if agg != "count" and column not in columns:
            continue
        label = str(raw.get("label") or "").strip() or (f"{agg}({column})" if column else agg)
        cleaned.append({"label": label, "column": column, "agg": agg})
        if len(cleaned) >= _MAX_METRIC_ITEMS:
            break
    return cleaned


def sanitize_artifact(
    raw_html: str,
    charts: List[Dict[str, Any]],
    map_layer: Optional[Dict[str, Any]],
    dataset_columns: Optional[Dict[str, Set[str]]] = None,
) -> Optional[Dict[str, Any]]:
    """清洗并校验 LLM 产出的 HTML Artifact。

    Args:
        raw_html: LLM 原始输出（可能带 markdown 栅栏）
        charts: 最终产出图表列表（含 chartId）
        map_layer: 最终产出地图图层（可为 None）
        dataset_columns: datasetId → 列名集合（kpi 指标列白名单）

    Returns:
        {"html": 清洗后的 HTML, "issues": [需 Reflection 修复的问题描述]}；
        整体为空返回 None（调用方回退布局树）。
    """
    dataset_columns = dataset_columns or {}
    dataset_ids = set(dataset_columns.keys())
    text = _sanitize_html(strip_code_fence(raw_html))
    if not text.strip():
        return None

    chart_ids = {str(c.get("chartId") or "") for c in charts if c.get("chartId")}
    has_map = bool(map_layer)
    issues: List[str] = []
    map_seen = False
    referenced_charts: Set[str] = set()

    # 逐个开标签处理占位符（属性级改写，不改动元素结构）
    def _process(match: "re.Match") -> str:
        nonlocal map_seen
        tag, attrs, kind = match.group(1), match.group(2), match.group("kind")
        if kind not in _SIT_KINDS:
            # 未知 kind：使占位符失效（保留元素作普通容器）
            return f"<{tag}{_remove_attr(_remove_attr(attrs, 'data-sit'), 'data-ref')}>"
        if kind == "chart":
            ref = _get_attr(attrs, "data-ref") or ""
            if ref in chart_ids:
                referenced_charts.add(ref)
                return f"<{tag}{attrs}>"
            # 非法引用：失效并记录（由补齐逻辑兜底，不必整体重写）
            if ref:
                issues.append(f"chart 占位符引用了不存在的 chartId：{ref}")
            return f"<{tag}{_remove_attr(_remove_attr(attrs, 'data-sit'), 'data-ref')}>"
        if kind == "map":
            if not has_map:
                issues.append("页面包含 map 占位符，但本次无地图产物")
                return f"<{tag}{_remove_attr(attrs, 'data-sit')}>"
            if map_seen:
                # 地图块最多一个：多余占位符失效
                return f"<{tag}{_remove_attr(attrs, 'data-sit')}>"
            map_seen = True
            return f"<{tag}{attrs}>"
        if kind == "kpi":
            ref = _get_attr(attrs, "data-ref") or ""
            if ref not in dataset_ids:
                if ref:
                    issues.append(f"kpi 占位符引用了不存在的 datasetId：{ref}")
                return f"<{tag}{_remove_attr(_remove_attr(_remove_attr(attrs, 'data-sit'), 'data-ref'), 'data-metrics')}>"
            cleaned = _sanitize_metrics(_get_attr(attrs, "data-metrics") or "",
                                        set(dataset_columns.get(ref) or set()))
            if not cleaned:
                return f"<{tag}{_remove_attr(_remove_attr(_remove_attr(attrs, 'data-sit'), 'data-ref'), 'data-metrics')}>"
            attrs = _replace_attr(_remove_attr(attrs, "data-metrics"),
                                  "data-metrics", json.dumps(cleaned, ensure_ascii=False))
            return f"<{tag}{attrs}>"
        if kind == "narrative_chart":
            ref = _get_attr(attrs, "data-ref") or ""
            if ref in chart_ids:
                return f"<{tag}{attrs}>"
            if ref:
                issues.append(f"narrative_chart 占位符引用了不存在的 chartId：{ref}")
            return f"<{tag}{_remove_attr(_remove_attr(attrs, 'data-sit'), 'data-ref')}>"
        # narrative / map_explanation：无需 ref 校验
        return f"<{tag}{attrs}>"

    text = _RE_SIT_TAG.sub(_process, text)

    # ── 完整性补齐：未被引用的产物自动追加占位块 ──
    missing = [cid for cid in chart_ids if cid not in referenced_charts]
    if missing:
        issues.append(f"以下图表未被任何 chart 占位符引用，已自动补齐：{'、'.join(missing)}")
    append_parts: List[str] = []
    for cid in missing:
        append_parts.append(
            f'<section class="sit-append"><h3 class="sit-append-title">图表 {cid}</h3>'
            f'<div data-sit="chart" data-ref="{_html.escape(cid, quote=True)}"></div></section>')
    if has_map and not map_seen:
        issues.append("存在地图产物但页面缺少 map 占位符，已自动补齐全宽地图块")
        append_parts.append(
            '<section class="sit-append sit-append-map"><h3 class="sit-append-title">地理分布</h3>'
            '<div data-sit="map"></div></section>')

    if append_parts:
        block = ('<style>.sit-append{margin:16px 0;padding:16px;border:1px solid #e5e7eb;'
                 'border-radius:12px;background:#fff}.sit-append-map>div{height:480px}'
                 '.sit-append>div[data-sit="chart"]{height:360px}</style>')
        injected = block + "".join(append_parts)
        close_m = re.search(r"</body\s*>", text, re.I)
        if close_m:
            text = text[:close_m.start()] + injected + text[close_m.start():]
        else:
            text = text + injected

    # 无任何产物引用且页面近乎无正文 → 视为整体失败
    if not referenced_charts and not map_seen and len(re.sub(r"<[^>]+>", "", text).strip()) < 10:
        return None

    return {"html": text, "issues": issues}


__all__ = ["sanitize_artifact", "strip_code_fence"]
