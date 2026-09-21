"""版式骨架库 —— 5 个预定义合理版式（态势图-版式骨架与视觉反馈循环方案 §四）。

设计原则（契约先行）：
- 骨架是确定性 HTML 模板：与 LLM Artifact 完全相同的 data-sit 占位符契约，
  前端 ArtifactSandbox/situation-kit 无需任何改动即可挂载；
- 设计质量下限由 CSS 变量 tokens 收敛（间距/圆角/主色/字号），模板只组合不发明；
- fit(profile) 用硬规则选型，render() 填充产物槽位，全程无 LLM 参与——
  即使 LLM 不可用（余额不足/网络故障），骨架排版仍可正常产出。

占位符契约（与 prompts.build_artifact_messages 一致）：
- 图表：<div data-sit="chart" data-ref="图表ID" style="height:..px"></div>（容器必须有确定高度）
- 地图：<div data-sit="map" style="height:..px"></div>（最多一个，仅在有地图产物时出现）
- 指标卡：<div data-sit="kpi" data-ref="数据集ID" data-metrics='[{"label":"..","column":"..","agg":"count"}]'></div>
- 文本：narrative / narrative_chart / map_explanation（仅在有对应文本产物时出现）
"""
import html as _html
import json as _json
from typing import Any, Dict, List, Optional, Tuple

# ── 设计 tokens：全部版式共享的设计系统（CSS 变量），保证美观下限一致 ──
# --sit-maxw 由 _tokens_css() 在渲染时从 config 读取（默认 none=全宽铺开，
# 态势图按大屏页处理；可用 SITUATION_LAYOUT_MAX_WIDTH=1400px 回到限宽居中）
def _tokens_css() -> str:
    import config as _config
    maxw = str(getattr(_config, "SITUATION_LAYOUT_MAX_WIDTH", "none") or "none")
    return (
        ":root{--sit-bg:#f5f7fa;--sit-card:#ffffff;--sit-primary:#2563eb;"
        "--sit-text:#1f2d3d;--sit-muted:#606266;--sit-line:#ebeef5;"
        "--sit-gap:16px;--sit-radius:12px;--sit-pad:16px;--sit-maxw:" + maxw + ";"
        "--sit-shadow:0 1px 4px rgba(0,0,0,.06)}"
    )

# 骨架共用基础样式（页头/卡片/KPI 行），各骨架仅追加自己的布局样式
# max-width:none 时 .wrap 全宽铺开；有限值时自动居中
_BASE_CSS = (
    "*{box-sizing:border-box}body{margin:0;padding:24px;background:var(--sit-bg);"
    "font-family:'Microsoft YaHei','PingFang SC',sans-serif;color:var(--sit-text)}"
    ".wrap{max-width:var(--sit-maxw);margin:0 auto}"
    ".page-title{font-size:20px;font-weight:700;margin:0 0 16px;color:var(--sit-text)}"
    ".grid{display:grid;grid-template-columns:repeat(12,1fr);gap:var(--sit-gap)}"
    ".card{background:var(--sit-card);border-radius:var(--sit-radius);padding:var(--sit-pad);"
    "box-shadow:var(--sit-shadow);min-width:0}"
    ".card h3{margin:0 0 12px;font-size:15px;color:var(--sit-text)}"
    ".kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));"
    "gap:var(--sit-gap);margin-bottom:var(--sit-gap)}"
    ".sit-explain-slot{margin-top:8px}"
    ".intro-card{line-height:1.8;color:var(--sit-muted)}"
)


def _esc(text: Any) -> str:
    """HTML 转义，防注入。"""
    return _html.escape(str(text if text is not None else ""), quote=True)


# ── 画像扩展因子的识别词表（多因素骨架选型 §三.③）──
# 空间/地理意图词：命中说明地图是任务核心（提升 map_importance）
_QUERY_GEO_WORDS = ("轨迹", "航线", "航迹", "巡航", "部署", "分布", "区域", "位置", "航线", "活动范围")
# 对比意图词：适合多图并排对照（S3）
_QUERY_COMPARE_WORDS = ("对比", "比较", "vs", "VS", "versus", "与.*相比")
# 演化/趋势意图词：适合纵向叙事（S4）
_QUERY_TREND_WORDS = ("变化", "趋势", "演化", "走势", "近一", "近几", "上周", "本周", "月度")
# 预警意图词：适合 KPI 置顶仪表盘（S1）
_QUERY_ALERT_WORDS = ("预警", "异常", "超限", "告警", "风险", "威胁")


