"""LLM Agent system prompt 与工具 schema（Phase 2 启用）。

Phase 1 不调用 LLM；此处预留 prompt 与 tool 定义，供 real_generate 接入。
时序硬约束（ADR-08）必须写入 prompt：图表/地图先出，文本为介绍+说明，最后产出。
地图标注 Skill 从 qa-service/skill/map_*.md 动态加载。
"""
from agent.map_skill_loader import load_map_skill_guide


def _build_system_prompt() -> str:
    """构建 SYSTEM_PROMPT，动态注入地图 Skill 指南。"""
    map_guide = load_map_skill_guide()
    if map_guide:
        map_section = f"\n{map_guide}\n"
    else:
        map_section = ""

    return f"""你是态势分析编排器。根据用户问题，按以下顺序调用工具产出态势图：

1) 调用数据工具（query_knowledge / get_indicators / get_evaluation / query_admin_data）获取数据；
2) 调用 render_chart 逐个产出图表（可多次调用，先于文本）；
3) 调用 render_map_layer 产出地图图层；
4) 最后调用 write_narrative 产出「态势介绍 + 逐图说明」。

硬约束：
- 禁止在图表产出前生成结论性文本。
- write_narrative 的 intro 是当前态势的介绍性描述，不是先验结论。
- explanations 的 chartId 必须命中已产出的图表。
- render_chart 的 option 必须是合法 ECharts JSON，数据内联。
- 中文输出。
{map_section}"""


# Phase 2 使用时调用此函数获取动态 prompt（延迟构建，避免 import 时序问题）
_system_prompt_cache: str | None = None

def get_system_prompt() -> str:
    """获取动态 SYSTEM_PROMPT（含地图 Skill 指南）。首次调用时构建并缓存。"""
    global _system_prompt_cache
    if _system_prompt_cache is None:
        _system_prompt_cache = _build_system_prompt()
    return _system_prompt_cache

# 向后兼容（Phase 2 迁移完成后可移除）
SYSTEM_PROMPT = get_system_prompt()


# 工具 JSON Schema 列表（OpenAI tools 格式）
TOOLS_SCHEMA: list = [
    {
        "type": "function",
        "function": {
            "name": "render_chart",
            "description": "产出单个统计图表。必须在 write_narrative 之前调用，可多次调用。",
            "parameters": {
                "type": "object",
                "required": ["chartId", "type", "title", "option"],
                "properties": {
                    "chartId": {"type": "string"},
                    "type": {"type": "string",
                             "enum": ["bar", "line", "pie", "radar", "gauge",
                                      "scatter", "heatmap", "relation", "sankey", "map"]},
                    "title": {"type": "string"},
                    "option": {"type": "object", "description": "ECharts option JSON，数据内联"},
                    "datasetRef": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_map_layer",
            "description": "产出地图图层，支持标点(markers)、连线(routes)、范围(areas/含圆形)、圆形(circles)四种标注。WGS84坐标。",
            "parameters": {
                "type": "object",
                "required": ["layerId"],
                "properties": {
                    "layerId": {"type": "string", "description": "图层唯一标识"},
                    "points": {
                        "type": "array",
                        "description": "标点列表",
                        "items": {
                            "type": "object",
                            "required": ["name", "lng", "lat"],
                            "properties": {
                                "name": {"type": "string", "description": "点位名称"},
                                "lng": {"type": "number", "description": "经度"},
                                "lat": {"type": "number", "description": "纬度"},
                                "raw": {"type": "string", "description": "原始描述（可选）"},
                            },
                        },
                    },
                    "routes": {
                        "type": "array",
                        "description": "路线列表",
                        "items": {
                            "type": "object",
                            "required": ["name", "points"],
                            "properties": {
                                "name": {"type": "string"},
                                "points": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["lng", "lat"],
                                        "properties": {
                                            "lng": {"type": "number"},
                                            "lat": {"type": "number"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "areas": {
                        "type": "array",
                        "description": "区域列表（多边形或圆形）",
                        "items": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "shape": {"type": "string", "enum": ["polygon", "circle"], "default": "polygon"},
                                "points": {
                                    "type": "array",
                                    "description": "多边形顶点（shape=polygon时必需，至少3个）",
                                    "items": {
                                        "type": "object",
                                        "required": ["lng", "lat"],
                                        "properties": {"lng": {"type": "number"}, "lat": {"type": "number"}},
                                    },
                                },
                                "center": {
                                    "type": "object",
                                    "description": "圆心（shape=circle时必需）",
                                    "required": ["lng", "lat"],
                                    "properties": {"lng": {"type": "number"}, "lat": {"type": "number"}},
                                },
                                "radiusKm": {"type": "number", "description": "圆半径（公里，shape=circle时必需）"},
                            },
                        },
                    },
                    "circles": {
                        "type": "array",
                        "description": "圆形区域列表（简便写法）",
                        "items": {
                            "type": "object",
                            "required": ["name", "center", "radiusKm"],
                            "properties": {
                                "name": {"type": "string"},
                                "center": {
                                    "type": "object",
                                    "required": ["lng", "lat"],
                                    "properties": {"lng": {"type": "number"}, "lat": {"type": "number"}},
                                },
                                "radiusKm": {"type": "number", "description": "圆半径（公里）"},
                            },
                        },
                    },
                    "layerConfig": {
                        "type": "object",
                        "description": "图层配置",
                        "properties": {
                            "color": {"type": "string", "default": "#e74c3c"},
                            "opacity": {"type": "number", "default": 0.85},
                        },
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_narrative",
            "description": "产出态势介绍 + 逐图说明。必须在所有图表和地图产出之后调用，为最后一步。",
            "parameters": {
                "type": "object",
                "required": ["intro", "explanations"],
                "properties": {
                    "intro": {"type": "string", "description": "态势介绍（描述性，非结论性）"},
                    "explanations": {
                        "type": "array",
                        "description": "逐图说明",
                        "items": {
                            "type": "object",
                            "required": ["chartId", "text"],
                            "properties": {
                                "chartId": {"type": "string", "description": "对应图表的 chartId"},
                                "text": {"type": "string", "description": "图表说明文字"},
                            },
                        },
                    },
                },
            },
        },
    },
]
