"""LLM Agent system prompt 与多阶段 JSON 协议 prompt（Phase 2）。

采用多阶段 JSON 协议（不依赖原生 function-calling，兼容所有 OpenAI 兼容模型）：
  阶段1 plan      规划要查哪些数据集、画什么图
  阶段2 data      编排器按 plan 取真实数据行（非 LLM）
  阶段3 chart     LLM 基于真实数据一次性生成 ECharts option 与逐图说明
  阶段4 map       LLM 生成地图图层标注（WGS84）
  阶段5 narrative LLM 撰写态势介绍 + 地图说明

时序硬约束（ADR-08）：图表/地图先出，文本为介绍+说明，最后产出。
地图标注 Skill 从 qa-service/skill/map_*.md 动态加载。
数据源无关：prompt 只描述「可用数据集 schema」，不出现任何特定表名/字段。
"""
import json
from agent.map_skill_loader import load_map_skill_guide


# ──────────────────────────────────────────────────────────
# 基础 system prompt（含地图 Skill 指南）
# ──────────────────────────────────────────────────────────
def _build_system_prompt() -> str:
    """构建 SYSTEM_PROMPT，动态注入地图 Skill 指南。"""
    map_guide = load_map_skill_guide()
    map_section = f"\n{map_guide}\n" if map_guide else ""
    return f"""你是态势分析编排器。根据用户问题与可用数据，分阶段产出态势图。

工作流程（严格按序）：
1) 规划：分析问题，决定要查询哪些数据集、生成哪些图表与地图图层；
2) 取数：由系统按规划执行数据集查询，取得真实数据行；
3) 产图：基于真实数据生成 ECharts option（数据内联，禁止占位符）；
4) 地图：基于数据与问题生成地图标注（WGS84 坐标）；
5) 文本：最后撰写态势介绍 + 逐图说明。

硬约束：
- 禁止在图表产出前生成结论性文本。
- 文本是介绍性描述，不是先验结论。
- ECharts option 必须是合法 JSON，数据内联为具体数值。
- 地图坐标用 WGS84（前端会转 GCJ02），不得编造中国境外坐标。
- 中文输出。
{map_section}"""


_system_prompt_cache: str | None = None


def get_system_prompt() -> str:
    """获取动态 SYSTEM_PROMPT（含地图 Skill 指南）。首次调用构建并缓存。"""
    global _system_prompt_cache
    if _system_prompt_cache is None:
        _system_prompt_cache = _build_system_prompt()
    return _system_prompt_cache


# 向后兼容（Phase 1 遗留）
SYSTEM_PROMPT = get_system_prompt()
TOOLS_SCHEMA: list = []


# ──────────────────────────────────────────────────────────
# 阶段 prompt 构造（每阶段返回 OpenAI messages 列表）
# ──────────────────────────────────────────────────────────
def _trim(text: str, limit: int) -> str:
    """截断文本到指定字符数，尾部标注省略。"""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...（已截断，原文共 {len(text)} 字符）"


def _format_meta(meta: dict) -> str:
    """把 /export/for-llm 返回的元数据格式化为 LLM 可读文本。数据源无关。"""
    if not meta or not meta.get("success"):
        return "（暂无可用数据集元数据）"
    data = meta.get("data", {})
    lines = []
    schemas = data.get("schemas", [])
    if schemas:
        lines.append("【可用数据集】（datasetId 是查询时必填的标识，勿用表名）")
        for s in schemas:
            lines.append(f"- datasetId={s.get('datasetId','')} 「{s.get('datasetName','')}」(表: {s.get('tableName','')})：{s.get('description','')}")
            fields = s.get("fields", [])
            if fields:
                # 每个数据集最多展示 12 个字段，避免 prompt 过长
                for f in fields[:12]:
                    biz = f.get("businessMeaning") or f.get("annotation") or f.get("comment") or ""
                    lines.append(f"    · {f.get('column','')} ({f.get('type','')}): {biz}")
                if len(fields) > 12:
                    lines.append(f"    · ...（共 {len(fields)} 个字段）")
    indicators = data.get("indicators", [])
    if indicators:
        lines.append("【可用指标】")
        for ind in indicators[:15]:
            lines.append(f"- {ind.get('name','')}：{ind.get('description','')}（公式: {ind.get('formula','')}）")
        if len(indicators) > 15:
            lines.append(f"- ...（共 {len(indicators)} 个指标）")
    return "\n".join(lines) if lines else "（数据集元数据为空）"


