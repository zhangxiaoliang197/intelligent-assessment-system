"""LLM Agent system prompt 与工具 schema（Phase 2 启用）。

Phase 1 不调用 LLM；此处预留 prompt 与 tool 定义，供 real_generate 接入。
时序硬约束（ADR-08）必须写入 prompt：图表/地图先出，文本为介绍+说明，最后产出。
"""

SYSTEM_PROMPT = """你是态势分析编排器。根据用户问题，按以下顺序调用工具产出态势图：

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
"""

# 工具 JSON Schema 列表（OpenAI tools 格式），Phase 2 接入时填充
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
    # 其余工具 schema 待 Phase 2 补全（query_knowledge / get_indicators / ... / write_narrative）
]
