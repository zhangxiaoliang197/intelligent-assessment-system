"""Context-aware follow-up topic recommendations for situation reports.

The recommender is intentionally deterministic: the UI can refresh it while the
user is typing without introducing an extra LLM call, latency spike, or a new
failure mode.  The actual situation generation still uses the normal Skill +
agent pipeline.
"""
from __future__ import annotations

import hashlib
import datetime as dt
import re
from typing import Any, Callable, Dict, List, Optional


SkillResolver = Callable[[str], Optional[Dict[str, Any]]]


def _text(value: Any, maximum: int = 160) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    return normalized[:maximum]


def _short_title(value: str, fallback: str) -> str:
    text = _text(value, 28).strip("，。！？；:： ")
    if not text:
        return fallback
    return text if len(text) <= 18 else f"{text[:18]}…"


def _time_label(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return "近期"
    def format_part(item: Any) -> str:
        if isinstance(item, (int, float)) or re.fullmatch(r"\d{10,13}", str(item or "")):
            try:
                number = float(item)
                if abs(number) > 10_000_000_000:
                    number /= 1000
                return dt.datetime.fromtimestamp(number).strftime("%Y-%m-%d")
            except (ValueError, TypeError, OSError, OverflowError):
                pass
        text = _text(item, 32)
        return text[:10] if re.match(r"20\d{2}-\d{2}-\d{2}", text) else text

    start, end = (format_part(item) for item in value)
    return f"{start} 至 {end}" if start and end else "近期"


def _context_tags(context: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    region = _text(context.get("selectedRegion") or context.get("regionName"), 40)
    if region:
        tags.append(f"区域：{region}")
    selected_time = context.get("selectedTimeRange")
    if isinstance(selected_time, (list, tuple)) and len(selected_time) == 2:
        tags.append(f"时段：{_time_label(selected_time)}")
    skill_name = _text(context.get("skillName"), 40)
    if skill_name:
        tags.append(f"Skill：{skill_name}")
    chart_titles = context.get("chartTitles")
    if isinstance(chart_titles, list) and chart_titles:
        tags.append(f"图表：{_text(chart_titles[0], 28)}")
    layer_names = context.get("layerNames")
    if isinstance(layer_names, list) and layer_names:
        tags.append(f"图层：{_text(layer_names[0], 28)}")
    return tags[:4]


def build_contextual_generation_query(query: str, parent_query: str) -> str:
    """Expand an elliptical follow-up for the agent without changing report.query."""
    current = _text(query, 2000)
    parent = _text(parent_query, 2000)
    if not parent or not current or parent == current:
        return ""
    return (
        f"上一轮态势主题：{parent}\n"
        f"当前用户追问：{current}\n"
        "请承接上一轮主题理解本轮追问，生成一份可独立查看的专题态势；"
        "不得臆造上一轮未提供的数据，仍以本轮可访问的数据源和证据为准。"
    )[:4000]


def recommend_topic_situations(
    current_query: str,
    question: str = "",
    context: Optional[Dict[str, Any]] = None,
    limit: int = 4,
    skill_resolver: Optional[SkillResolver] = None,
) -> Dict[str, Any]:
    """Build standalone, one-click follow-up topics from the current situation."""
    runtime_context = dict(context or {})
    subject = _text(current_query, 500) or "当前综合态势"
    follow_up = _text(question, 500)
    region = _text(
        runtime_context.get("selectedRegion") or runtime_context.get("regionName"),
        60,
    )
    time_label = _time_label(runtime_context.get("selectedTimeRange"))
    tags = _context_tags(runtime_context)
    reason_parts = ["承接当前态势"]
    if follow_up:
        reason_parts.append("结合你的追问")
    if region:
        reason_parts.append("沿用已选区域")
    if runtime_context.get("selectedTimeRange"):
        reason_parts.append("沿用当前时段")
    common_reason = " · ".join(reason_parts)

    candidates: List[Dict[str, str]] = []
    if follow_up:
        candidates.append({
            "dimension": "追问专题",
            "title": _short_title(follow_up, "基于追问的专题态势"),
            "description": "把当前追问与上一轮态势合并研判",
            "query": (
                f"基于“{subject}”继续探索：{follow_up}。"
                "生成专题态势，突出关键指标、空间分布、异常点与证据结论。"
            ),
        })

    spatial_focus = region or "重点区域"
    candidates.extend([
        {
            "dimension": "空间聚焦",
            "title": f"{spatial_focus}热点与覆盖专题",
            "description": "下钻热点分布、覆盖空白与空间关联",
            "query": (
                f"围绕“{subject}”{f'及追问“{follow_up}”' if follow_up else ''}，"
                f"聚焦{spatial_focus}，分析热点分布、覆盖空白、异常聚集和空间关联，生成专题态势。"
            ),
        },
        {
            "dimension": "时间演化",
            "title": "时间演化与趋势专题",
            "description": "识别阶段变化、拐点与趋势信号",
            "query": (
                f"围绕“{subject}”{f'及追问“{follow_up}”' if follow_up else ''}，"
                f"分析{time_label}的态势演化、关键拐点、增减趋势和驱动因素，生成时间演化专题态势。"
            ),
        },
        {
            "dimension": "对比研判",
            "title": "关键力量与指标对比专题",
            "description": "对比核心对象，定位优势、差距与变化",
            "query": (
                f"基于“{subject}”{f'和追问“{follow_up}”' if follow_up else ''}，"
                "选取关键对象和核心指标进行横向对比，研判优势、差距及其空间分布，生成对比专题态势。"
            ),
        },
        {
            "dimension": "风险预警",
            "title": "异常风险与薄弱环节专题",
            "description": "聚焦异常、风险信号与处置优先级",
            "query": (
                f"基于“{subject}”{f'和追问“{follow_up}”' if follow_up else ''}，"
                "识别异常点、潜在风险和薄弱环节，评估影响范围与优先级，生成风险预警专题态势。"
            ),
        },
    ])

    requested_limit = max(1, min(int(limit or 4), 6))
    # A typed follow-up is always the first recommendation; without one, keep
    # the four complementary exploration dimensions.
    chosen = candidates[:requested_limit]
    topics: List[Dict[str, Any]] = []
    for index, candidate in enumerate(chosen):
        query = _text(candidate["query"], 1800)
        skill = skill_resolver(query) if skill_resolver else None
        digest = hashlib.sha1(
            f"{subject}|{follow_up}|{candidate['dimension']}".encode("utf-8")
        ).hexdigest()[:12]
        topics.append({
            "id": f"topic-{digest}",
            **candidate,
            "query": query,
            "reason": common_reason,
            "contextTags": tags,
            "rank": index + 1,
            "skillId": _text((skill or {}).get("id"), 128),
            "skillName": _text((skill or {}).get("name"), 80),
            "skillReason": _text((skill or {}).get("recommendationReason"), 180),
        })

    return {
        "items": topics,
        "total": len(topics),
        "currentQuery": subject,
        "question": follow_up,
        "contextTags": tags,
    }