def _format_data(data: dict, max_rows: int = 30) -> str:
    """把 query_admin_data 返回的数据行格式化为 LLM 可读 JSON 文本。"""
    if not data or not data.get("success"):
        return f"（数据查询失败: {data.get('message', '未知') if data else '无响应'}）"
    columns = data.get("columns", [])
    rows = data.get("rows", [])
    total = data.get("total", len(rows))
    sample = rows[:max_rows]
    text = json.dumps({"columns": columns, "rows": sample, "totalRows": total},
                      ensure_ascii=False, default=str)
    return _trim(text, 6000)


def build_plan_messages(query: str, meta: dict) -> list:
    """阶段1：规划。LLM 据可用数据集元数据决定查什么、画什么。"""
    return [
        {"role": "system", "content": get_system_prompt() +
            "\n\n【当前阶段：规划】\n"
            "根据用户问题与下方可用数据集元数据，规划本次态势图要查询的数据集与要生成的图表/地图。\n"
            "返回 JSON（仅 JSON，无其它文字）：\n"
            "{\n"
            '  "datasets": [{"datasetId": "数据集ID", "intent": "查询意图", "limit": 200}],\n'
            '  "chartsPlan": [{"type": "bar|line|pie|radar|...", "title": "图表标题", "intent": "图表目的"}],\n'
            '  "mapPlan": [{"layerId": "图层ID", "intent": "地图目的"}],\n'
            '  "needKnowledge": false,\n'
            '  "knowledgeQuery": ""\n'
            "}\n"
            "规则：datasetId 必须来自下方可用数据集；若数据集不含地理坐标字段，mapPlan 可为空数组；"
            "图表数量 1-4 个，聚焦问题核心。"},
        {"role": "user", "content": f"用户问题：{query}\n\n可用数据集元数据：\n{_format_meta(meta)}"},
    ]


def build_chart_messages(query: str, data_context: dict, plan: dict) -> list:
    """阶段3：产图。LLM 基于真实数据行一次性生成 ECharts option 与逐图说明。"""
    plans = plan.get("chartsPlan", [])
    plans_text = "\n".join(f"- {p.get('type','')}: {p.get('title','')}（{p.get('intent','')}）"
                           for p in plans) or "（规划阶段未指定图表，请根据数据自行设计 1-4 个最贴切问题的图表，按需选择图表个数）"
    data_text = ""
    for ds_id, ds_data in data_context.items():
        data_text += f"\n--- 数据集 {ds_id} ---\n{_format_data(ds_data)}\n"
    if not data_text:
        data_text = "（未取得数据，请基于问题常识生成代表性图表，option 数据内联具体数值）"
    return [
        {"role": "system", "content": get_system_prompt() +
            "\n\n【当前阶段：产图】\n"
            "基于真实数据行，一次性生成 ECharts option JSON 数组，并随每个图表一并给出该图的详细说明（explanation）。"
            "每个图表的 option 必须内联具体数据值，禁止占位符。\n"
            "返回 JSON 数组（仅 JSON）：\n"
            '[{"chartId": "c_1", "type": "line", "title": "标题", "option": {ECharts完整option}, "datasetRef": "数据集ID", "explanation": "该图详细说明"}]\n'
            "规则：chartId 用 c_1/c_2...；option 必须是合法 ECharts 配置（含 series/xAxis/yAxis 等）；"
            "explanation 是该图的逐图说明（用于态势报告的图表解读，需说明图表展示的内容、关键数据特征与分析要点，1-3 句，中文）；"
            "数据来自上方真实数据行，不得编造；若无合适数据可降级为说明性图表。"},
        {"role": "user", "content": f"用户问题：{query}\n\n图表规划：\n{plans_text}\n\n真实数据：\n{data_text}"},
    ]


