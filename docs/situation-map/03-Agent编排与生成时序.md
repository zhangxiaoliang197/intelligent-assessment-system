# 03 · Agent 编排与生成时序

> 本章约束 situation-service 的 LLM Agent 行为。**核心硬约束：图表/地图先出，文本为「态势介绍 + 图表说明」随后，不得结论先行（ADR-08）。**

## 1. Agent 总体模式

采用 **tool-calling 循环**（OpenAI 兼容 `tools` 字段）。模型不支持时降级为 **JSON 计划模式**（Q-01）。

### 1.1 tool-calling 循环（主模式）

```
system: 你是态势分析编排器。根据用户问题，按顺序：
        1) 调用数据工具获取数据；
        2) 调用 render_chart 逐个产出图表（先于文本）；
        3) 调用 render_map_layer 产出地图图层；
        4) 调用 write_narrative 产出「态势介绍 + 逐图说明」（最后）。
        禁止在图表产出前生成结论性文本。
user:   <用户问题 / 草稿态上下文>

循环:
  resp = call_llm_with_tools(messages, tools)
  if resp.tool_calls:
      for call in resp.tool_calls:
          result = dispatch(call)          # 执行工具, 同时通过 SSE 推送中间事件
          messages.append(tool_result)     # 回填
      continue
  else:
      # 无 tool_calls 视为结束（理论上最后一步应由 write_narrative 收尾）
      break
```

### 1.2 JSON 计划模式（降级）

若模型不支持 function-calling：

1. `call_llm_json` 产出计划 `{datasets:[...], charts:[{type,title,datasetRef}], map_layers:[...]}`
2. 编排器按计划执行：拉数据 → 逐图生成 option → 地图图层 → 最后 `call_llm_json` 产 narrative
3. 时序约束同样生效（图表先于文本）

## 2. 工具集（Tool Registry）

工具 = LLM 可调用的数据/产出接口。每个工具对应一个 Python 函数 + JSON Schema 描述。

| 工具名 | 作用 | 下游 | 产出事件（SSE） |
|--------|------|------|------------------|
| `query_knowledge` | 知识库检索 | qa-service / knowledge-service | `dataset` |
| `get_indicators` | 取指标数据 | indicator-service | `dataset` |
| `get_evaluation` | 取评估结果 | qa-service(/api/evaluation) | `dataset` |
| `query_admin_data` | 取数据源/字段/原始记录 | admin-service | `dataset` |
| `fetch_external_data` | 外部实时数据源（预留适配器） | external | `dataset` |
| `render_chart` | 产出单个图表（ECharts option） | （内部） | `chart` |
| `render_map_layer` | 产出地图图层/点位/路线/区域 | （内部） | `map_layer` |
| `write_narrative` | 产出态势介绍 + 逐图说明 | （内部，最后调用） | `narrative` |

### 2.1 工具 JSON Schema 示例（render_chart）

```json
{
  "type": "function",
  "function": {
    "name": "render_chart",
    "description": "产出单个统计图表。必须在 write_narrative 之前调用。可多次调用产出多个图表。",
    "parameters": {
      "type": "object",
      "required": ["chartId", "type", "title", "option"],
      "properties": {
        "chartId":   { "type": "string", "description": "图表唯一 id，供说明引用" },
        "type":      { "type": "string", "enum": ["bar","line","pie","radar","gauge","scatter","heatmap","relation","sankey","map"] },
        "title":     { "type": "string" },
        "option":    { "type": "object", "description": "ECharts option JSON，数据须内联" },
        "datasetRef":{ "type": "string", "description": "引用的 datasetId" }
      }
    }
  }
}
```

### 2.2 工具实现约束
- 每个工具函数返回结构化结果（dict），编排器回填给 LLM。
- `render_chart` / `render_map_layer` / `write_narrative` 在执行时**同时**通过 SSE 推送对应事件给前端（不等循环结束）。
- 工具失败时返回 `{success:false, message:...}` 给 LLM，让其决定重试或跳过，**不中断**整体流。

