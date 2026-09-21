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
from typing import Any, Dict, List, Optional, Set, Tuple

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

    # ── 栅格回收：槽位失效后移除空壳卡片并重算 span，杜绝"地图 span8 + 右侧空白 4 列" ──
    text, grid_notes = _recover_grid_layout(text, len(referenced_charts), map_seen)
    issues.extend(grid_notes)

    # 无任何产物引用且页面近乎无正文 → 视为整体失败
    if not referenced_charts and not map_seen and len(re.sub(r"<[^>]+>", "", text).strip()) < 10:
        return None

    return {
        "html": text,
        "issues": issues,
        "validChartSlots": len(referenced_charts),
        "hasMapSlot": map_seen,
    }


# ── 栅格回收（纯规则标签扫描，支持嵌套 grid） ─────────────────────────────
# 排版契约：<div class="grid"> 为 12 列栅格容器，直接子级 <div class="card"
# style="grid-column:span N"> 为卡片；右侧 4/3 列容器可能是嵌套 <div class="grid">。
# 槽位失效（非法 chart/kpi 引用被剥离 data-sit）后，包裹它的卡片只剩标题空壳，
# 旧逻辑把空壳留在栅格中占位，形成右侧大块空白。回收策略：
#   1. 删除无有效槽位且近乎无正文的空壳卡片（含空的嵌套 grid 容器）；
#   2. 发生删除的 grid，剩余卡片按数量确定性均分 12 列；
#   3. 全页 0 图表时，含地图的卡片强制 span 12（地图独占整行）。
_RE_DIV_OPEN = re.compile(
    r"<div\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.I)
_RE_DIV_TOKEN = re.compile(r"<div\b|</div\s*>", re.I)
_RE_STYLE_ATTR = re.compile(r"\bstyle\s*=\s*(\"([^\"]*)\"|'([^']*)')", re.I)
_RE_GRID_COLUMN = re.compile(r"grid-column\s*:\s*span\s*\d+", re.I)
_RE_GRID_COLUMN_GET = re.compile(r"grid-column\s*:\s*span\s*(\d+)", re.I)
_RE_SPAN_12 = re.compile(r"grid-column\s*:\s*span\s*12\b", re.I)
# 内联单列模板：LLM 常用 grid-template-columns:1fr 把嵌套 grid 锁成竖排，
# 展开窄列时需剥离，使其回落到 .grid 类的 12 列轨道
_RE_GRID_TEMPLATE_COLS = re.compile(r"\s*grid-template-columns\s*:[^;\"']*;?", re.I)
_RE_CHART_SLOT = re.compile(r"\bdata-sit\s*=\s*[\"']chart[\"']", re.I)
# 窄图表列判定阈值：嵌套容器占宽 ≤ 该列数 且内部 ≥ 该数量图表槽
_CRAMPED_COL_SPAN_MAX = 5
_CRAMPED_CHART_MIN = 2
# 空壳判定时视为"实质内容"的槽位：可视化槽（chart/map/kpi）与必注入的叙事槽；
# map_explanation 不列入——无地图产物时 map 槽已失效，仅剩该文本槽的卡片必须能被判壳回收
_SLOT_ATTR_SUBSTANTIAL = re.compile(
    r"\bdata-sit\s*=\s*[\"'](?:chart|map|kpi|narrative|narrative_chart)[\"']", re.I)
_RE_MAP_SLOT = re.compile(r"\bdata-sit\s*=\s*[\"']map[\"']", re.I)
_RE_RICH_INNER = re.compile(r"<(table|svg|canvas|ul|ol|img|iframe)\b", re.I)
# 栅格回收处理完成标记（仅回收过程使用，输出前统一清除）
_GRID_DONE_ATTR = 'data-sit-griddone=""'


def _classes_of(attrs: str) -> Set[str]:
    """取 div 属性串中的 class 词集合。"""
    m = re.search(r"\bclass\s*=\s*(\"([^\"]*)\"|'([^']*)')", attrs, re.I)
    if not m:
        return set()
    raw = m.group(2) if m.group(2) is not None else m.group(3)
    return set((raw or "").split())


def _balanced_spans(count: int) -> List[int]:
    """按有效卡片数量均分 12 列（两行内布完，避免窄卡）。"""
    table = {1: [12], 2: [6, 6], 3: [4, 4, 4], 4: [6, 6, 6, 6], 5: [4, 4, 4, 4, 4], 6: [4, 4, 4, 4, 4, 4]}
    if count in table:
        return table[count]
    return [3] * count


def _set_card_span(attrs: str, span: int) -> str:
    """重写/追加卡片开标签 style 中的 grid-column:span N。"""
    style_m = _RE_STYLE_ATTR.search(attrs)
    if not style_m:
        return f'{attrs} style="grid-column:span {span}"'
    quote = '"' if style_m.group(2) is not None else "'"
    style_val = style_m.group(2) if style_m.group(2) is not None else style_m.group(3)
    if _RE_GRID_COLUMN.search(style_val):
        new_style = _RE_GRID_COLUMN.sub(f"grid-column:span {span}", style_val)
    else:
        new_style = (style_val.rstrip(";") + f";grid-column:span {span}") if style_val.strip() else f"grid-column:span {span}"
    new_attr = f'style={quote}{new_style}{quote}'
    return attrs[:style_m.start()] + new_attr + attrs[style_m.end():]


def _get_col_span(attrs: str) -> int:
    """取开标签 style 中 grid-column:span N；未声明按占满 12 列处理。"""
    style_m = _RE_STYLE_ATTR.search(attrs)
    scope = (style_m.group(2) if style_m.group(2) is not None else style_m.group(3)) if style_m else attrs
    m = _RE_GRID_COLUMN_GET.search(scope or "")
    return int(m.group(1)) if m else 12


def _strip_inline_columns(attrs: str) -> str:
    """剥离 style 中的 grid-template-columns 声明（无 style 则原样返回）。"""
    style_m = _RE_STYLE_ATTR.search(attrs)
    if not style_m:
        return attrs
    quote = '"' if style_m.group(2) is not None else "'"
    style_val = style_m.group(2) if style_m.group(2) is not None else style_m.group(3)
    new_val = _RE_GRID_TEMPLATE_COLS.sub("", style_val).strip().strip(";").strip()
    if new_val == style_val.strip():
        return attrs
    new_attr = f'style={quote}{new_val}{quote}' if new_val else ""
    # style 属性被清空时连同属性一起删除（含其前导空格）
    start = style_m.start() - (1 if style_m.start() > 0 and attrs[style_m.start() - 1] == " " else 0)
    return attrs[:start] + (" " + new_attr if new_attr else "") + attrs[style_m.end():]


def _iter_div_elements(text: str, start: int, end: int) -> List[Dict[str, Any]]:
    """枚举区间内已闭合的 div 元素，depth 为开标签时的嵌套深度（根=0）。"""
    elements: List[Dict[str, Any]] = []
    open_stack: List[Dict[str, Any]] = []
    for m in _RE_DIV_TOKEN.finditer(text, start, end):
        if m.group(0).lower().startswith("</div"):
            if open_stack:
                op = open_stack.pop()
                elements.append({**op, "close_start": m.start(), "end": m.end()})
        else:
            full = _RE_DIV_OPEN.match(text, m.start(), end)
            if full:
                attrs = full.group(1)
                open_stack.append({
                    "start": full.start(), "open_end": full.end(),
                    "attrs": attrs, "classes": _classes_of(attrs),
                    "depth": len(open_stack),
                })
    return elements


def _card_is_shell(segment: str) -> bool:
    """判定卡片片段是否为空壳：无实质槽位/富内容元素且正文很短。

    注意：无地图产物时 map 槽仅被剥离 data-sit（留下固定高度空 div），同卡的
    map_explanation 属可选文本槽，二者均不得阻止空壳回收，否则会留下数百像素空白块。
    """
    if _SLOT_ATTR_SUBSTANTIAL.search(segment) or _RE_RICH_INNER.search(segment):
        return False
    plain = _html.unescape(re.sub(r"<[^>]+>", "", segment)).strip()
    return len(plain) < 20


def _find_cramped_column(frag: str, items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """在直接子级中定位"拥挤图表列"：占宽 ≤5 列的嵌套 grid 且内含 ≥2 个图表槽。

    LLM 常见排版是"地图 span8 + 嵌套 grid span4 内竖排 4 张图"，30 点趋势折线在
    约 1/3 屏宽内 x 轴标签互相压盖、首末点贴边（用户反馈"折线截断、前面没显示"）。
    kpi/纯文本窄卡可容纳，不纳入；仅多图窄列触发整行展开。
    """
    for e in items:
        if "grid" not in e["classes"]:
            continue
        if _get_col_span(e["attrs"]) > _CRAMPED_COL_SPAN_MAX:
            continue
        if len(_RE_CHART_SLOT.findall(frag[e["start"]:e["end"]])) >= _CRAMPED_CHART_MIN:
            return e
    return None


def _expand_cramped_column(
    new_frag: str, kept: List[Dict[str, Any]], target: Dict[str, Any], notes: List[str]
) -> str:
    """展开拥挤图表列（所有开标签替换收集后按位置倒序执行）。

    - 嵌套列剥离内联单列模板并占满整行（回落 .grid 的 12 列轨道）；
    - 嵌套列内部卡片按数量两列均布（4 张→6/6/6/6）；
    - 同层其他卡片（含地图卡）全部 span12，与展开后的图列上下分排。
    """
    replacements: List[Tuple[int, int, str]] = []
    col_frag = new_frag[target["start"]:target["end"]]
    inner_cards = [
        e for e in _iter_div_elements(col_frag, 0, len(col_frag))[1:]
        if e["depth"] == 1 and "card" in e["classes"]
    ]
    for e, sp in zip(inner_cards, _balanced_spans(len(inner_cards))):
        replacements.append((
            target["start"] + e["start"], target["start"] + e["open_end"],
            f"<div{_set_card_span(e['attrs'], sp)}>",
        ))
    target_attrs = _set_card_span(_strip_inline_columns(target["attrs"]), 12)
    replacements.append((target["start"], target["open_end"], f"<div{target_attrs}>"))
    for e in kept:
        if e is target:
            continue
        replacements.append((e["start"], e["open_end"], f"<div{_set_card_span(e['attrs'], 12)}>"))
    for start, open_end, text in sorted(replacements, key=lambda x: x[0], reverse=True):
        new_frag = new_frag[:start] + text + new_frag[open_end:]
    notes.append("栅格回收：多张图表被挤在窄列中，已展开为整行网格（图表两列均布、地图占满整行）")
    return new_frag


def _rebuild_one_grid(frag: str, force_map_full: bool) -> Tuple[str, bool, List[str]]:
    """重建一个（最内层）grid 元素：删空壳卡片、窄图表列展开、重算 span。

    Returns:
        (新片段, 是否发生修改, 修复说明)
    """
    elements = _iter_div_elements(frag, 0, len(frag))
    if not elements:
        return frag, False, []
    notes: List[str] = []
    direct = [
        e for e in elements[1:]
        if e["depth"] == 1 and ({"card", "grid"} & e["classes"])
    ]
    shells = [e for e in direct if _card_is_shell(frag[e["start"]:e["end"]])]

    # 判断 0 图表时地图卡是否已经是全宽（幂等关键：已全宽则不再修改）
    def _is_map_card(e: Dict[str, Any]) -> bool:
        return bool(_RE_MAP_SLOT.search(frag[e["start"]:e["end"]]))

    map_need_adjust = False
    if force_map_full:
        for e in direct:
            if _is_map_card(e) and not _RE_SPAN_12.search(e["attrs"]):
                map_need_adjust = True
                break

    # 窄图表列检测：无任何修改动作时直接早退（幂等）
    cramped_initial = _find_cramped_column(frag, direct)
    if not shells and not map_need_adjust and cramped_initial is None:
        return frag, False, []

    new_frag = frag
    if shells:
        notes.append("栅格回收：已移除 %d 个无内容的空卡片壳，剩余卡片重新均分列宽" % len(shells))
        for e in sorted(shells, key=lambda x: x["start"], reverse=True):
            new_frag = new_frag[:e["start"]] + new_frag[e["end"]:]

    # 删除后重新扫描直接卡片（坐标基于新片段）
    kept = [
        e for e in _iter_div_elements(new_frag, 0, len(new_frag))[1:]
        if e["depth"] == 1 and ({"card", "grid"} & e["classes"])
    ]
    if not kept:
        return new_frag, True, notes

    # 窄图表列优先展开（独立于 force_map_full：有图表场景同样成立）
    cramped = _find_cramped_column(new_frag, kept)
    if cramped is not None:
        new_frag = _expand_cramped_column(new_frag, kept, cramped, notes)
        return new_frag, True, notes

    if force_map_full:
        map_els = [e for e in kept if _RE_MAP_SLOT.search(new_frag[e["start"]:e["end"]])]
        other_els = [e for e in kept if e not in map_els]
        other_spans = _balanced_spans(len(other_els)) if other_els else []
        span_map: Dict[int, int] = {id(e): 12 for e in map_els}
        for e, sp in zip(other_els, other_spans):
            span_map[id(e)] = sp
        ordered = kept
        spans = [span_map[id(e)] for e in ordered]
        if map_els:
            notes.append("栅格回收：本次无图表产物，地图已调整为整行全宽展示")
    else:
        ordered = kept
        spans = _balanced_spans(len(kept))

    for e, sp in sorted(zip(ordered, spans), key=lambda pair: pair[0]["start"], reverse=True):
        new_open = f"<div{_set_card_span(e['attrs'], sp)}>"
        new_frag = new_frag[:e["start"]] + new_open + new_frag[e["open_end"]:]
    return new_frag, True, notes


def _recover_grid_layout(text: str, chart_slot_count: int, has_map_slot: bool) -> Tuple[str, List[str]]:
    """自底向上扫描全部 grid 容器执行栅格回收（带完成标记，单遍必然收敛）。"""
    force_map_full = chart_slot_count == 0 and has_map_slot
    all_notes: List[str] = []
    map_note_emitted = False

    while True:
        # 未处理（无完成标记）的 grid
        grids = [
            g for g in _iter_div_elements(text, 0, len(text))
            if "grid" in g["classes"] and "data-sit-griddone" not in g["attrs"]
        ]
        if not grids:
            break
        # 最内层：内部区间不含其他未处理 grid 开标签
        innermost = [
            g for g in grids
            if not any(o is not g and g["open_end"] <= o["start"] < g["close_start"] for o in grids)
        ]
        # 最内层 grid 互不嵌套、区间不相交，从后往前替换不影响靠前坐标
        for g in sorted(innermost, key=lambda x: x["start"], reverse=True):
            frag = text[g["start"]:g["end"]]
            new_frag, _, notes = _rebuild_one_grid(frag, force_map_full)
            for note in notes:
                # 地图全宽说明全页最多一条
                if "地图已调整" in note:
                    if not map_note_emitted:
                        all_notes.append(note)
                        map_note_emitted = True
                else:
                    all_notes.append(note)
            # 无论是否修改都打完成标记：使父级 grid 下一轮能够成为最内层
            new_frag = new_frag[:4] + " " + _GRID_DONE_ATTR + new_frag[4:]
            text = text[:g["start"]] + new_frag + text[g["end"]:]

    # 清除回收过程标记
    text = text.replace(" " + _GRID_DONE_ATTR, "")
    return text, all_notes


__all__ = ["sanitize_artifact", "strip_code_fence"]