def build_map_messages(query: str, data_context: dict) -> list:
    """阶段4：地图。LLM 基于数据与问题生成地图图层标注（WGS84）。"""
    data_text = ""
    for ds_id, ds_data in data_context.items():
        data_text += f"\n--- 数据集 {ds_id} ---\n{_format_data(ds_data, max_rows=50)}\n"
    if not data_text:
        data_text = "（无数据，若问题涉及地理则按常识生成代表性标注，否则返回空图层）"
    return [
        {"role": "system", "content": get_system_prompt() +
            "\n\n【当前阶段：地图】\n"
            "根据数据与问题生成地图图层标注。坐标用 WGS84（前端会转 GCJ02）。\n"
            "返回 JSON（仅 JSON）：\n"
            '{\n'
            '  "layerId": "main",\n'
            '  "points": [{"name": "名称", "lng": 116.4, "lat": 39.9, "weight": 1.0, "raw": "描述"}],\n'
            '  "routes": [],\n'
            '  "areas": [],\n'
            '  "circles": [{"name": "名称", "center": {"lng": 113.27, "lat": 23.13}, "radiusKm": 120}],\n'
            '  "layerConfig": {"type": "heatmap", "color": "#e74c3c", "opacity": 0.85}\n'
            '}\n'
            "规则：layerConfig.type 取值 points（普通标点，默认）或 heatmap（热力图）。"
            "当用户要求热力图/热度分布且数据含地理字段时，应设 type=heatmap，并为 points 中每个点带 weight（热度权重，数值越大越热，可用该位置的样本量或指标值归一化）；"
            "type=points 时 weight 可省略。"
            "坐标必须来自数据中的地理字段（若有），不得编造境外坐标；"
            "若数据无地理信息且问题不涉及空间分布，返回空 points/routes/areas/circles 数组（layerId 仍保留）。"},
        {"role": "user", "content": f"用户问题：{query}\n\n真实数据：\n{data_text}"},
    ]


def build_narrative_messages(query: str, charts: list, map_layer: dict) -> list:
    """阶段5：文本。LLM 撰写态势介绍 + 地图说明（逐图说明已在产图阶段随图生成）。"""
    charts_summary = "\n".join(f"- {c.get('chartId','')}: {c.get('title','')}（{c.get('explanation','')}）"
                               for c in charts) or "（无图表）"
    points = map_layer.get("points", []) if map_layer else []
    routes = map_layer.get("routes", []) if map_layer else []
    areas = map_layer.get("areas", []) if map_layer else []
    circles = map_layer.get("circles", []) if map_layer else []
    map_summary = (
        f"图层 {map_layer.get('layerId','')}：{len(points)} 个标点、{len(routes)} 条路线、"
        f"{len(areas)} 个区域、{len(circles)} 个圆形区域"
        if map_layer else "（无地图）"
    )
    return [
        {"role": "system", "content": get_system_prompt() +
            "\n\n【当前阶段：文本】\n"
            "撰写态势介绍 + 地图说明。intro 是介绍性描述（非先验结论），mapExplanation 对应地图（若存在地图则必填，否则为空字符串）。"
            "逐图说明已在产图阶段随各图表生成，无需在此重复。\n"
            "返回 JSON（仅 JSON）：\n"
            '{"intro": "态势介绍段落", "mapExplanation": "地图说明"}\n'
            "规则：intro 不超过 300 字；中文。"},
        {"role": "user", "content": f"用户问题：{query}\n\n已产出图表：\n{charts_summary}\n\n地图：{map_summary}"},
    ]