def _hit_words(text: str, words) -> bool:
    lowered = str(text or "").lower()
    return any(w.lower() in lowered for w in words)


def _estimate_map_importance(
    map_layer: Optional[Dict[str, Any]],
    feature_count: int,
    query: str,
    semantic: Optional[Dict[str, Any]],
) -> float:
    """地图重要性评分 0-1（连续值替代原 has_map 布尔）。

    构成：有图基础分 + 要素规模分 + query 空间意图 + 叙事焦点空间词。
    "有地图"不等于"地图是主角"——出动架次统计里地图是配图（≈0.4），
    巡航轨迹里地图是核心（≈0.9）。
    """
    if feature_count < 1:
        return 0.0
    score = 0.4
    if feature_count >= 50:
        score += 0.2
    elif feature_count >= 10:
        score += 0.1
    if _hit_words(query, _QUERY_GEO_WORDS):
        score += 0.3
    focus = str((semantic or {}).get("focus") or "")
    if _hit_words(focus, _GEO_FOCUS_WORDS):
        score += 0.1
    return round(min(1.0, score), 2)


def _classify_intent(query: str, semantic: Optional[Dict[str, Any]]) -> str:
    """问题句式意图分类：compare / trend / alert / overview。

    优先级：semantic.polarity（LLM 判定）> query 关键词规则；overview 为默认。
    """
    polarity = str((semantic or {}).get("polarity") or "").strip().lower()
    if polarity in ("compare", "alert"):
        return polarity
    if polarity == "therefore":
        return "conclusion"
    if _hit_words(query, _QUERY_ALERT_WORDS):
        return "alert"
    if _hit_words(query, _QUERY_COMPARE_WORDS):
        return "compare"
    if _hit_words(query, _QUERY_TREND_WORDS):
        return "trend"
    return "overview"


