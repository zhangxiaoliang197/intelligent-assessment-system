"""chart option 规范化管线（态势图-排版多样性与产物质量校验方案 §三.①）。

职责：在 chart Writer 产出 ECharts option 之后、进入 VERIFY 之前，
用纯规则（零 LLM）修复常见视觉质量问题：

- 文字防重叠：饼图/散点/关系图注入 labelLayout.hideOverlap（ECharts 官方布局算法）；
  x 轴类目多/长时注入 axisLabel interval/rotate/truncate；
- 图例补全：多 series 无图例 → 补滚动图例；图例条目过多 → type='scroll'；
- 数据量适配：line/scatter 单系列超阈值 → sampling:'lttb' + large + showSymbol:false；
- 配色对齐：series 缺色时注入专业 categorical 调色板（与主题令牌同源的蓝系基调）；
- bar 类目过多 → 旋转为横向条形。

设计边界：
- 只补全/增强"展示层"配置，绝不修改任何数据值（data 数组原样保留）；
- 已存在的用户/LLM 配置优先（只补缺，不覆盖），避免破坏 LLM 刻意设计；
- 全部确定性规则，无 LLM 依赖（DeepSeek 402 时照常工作）。
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("situation-service")

# ── 阈值常量（可按需调） ──
# 单系列数据点超过该值时启用大数据采样与 large 模式
_LARGE_SERIES_THRESHOLD = 1000
# x 轴类目数超过该值时旋转轴标签
_AXIS_CATEGORY_ROTATE_THRESHOLD = 8
# 类目平均字符长度超过该值时启用截断
_AXIS_LABEL_TRUNCATE_AVG_LEN = 4
# bar 类目数超过该值时旋转为横向条形图
_BAR_HORIZONTAL_THRESHOLD = 20
# 图例条目超过该值时启用滚动翻页
_LEGEND_SCROLL_THRESHOLD = 10

# 专业 categorical 调色板（蓝系主调，与默认主题令牌 --sit-primary:#2563eb 协调；
# 8 色循环，相邻色差大，深浅色交替保证白底可读）
_CATEGORICAL_PALETTE = [
    "#2563eb", "#d97706", "#0f766e", "#7c3aed",
    "#dc2626", "#0369a1", "#b45309", "#4f46e5",
]

# 需要防标签重叠的图型（labelLayout 生效的系列类型）
_LABEL_OVERLAP_TYPES = {"pie", "scatter", "graph"}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _series_list(option: Dict[str, Any]) -> List[Dict[str, Any]]:
    """抽取 option.series 中的 dict 系列列表（非法项剔除）。"""
    return [s for s in _as_list(option.get("series")) if isinstance(s, dict)]


def _series_data_length(series: Dict[str, Any]) -> int:
    data = series.get("data")
    return len(data) if isinstance(data, list) else 0


def _category_axis_labels(option: Dict[str, Any]) -> List[str]:
    """抽取类目轴（xAxis/yAxis type=category）上的类目文本。"""
    labels: List[str] = []
    for axis_key in ("xAxis", "yAxis"):
        axis = option.get(axis_key)
        # 兼容单对象与数组两种写法
        axes = axis if isinstance(axis, list) else ([axis] if isinstance(axis, dict) else [])
        for item in axes:
            if not isinstance(item, dict) or item.get("type", "category") != "category":
                continue
            data = item.get("data")
            if isinstance(data, list):
                labels.extend(str(v) for v in data)
    return labels


def _is_category_axis(axis_value: Any) -> bool:
    """判断 xAxis/yAxis 配置（对象或数组）是否为类目轴。"""
    axes = axis_value if isinstance(axis_value, list) else [axis_value]
    return any(
        isinstance(item, dict) and item.get("type", "category") == "category"
        for item in axes
    )


# ── 各项规范化规则（全部"只补缺不覆盖"） ──

def _polish_label_overlap(chart_type: str, series: List[Dict[str, Any]]) -> bool:
    """文字防重叠：为饼图/散点/关系图系列注入 labelLayout。

    Returns:
        是否有注入发生
    """
    changed = False
    for s in series:
        s_type = str(s.get("type") or chart_type).lower()
        if s_type not in _LABEL_OVERLAP_TYPES:
            continue
        label_layout = s.get("labelLayout")
        if not isinstance(label_layout, dict):
            s["labelLayout"] = {"hideOverlap": True, "moveOverlap": "shiftY"}
            changed = True
        else:
            if "hideOverlap" not in label_layout:
                label_layout["hideOverlap"] = True
                changed = True
        # 饼图额外：标签对齐到引导线端点，减少径向压盖
        if s_type == "pie":
            s.setdefault("avoidLabelOverlap", True)
            ll = s["labelLayout"]
            ll.setdefault("alignTo", "labelLine")
            changed = True
    return changed


def _polish_axis_labels(option: Dict[str, Any]) -> bool:
    """轴标签防重叠：类目多或文本长时旋转 + 截断（只补缺不覆盖）。"""
    labels = _category_axis_labels(option)
    if len(labels) < _AXIS_CATEGORY_ROTATE_THRESHOLD:
        return False
    avg_len = sum(len(v) for v in labels) / max(1, len(labels))
    if len(labels) < _AXIS_CATEGORY_ROTATE_THRESHOLD and avg_len < _AXIS_LABEL_TRUNCATE_AVG_LEN:
        return False

    changed = False
    for axis_key in ("xAxis", "yAxis"):
        axis = option.get(axis_key)
        axes = axis if isinstance(axis, list) else ([axis] if isinstance(axis, dict) else [])
        for item in axes:
            if not isinstance(item, dict) or item.get("type", "category") != "category":
                continue
            axis_label = item.get("axisLabel")
            if not isinstance(axis_label, dict):
                axis_label = {}
                item["axisLabel"] = axis_label
            before = dict(axis_label)
            axis_label.setdefault("interval", "auto")
            axis_label.setdefault("rotate", 30)
            if avg_len >= _AXIS_LABEL_TRUNCATE_AVG_LEN:
                axis_label.setdefault("width", 80)
                axis_label.setdefault("overflow", "truncate")
            if axis_label != before:
                changed = True
    return changed


def _polish_large_series(chart_type: str, series: List[Dict[str, Any]]) -> bool:
    """大数据量适配：line/scatter 单系列超阈值时注入采样与 large 模式。"""
    changed = False
    for s in series:
        s_type = str(s.get("type") or chart_type).lower()
        if s_type not in ("line", "scatter"):
            continue
        if _series_data_length(s) <= _LARGE_SERIES_THRESHOLD:
            continue
        if s_type == "line" and "sampling" not in s:
            # LTTB 采样保留趋势特征（波峰/波谷），官方推荐的大数据折线方案
            s["sampling"] = "lttb"
            changed = True
        s.setdefault("large", True)
        s.setdefault("largeThreshold", _LARGE_SERIES_THRESHOLD)
        # 大数据下标记点是最大性能开销项，默认关闭
        s.setdefault("showSymbol", False)
        s.setdefault("animation", False)
        changed = True
    return changed


def _polish_legend(chart_type: str, option: Dict[str, Any], series: List[Dict[str, Any]]) -> bool:
    """图例补全：多 series 缺图例 → 补滚动图例；条目过多 → type='scroll'。"""
    legend = option.get("legend")
    # 多系列命名需要图例才可辨识
    named_series = [s for s in series if s.get("name")]
    if legend is None and len(named_series) >= 2:
        option["legend"] = {"type": "scroll", "bottom": 0}
        return True
    legends = legend if isinstance(legend, list) else ([legend] if isinstance(legend, dict) else [])
    changed = False
    for item in legends:
        data = item.get("data")
        count = len(data) if isinstance(data, list) else len(named_series)
        if count > _LEGEND_SCROLL_THRESHOLD and item.get("type") != "scroll":
            item["type"] = "scroll"
            changed = True
    return changed


def _polish_colors(option: Dict[str, Any], series: List[Dict[str, Any]]) -> bool:
    """配色对齐：series 普遍缺色时注入调色板（LLM 已指定颜色则不干预）。"""
    if not series:
        return False
    # 全局 color 已存在则不干预
    if isinstance(option.get("color"), list) and option["color"]:
        return False
    # 任一系列显式指定了 itemStyle.color / lineStyle.color 视为 LLM 刻意配色
    for s in series:
        for style_key in ("itemStyle", "lineStyle"):
            style = s.get(style_key)
            if isinstance(style, dict) and style.get("color"):
                return False
    option["color"] = list(_CATEGORICAL_PALETTE)
    return True


def _title_present(option: Dict[str, Any]) -> bool:
    """option.title 是否实际带标题文本（dict 或 list 任一非空）。"""
    title = option.get("title")
    items = title if isinstance(title, list) else ([title] if isinstance(title, dict) else [])
    return any(bool((t or {}).get("text")) for t in items)


def _legend_present(option: Dict[str, Any]) -> bool:
    """option.legend 是否存在（存在即渲染，空 dict 也会显示系列名图例）。"""
    legend = option.get("legend")
    if isinstance(legend, list):
        return any(isinstance(x, dict) for x in legend)
    return isinstance(legend, dict)


def _x_category_rotated(option: Dict[str, Any]) -> bool:
    """x 类目轴是否启用旋转标签（旋转后需要更大的底部留白）。"""
    x_axis = option.get("xAxis")
    axes = x_axis if isinstance(x_axis, list) else ([x_axis] if isinstance(x_axis, dict) else [])
    for item in axes:
        if not isinstance(item, dict) or item.get("type", "category") != "category":
            continue
        label = item.get("axisLabel")
        if isinstance(label, dict) and label.get("rotate"):
            return True
    return False


def _polish_grid(option: Dict[str, Any]) -> bool:
    """绘图区边距规范化：修复 LLM 固定像素边距在矮/窄容器内压扁绘图区的问题。

    实测问题：LLM 给 grid.top=100、bottom='12%'，而图表槽常为 200px 高，
    绘图区只剩 ~60px，旋转的 x 轴日期标签侵入绘图区与 y 轴刻度重叠（折线
    "前段被截断"视觉问题的直接成因）。规则：
    - top 按 title/legend 实际占用钳制（双者齐全 72 / 仅标题 48 / 其他 24）；
    - x 轴旋转标签时 bottom 像素保底 56（百分比在矮容器不足）；
    - 统一 containLabel，避免轴名与刻度贴边被裁。
    """
    raw_grid = option.get("grid")
    if raw_grid is None:
        option["grid"] = {}
        grids: List[Dict[str, Any]] = [option["grid"]]
    elif isinstance(raw_grid, dict):
        grids = [raw_grid]
    elif isinstance(raw_grid, list):
        grids = [g for g in raw_grid if isinstance(g, dict)]
        if not grids:
            return False
    else:
        return False

    top_cap = 72 if (_title_present(option) and _legend_present(option)) else (
        48 if _title_present(option) else 24)
    rotated = _x_category_rotated(option)
    bottom_floor = 56 if rotated else 32

    changed = False
    for g in grids:
        if not g.get("containLabel"):
            g["containLabel"] = True
            changed = True
        top = g.get("top")
        # 缺省补到上限；过大的固定像素值钳制（百分比边距在窄容器反而自适应，保留）
        if top is None:
            g["top"] = top_cap
            changed = True
        elif isinstance(top, (int, float)) and top > top_cap:
            g["top"] = top_cap
            changed = True
        bottom = g.get("bottom")
        # 旋转标签场景：缺省/过小像素值/百分比 → 像素保底（百分比在矮容器仅 24-43px）
        if rotated and (not isinstance(bottom, (int, float)) or bottom < bottom_floor):
            g["bottom"] = bottom_floor
            changed = True
        elif bottom is None:
            g["bottom"] = bottom_floor
            changed = True
    return changed


def _polish_bar_orientation(chart_type: str, option: Dict[str, Any], series: List[Dict[str, Any]]) -> bool:
    """bar 类目过多时旋转为横向条形图（x 轴类目压盖的根本解）。"""
    if chart_type != "bar":
        return False
    labels = _category_axis_labels(option)
    if len(labels) <= _BAR_HORIZONTAL_THRESHOLD:
        return False
    # 已是横向（类目在 y 轴）则跳过
    if _is_category_axis(option.get("yAxis")):
        return False
    x_axis, y_axis = option.get("xAxis"), option.get("yAxis")
    if not isinstance(x_axis, dict) or not isinstance(y_axis, dict):
        return False
    # 交换两轴配置，类目轴移到 y
    option["xAxis"], option["yAxis"] = y_axis, x_axis
    # 横向后轴标签不需要旋转
    new_y = option["yAxis"]
    if isinstance(new_y, dict) and isinstance(new_y.get("axisLabel"), dict):
        new_y["axisLabel"].pop("rotate", None)
        new_y["axisLabel"].setdefault("width", 100)
        new_y["axisLabel"].setdefault("overflow", "truncate")
    return True


def polish_chart(chart: Dict[str, Any]) -> Dict[str, Any]:
    """对单个 chart dict 执行规范化管线（原地修改 option，返回同一对象）。

    Args:
        chart: {"chartId", "type", "option", ...}

    Returns:
        规范化后的 chart（option 可能被注入展示层配置；数据值不变）
    """
    if not isinstance(chart, dict):
        return chart
    option = chart.get("option")
    if not isinstance(option, dict):
        return chart

    chart_type = str(chart.get("type") or "bar").lower()
    series = _series_list(option)
    if not series:
        return chart

    applied: List[str] = []
    if _polish_label_overlap(chart_type, series):
        applied.append("label_overlap")
    if _polish_axis_labels(option):
        applied.append("axis_label")
    # 必须在 axis_labels 之后：旋转标签可能由上一步注入，grid 留白据此保底
    if _polish_grid(option):
        applied.append("grid")
    if _polish_large_series(chart_type, series):
        applied.append("large_sampling")
    if _polish_legend(chart_type, option, series):
        applied.append("legend")
    if _polish_colors(option, series):
        applied.append("palette")
    if _polish_bar_orientation(chart_type, option, series):
        applied.append("bar_horizontal")

    if applied:
        logger.info("chart %s option 规范化: %s", chart.get("chartId"), ",".join(applied))
    return chart


def polish_charts(charts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量规范化（保持顺序；None/非法项原样跳过）。"""
    return [polish_chart(c) if isinstance(c, dict) else c for c in charts or []]


__all__ = ["polish_chart", "polish_charts"]