## 3. 生成时序（硬约束）

```
t0  用户提问 / 草稿态触发
    │ POST /generate → 立即返回 reportId（status=generating）+ 建立 SSE
    ▼
t1  [plan]      Agent 规划要哪些数据/图表/地图  → SSE: event=plan
    │
t2  [dataset]   逐个拉数据                      → SSE: event=dataset (可多条)
    │
t3  [chart]     逐个产出图表 option             → SSE: event=chart (图表一个个冒出) ★先于文本
    │
t4  [map_layer] 产出地图图层/点位               → SSE: event=map_layer
    │
t5  [narrative] 产出态势介绍 + 逐图说明         → SSE: event=narrative ★最后
    │   ├─ intro:        当前态势整体介绍（介绍性，非结论）
    │   └─ explanations: [{chartId, text}] 逐图解释
    ▼
t6  [done]      持久化 → status=ready           → SSE: event=done {reportId}
    │
t7  [tick]      外部数据源有更新                 → SSE: event=chart_update / map_update （持续，生成完成后）
```

### 3.1 时序校验
编排器在 `write_narrative` 被调用前，**拒绝**任何 narrative 输出；若 LLM 在 `render_chart` 之前尝试输出结论性文本，编排器应将其丢弃并提示「请先产出图表」。这是 ADR-08 的实现保障。

### 3.2 为什么这样排序（用户反馈）
> 「结论比图表先出不符合直觉」「文本应是当前态势介绍和对图表的说明」

因此文本是**描述性/解释性**的，依附于已生成的图表，而非先验结论。

## 4. SSE 事件协议（概要）

详细字段见 [04-接口契约.md](./04-接口契约.md) §3。事件类型：

| event | data 要点 | 时机 |
|-------|-----------|------|
| `plan` | {datasets, charts_plan, map_plan} | 规划后 |
| `dataset` | {datasetId, source, summary, rows} | 每次数据获取 |
| `chart` | {chartId, type, title, option} | 每个图表产出 |
| `map_layer` | {layerId, points, routes, areas, layerConfig} | 地图数据产出 |
| `narrative` | {intro, explanations:[{chartId,text}]} | 文本产出（最后） |
| `chart_update` | {chartId, option} | 外部 tick 刷新 |
| `map_update` | {layerId, ...} | 外部 tick 刷新 |
| `done` | {reportId, status} | 生成完成 |
| `error` | {message, stage} | 任一阶段失败 |

## 5. 外部数据 tick（实时刷新）

- 生成完成后，situation-service 可选地为带外部数据源的 reportId 启动一个 **tick 任务**（异步循环或事件订阅）。
- 每次有新数据：重算受影响图表的 option → 推送 `chart_update`；重算地图图层 → 推送 `map_update`。
- tick 频率由数据源适配器决定（Q-03）；前端也可主动 `POST /refresh/:reportId` 触发一次。
- tick 任务有 TTL（如 30 分钟无前端连接则停止），避免空跑。

## 6. 错误与降级

| 场景 | 处理 |
|------|------|
| LLM 配置缺失 | `load_llm_config` 兜底失败 → SSE `error` + `done(status=failed)` |
| 某数据工具超时 | 该工具返回失败，LLM 决定跳过/换源；不影响其他图表 |
| LLM 不返回 tool_calls 且非结束 | 最多重试 N 次，超限则按已产出部分 `done(status=partial)` |
| 模型不支持 function-calling | 自动降级 JSON 计划模式（§1.2） |

## 7. Prompt 设计要点（system prompt）

- 明确「先图表后文本」「文本是介绍+说明非结论」。
- 约束 `render_chart` 的 option 必须是合法 ECharts JSON、数据内联（不引用外部）。
- 约束 `write_narrative.explanations` 的 chartId 必须命中已产出的图表。
- 鼓励按问题选择合适图表类型（趋势用 line，占比用 pie，多维用 radar，分布用 scatter/heatmap）。
- 中文输出。

prompt 模板放 `agent/prompts.py`，可随业务调优，不影响契约。