def build_profile(
    charts: List[Dict[str, Any]],
    map_layer: Optional[Dict[str, Any]],
    narrative: Optional[Dict[str, Any]],
    datasets: List[Dict[str, Any]],
    query: str = "",
    semantic: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建产物画像：骨架选型与渲染共用的确定性输入。

    Args:
        charts: 已产出图表列表（含 chartId/title/type）
        map_layer: 地图图层 dict（可为 None）
        narrative: 文本产物 {"intro", "explanations": [{chartId, text}], "mapExplanation"}
        datasets: 数据集元信息 [{datasetId, columns, rowCount}]（供 kpi 占位）
        query: 用户原始问题（供地图重要性与句式意图识别）
        semantic: Planner 叙事标签 {"polarity", "focus"}（可为 None）

    Returns:
        画像 dict：charts/chart_count/has_map/map_importance/chart_type_mix/
        question_intent/data_volume/has_intro/explanations/has_map_explanation/kpi_datasets
    """
    feature_count = 0
    density = ""
    if isinstance(map_layer, dict):
        feature_count = sum(
            len(map_layer.get(key) or []) for key in ("points", "routes", "areas", "circles")
        )
        density = str(map_layer.get("density") or "")
    explanations = {
        item.get("chartId")
        for item in (narrative or {}).get("explanations") or []
        if isinstance(item, dict) and item.get("chartId")
    }
    # kpi 最多取 3 个数据集，且必须有列名（data-metrics 需要具体列做 count）
    kpi_datasets = [
        {"datasetId": d.get("datasetId", ""), "columns": list(d.get("columns") or [])}
        for d in (datasets or [])[:3]
        if d.get("datasetId") and (d.get("columns") or [])
    ]
    chart_list = [
        {"chartId": c.get("chartId", ""), "title": c.get("title", ""), "type": c.get("type", "")}
        for c in charts or []
        if c.get("chartId")
    ]
    # 图表类型构成：趋势型(line)多 → 叙事；占比型(pie)多 → 并列对照
    chart_type_mix: Dict[str, int] = {}
    for c in chart_list:
        ctype = str(c.get("type") or "bar").lower()
        chart_type_mix[ctype] = chart_type_mix.get(ctype, 0) + 1
    # 数据体量分档（证据总行数）：大 → 地图承载更合适
    total_rows = sum(int(d.get("rowCount") or 0) for d in (datasets or []))
    data_volume = "large" if total_rows >= 5000 else ("medium" if total_rows >= 500 else "small")
    return {
        "charts": chart_list,
        "chart_count": len(chart_list),
        "has_map": feature_count >= 1,
        "map_importance": _estimate_map_importance(map_layer, feature_count, query, semantic),
        "map_density": density,
        "chart_type_mix": chart_type_mix,
        "question_intent": _classify_intent(query, semantic),
        "data_volume": data_volume,
        "has_intro": bool(((narrative or {}).get("intro") or "").strip()),
        "explanations": explanations,
        "has_map_explanation": bool(((narrative or {}).get("mapExplanation") or "").strip()),
        "kpi_datasets": kpi_datasets,
    }


# ── 槽位渲染助手（全部骨架共享） ──

def _chart_card(chart: Dict[str, Any], profile: Dict[str, Any],
                span: int = 6, height: int = 320) -> str:
    """单图表卡片：标题 + chart 占位符 +（可选）就近逐图说明。"""
    cid = chart.get("chartId", "")
    title = chart.get("title") or "图表"
    explain = ""
    if cid in profile.get("explanations", set()):
        explain = f'<div class="sit-explain-slot" data-sit="narrative_chart" data-ref="{_esc(cid)}"></div>'
    return (
        f'<div class="card" style="grid-column:span {span}">'
        f'<h3>{_esc(title)}</h3>'
        f'<div data-sit="chart" data-ref="{_esc(cid)}" style="height:{height}px"></div>'
        f"{explain}</div>"
    )


def _map_card(profile: Dict[str, Any], span: int = 12, height: int = 480) -> str:
    """地图卡片：仅在有地图产物时输出（占位符契约：map 最多一个）。"""
    if not profile.get("has_map"):
        return ""
    explain = (
        '<div class="sit-explain-slot" data-sit="map_explanation"></div>'
        if profile.get("has_map_explanation") else ""
    )
    return (
        f'<div class="card" style="grid-column:span {span}"><h3>地理分布</h3>'
        f'<div data-sit="map" style="height:{height}px"></div>{explain}</div>'
    )


def _kpi_items(profile: Dict[str, Any]) -> str:
    """KPI 指标卡占位符序列（不含外层容器），供各骨架自行包布局。"""
    items = []
    for ds in profile.get("kpi_datasets", []):
        columns = ds.get("columns") or []
        if not columns:
            continue
        column = columns[0]
        metrics = _json.dumps(
            [{"label": "记录总数", "column": column, "agg": "count"}],
            ensure_ascii=False,
        )
        items.append(
            f'<div data-sit="kpi" data-ref="{_esc(ds["datasetId"])}" '
            f"data-metrics='{_esc(metrics)}'></div>"
        )
    return "".join(items)


def _kpi_row(profile: Dict[str, Any]) -> str:
    """KPI 指标行：每个数据集一个 count 指标卡（确定性、恒可用）。"""
    items = _kpi_items(profile)
    if not items:
        return ""
    return f'<div class="kpi-row">{items}</div>'


def _intro_card(profile: Dict[str, Any], span: int = 12, top: bool = False) -> str:
    """态势介绍卡片：仅在有 intro 文本时输出。"""
    if not profile.get("has_intro"):
        return ""
    return (
        f'<div class="card intro-card" style="grid-column:span {span}">'
        + ("<h2 style=\"font-size:17px;margin:0 0 12px\">态势概述</h2>" if top else "<h3>态势介绍</h3>")
        + '<div data-sit="narrative" data-part="intro"></div></div>'
    )


def _page(title: str, extra_css: str, body: str, theme_css: str = "") -> str:
    """完整 HTML 文档包装（tokens + 动态主题 + 基础样式 + 骨架专属样式）。

    Args:
        theme_css: 动态主题令牌块（:root{--sit-*}），拼在静态 _TOKENS_CSS 之后，
            同名 CSS 变量后者覆盖前者；为空则保持现状静态主题。
    """
    return (
        '<!DOCTYPE html>\n<html lang="zh">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{_esc(title)}</title>\n<style>\n{_tokens_css()}\n{theme_css}\n{_BASE_CSS}\n{extra_css}\n</style>\n"
        f'</head>\n<body>\n<div class="wrap">\n<h1 class="page-title">{_esc(title)}</h1>\n'
        f"{body}\n</div>\n</body>\n</html>"
    )


# ── 5 个版式骨架 ──

# 多因素加权评分卡：每个骨架的 fit 由"产物画像 × 地图重要性 × 图型构成 × 句式意图"
# 四组因子加权合成（态势图-排版多样性与产物质量校验方案 §三.③）。
# 叙事极性 → 骨架语义加分（ABT 思想：语义只做平手决胜，幅度 ≤0.12）
_SEMANTIC_BONUS: Dict[str, Dict[str, float]] = {
    "alert": {"S1": 0.10},      # 预警升级：KPI 置顶的仪表盘
    "compare": {"S3": 0.10},    # 对比分析：多图并排对照
    "but": {"S4": 0.08},        # 问题聚焦：图文并茂讲清问题
    "therefore": {"S5": 0.08},  # 结论成果：收束式单列聚焦
}
# 叙事焦点含空间词 → 地图主导优先（has_map 边缘场景的决胜票）
_GEO_FOCUS_WORDS = ("geo", "分布", "区域", "空间", "地理")


def _semantic_bonus(skeleton_id: str, semantic: Optional[Dict[str, Any]]) -> float:
    """计算骨架的语义拟合加分（0 或小幅正值；semantic 缺失时恒为 0 = 现状行为）。"""
    if not isinstance(semantic, dict):
        return 0.0
    polarity = str(semantic.get("polarity") or "").strip().lower()
    bonus = _SEMANTIC_BONUS.get(polarity, {}).get(skeleton_id, 0.0)
    focus = str(semantic.get("focus") or "").strip().lower()
    if skeleton_id == "S2" and any(w in focus for w in _GEO_FOCUS_WORDS):
        bonus += 0.12
    return bonus


def _fit_s1(p: Dict[str, Any], semantic: Optional[Dict[str, Any]] = None) -> float:
    """S1 仪表盘型：多图 + KPI 齐全 + 预警意图；地图是主角时不适合。"""
    score = 0.2
    if p["chart_count"] >= 3:
        score += 0.25
    if p["kpi_datasets"]:
        score += 0.15
    if p["question_intent"] == "alert":
        score += 0.2
    # 图型混杂（≥3 种类型）适合仪表盘分格收纳
    if len(p.get("chart_type_mix") or {}) >= 3:
        score += 0.1
    if p["map_importance"] >= 0.7:
        score -= 0.25
    if not p["kpi_datasets"]:
        score -= 0.15
    return score + _semantic_bonus("S1", semantic)


def _render_s1(profile: Dict[str, Any], query: str, theme_css: str = "") -> str:
    """S1 仪表盘型：页头 → KPI 带 → 2×2 图表网格 → 地图全宽 → 介绍收尾。"""
    cards = [_chart_card(c, profile, span=6, height=320) for c in profile["charts"]]
    body = (
        _kpi_row(profile)
        + f'<div class="grid">{"".join(cards)}</div>'
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{_map_card(profile, span=12, height=480)}</div>'
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{_intro_card(profile)}</div>'
    )
    return _page(query, "", body, theme_css)


def _fit_s2(p: Dict[str, Any], semantic: Optional[Dict[str, Any]] = None) -> float:
    """S2 地图主导型：地图重要性是主变量；数据体量大、密度高时地图承载更优。"""
    if not p["has_map"]:
        return 0.0  # 无地图直接出局（替代原 -0.6 惩罚，杜绝"无图的大图版式"）
    score = 0.15 + p["map_importance"] * 0.55
    if 1 <= p["chart_count"] <= 3:
        score += 0.1
    if p["chart_count"] >= 5:
        score -= 0.15
    if p.get("map_density") in ("cluster", "heavy"):
        score += 0.1
    if p.get("data_volume") == "large":
        score += 0.05
    return score + _semantic_bonus("S2", semantic)


def _render_s2(profile: Dict[str, Any], query: str, theme_css: str = "") -> str:
    """S2 地图主导型：页头 → 地图大块（左 2/3）+ 右侧图表栏 → KPI → 介绍。"""
    charts = profile["charts"]
    first = charts[0] if charts else None
    rest = charts[1:]
    left = _map_card(profile, span=8, height=560)
    right_cards = []
    if first is not None:
        right_cards.append(_chart_card(first, profile, span=12, height=260))
    for c in rest:
        right_cards.append(_chart_card(c, profile, span=12, height=200))
    right = f'<div class="grid" style="grid-template-columns:1fr;grid-column:span 4;gap:var(--sit-gap)">{"".join(right_cards)}</div>' if right_cards else ""
    kpi_items = _kpi_items(profile)
    body = (
        f'<div class="grid" style="grid-template-columns:repeat(12,1fr)">{left}{right}</div>'
        + (f'<div class="kpi-row" style="margin-top:var(--sit-gap)">{kpi_items}</div>' if kpi_items else "")
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{_intro_card(profile)}</div>'
    )
    return _page(query, "", body, theme_css)


def _fit_s3(p: Dict[str, Any], semantic: Optional[Dict[str, Any]] = None) -> float:
    """S3 图表主导型：图多、地图次要；对比意图/多占比图时最优。"""
    score = 0.2
    if p["chart_count"] >= 3:
        score += 0.3
    if p["chart_count"] < 2:
        score -= 0.35
    if p["question_intent"] == "compare":
        score += 0.2
    # 占比型（pie）≥2 张时并列对照收益最大
    if (p.get("chart_type_mix") or {}).get("pie", 0) >= 2:
        score += 0.1
    if p["map_importance"] >= 0.7:
        score -= 0.2
    elif p["has_map"]:
        score += 0.05
    return score + _semantic_bonus("S3", semantic)


def _render_s3(profile: Dict[str, Any], query: str, theme_css: str = "") -> str:
    """S3 图表主导型：首图 8 列大卡 + 其余图 4 列堆叠 → 地图全宽 → 介绍。"""
    charts = profile["charts"]
    cards = []
    if charts:
        cards.append(_chart_card(charts[0], profile, span=8, height=400))
    for c in charts[1:]:
        cards.append(_chart_card(c, profile, span=4, height=280))
    body = (
        _kpi_row(profile)
        + f'<div class="grid">{"".join(cards)}</div>'
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{_map_card(profile, span=12, height=440)}</div>'
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{_intro_card(profile)}</div>'
    )
    return _page(query, "", body, theme_css)


def _fit_s4(p: Dict[str, Any], semantic: Optional[Dict[str, Any]] = None) -> float:
    """S4 叙事型：介绍丰富、2-3 张图；趋势/演化意图最优（折线多 → 纵向叙事）。"""
    score = 0.2
    if p["has_intro"]:
        score += 0.2
    if p["explanations"]:
        score += 0.1
    if 2 <= p["chart_count"] <= 3:
        score += 0.15
    if p["question_intent"] == "trend":
        score += 0.2
    # 趋势型图表（line）占主导时纵向图文交错阅读节奏最好
    mix = p.get("chart_type_mix") or {}
    if mix.get("line", 0) >= max(1, p["chart_count"] // 2) and p["chart_count"] >= 2:
        score += 0.1
    if p["chart_count"] >= 5:
        score -= 0.2
    if p["map_importance"] >= 0.7:
        score -= 0.15
    return score + _semantic_bonus("S4", semantic)


def _render_s4(profile: Dict[str, Any], query: str, theme_css: str = "") -> str:
    """S4 叙事型：介绍置顶 → 图文交错（图 + 就近说明）→ 地图。"""
    cards = [_chart_card(c, profile, span=6, height=340) for c in profile["charts"]]
    body = (
        _intro_card(profile, top=True)
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{"".join(cards)}</div>'
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{_map_card(profile, span=12, height=460)}</div>'
    )
    return _page(query, "", body, theme_css)


def _fit_s5(p: Dict[str, Any], semantic: Optional[Dict[str, Any]] = None) -> float:
    """S5 简报型：1-2 图、无地图、结论式收束时最优。"""
    score = 0.25
    if p["chart_count"] <= 2:
        score += 0.3
    if not p["has_map"]:
        score += 0.15
    if p["question_intent"] == "conclusion":
        score += 0.15
    if p["chart_count"] >= 4:
        score -= 0.5
    if p["map_importance"] >= 0.4:
        score -= 0.15
    return score + _semantic_bonus("S5", semantic)


def _render_s5(profile: Dict[str, Any], query: str, theme_css: str = "") -> str:
    """S5 简报型：单列紧凑——页头 → KPI → 图逐张全宽 → 地图（如有）→ 介绍。"""
    cards = [_chart_card(c, profile, span=12, height=360) for c in profile["charts"]]
    body = (
        _kpi_row(profile)
        + f'<div class="grid">{"".join(cards)}</div>'
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{_map_card(profile, span=12, height=440)}</div>'
        + f'<div class="grid" style="margin-top:var(--sit-gap)">{_intro_card(profile)}</div>'
    )
    return _page(query, "", body, theme_css)


# 骨架注册表：fit 为 0-1 确定性拟合分（可含语义加分），render(profile, query, theme_css) -> 完整 HTML
SKELETONS: List[Dict[str, Any]] = [
    {"id": "S1", "name": "仪表盘型", "fit": _fit_s1, "render": _render_s1},
    {"id": "S2", "name": "地图主导型", "fit": _fit_s2, "render": _render_s2},
    {"id": "S3", "name": "图表主导型", "fit": _fit_s3, "render": _render_s3},
    {"id": "S4", "name": "叙事型", "fit": _fit_s4, "render": _render_s4},
    {"id": "S5", "name": "简报型", "fit": _fit_s5, "render": _render_s5},
]

# 同分扰动阈值：fit 分差小于该值视为同分，进入扰动选取
_TIE_MARGIN = 0.08


def _tie_seed(profile: Dict[str, Any], query: str = "") -> int:
    """同分扰动的确定性种子：问题 + 画像内容哈希（跨任务多样、同任务可复现）。"""
    raw = str(query or "") + "|".join(
        [str(profile.get("chart_count")), str(profile.get("has_map")),
         str(profile.get("map_importance")), str(profile.get("question_intent")),
         str(profile.get("data_volume"))]
        + sorted((profile.get("chart_type_mix") or {}).keys())
    )
    return sum(ord(c) for c in raw)


def rank_skeletons(profile: Dict[str, Any],
                   semantic: Optional[Dict[str, Any]] = None,
                   query: str = "") -> List[Dict[str, Any]]:
    """按拟合分降序返回骨架列表（供调用方取 Top1/Top2 依次尝试）。

    同分扰动（态势图-排版多样性与产物质量校验方案 §三.③）：
    fit 分差 < _TIE_MARGIN 的骨架视为同分组，组内按「问题+画像」哈希轮转排序——
    不同问题命中不同骨架（跨任务多样），同一问题结果固定（可复现）。

    Args:
        semantic: Planner 叙事标签 {"polarity", "focus"}；None 时纯画像拟合（现状行为）
        query: 用户原始问题（同分扰动种子的一部分）
    """
    scored = [(s["fit"](profile, semantic), s) for s in SKELETONS]
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return []
    # 同分组扰动：只轮转与第一名同分的组（Top1 真正被扰动，后续候选保持分差序）
    top_score = scored[0][0]
    tied = [(score, s) for score, s in scored if top_score - score < _TIE_MARGIN]
    rest = [(score, s) for score, s in scored if top_score - score >= _TIE_MARGIN]
    if len(tied) > 1:
        offset = _tie_seed(profile, query) % len(tied)
        tied = tied[offset:] + tied[:offset]
    return [s for _, s in tied + rest]


def pick_skeleton(profile: Dict[str, Any],
                  semantic: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], float]:
    """选最优骨架。

    Args:
        semantic: 叙事标签（可选）

    Returns:
        (骨架 dict, 拟合分)
    """
    best = rank_skeletons(profile, semantic)[0]
    return best, best["fit"](profile, semantic)
