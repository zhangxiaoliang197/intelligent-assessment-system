# 指标分析后端优化方案（WS-6）

> 目标：围绕第二阶段"查询功能"做一次重新设计，而不是在现有链路上继续打补丁。
> 原则：**配置优先、运行期确定化**。大模型只做"提建议"和"解释结果"这两件窄事，
> 凡是能提前确定的关系（表、字段、公式、连接键、聚合粒度）全部在配置期落库，
> 运行期用确定性代码编译与执行。

---

## 一、现状诊断（对应问题 1–4）

### 问题 1：指标与表的关系不可靠

当前链路（`qa-service/agents/indicator_query.py`）在运行期用启发式打分选表：

- 表名/注释与问题、分析计划的 2-gram Jaccard 相似度；
- 分析计划中"表 xxx"文本的 +200 强信号；
- 数据集 → 单表关联兜底（`table_select_node` 中 `dataset_table_map`）。

根因：

1. 管理端 `ass_indicator` 只有一个 `dataset_id`（单表），无法表达"公式需要 A 表的数据、
   又要按 B 表分组、还要关联 C 表"这类多表结构。
2. 运行期靠字符串相似度猜表，表多、注释不全时必然出错；选错表后 SQL 生成、充分性判定
   全部跟着错。

### 问题 2：公式参数与列名不对应

当前"字段映射"是三层拼凑：

- 管理端 UI 生成的是 `{columnName: weight}`（按"映射权重"勾选字段），
  而运行期 `build_field_hints` 期望的是 `{公式中文词: 表名.字段名}`，
  **配置层与消费层语义不一致**；
- 未命中时用 bigram 相似度猜列，再兜底让 LLM 批量猜（`_llm_match_formula_words`）；
- 每指标只保留前 5 条 hint，复杂公式的信息被截断；
- 公式里"某物品的行数"这类**跨表行数**（如 `COUNT(orders WHERE item_type='A')`）
  没有任何建模载体，只能靠 LLM 现场生成 SQL。

根因：**没有"指标规格（Indicator Spec）"这个中间层**。公式停留在自然语言，
列绑定停留在权重列表，两者之间没有可编译、可校验的桥。

### 问题 3：充分性判定鸡肋

现状（`qa-service/agents/suffficiency.py`）是**查询之后的列名匹配后验判定**：

- 拿指标名 + fieldMapping + 公式词去匹配结果列，匹配不到就标"无数据"；
- 单条 SQL 通常把多个指标算在同一结果集里，列名匹配对不上时，
  判定结果与实际可算性完全脱节；
- 产出"覆盖率 x/y"这类技术报告，用户不知道**下一步该干什么**；
- 前端只在执行面板的 thinking 区展示，主对话区只有一个 LLM 复述的结论。

根因：充分性被当成了"运行期检查"，但真正该回答的问题是
**"这个指标在配置期是否可算"**（绑定齐不齐、能不能 dry-run、数据量够不够）。

### 问题 4：大模型不强时如何兜住整个链路

当前架构把最难的活全部压在运行期 LLM 上：选表、中英列映射、JOIN 推断、
多表聚合、SQL 重试修正，一次 prompt 全部让模型现场完成。模型弱时必然出错，
且错误不可复现、不可审计、不可离线修正。

---

## 二、设计目标与原则

1. **配置优先（Configuration-first）**：指标与表的绑定、公式项与列的映射、
   表间连接键、聚合粒度，全部在管理端配置并校验，落库为"可编译规格"。
2. **运行期确定化（Deterministic runtime）**：查询期由编译器把规格翻译成 SQL，
   不再让 LLM 自由发挥；LLM 只做参数抽取与结果解读两类窄任务。
3. **LLM 提建议、人来确认（Human-in-the-loop）**：配置期用 LLM 辅助生成绑定建议，
   但必须 dry-run 通过并由管理员确认后才生效；确认结果回写配置，形成持续沉淀。
4. **充分性前移（Readiness before query）**：把"充分性判定"改为查询前的
   **指标就绪度检查（Preflight Readiness）**，给出可执行的缺口清单。

---

## 三、核心设计：指标规格（Indicator Spec）

### 3.1 数据模型

`ass_indicator` 表扩展（兼容旧字段，新增 JSON 列 `indicator_spec`）：

```json
{
  "version": 1,
  "sourceTables": [
    {"alias": "o", "tableName": "orders", "role": "fact"},
    {"alias": "i", "tableName": "order_items", "role": "detail"},
    {"alias": "p", "tableName": "products", "role": "dimension"}
  ],
  "keyMappings": [
    {"left": "o.order_id", "right": "i.order_id"},
    {"left": "i.product_id", "right": "p.product_id"}
  ],
  "dimensions": [
    {"alias": "d", "table": "o", "column": "order_date", "type": "time"},
    {"alias": "g", "table": "p", "column": "item_type", "type": "category"}
  ],
  "parameters": [
    {"name": "物品类别", "term": "某物品", "type": "filter",
     "target": {"table": "p", "column": "item_type"}}
  ],
  "bindings": [
    {"term": "订单数", "kind": "agg", "agg": "COUNT", "table": "o", "column": "order_id"},
    {"term": "商品件数", "kind": "agg", "agg": "COUNT", "table": "i", "column": "item_id"},
    {"term": "销售额", "kind": "agg", "agg": "SUM", "table": "i", "column": "price"},
    {"term": "目标物品订单数", "kind": "scoped",
     "base": {"term": "订单数", "table": "o", "column": "order_id"},
     "scope": {"table": "p", "column": "item_type", "operator": "=", "value": "=参数(物品类别)"}}
  ],
  "grain": {"groupBy": ["d", "g"], "distinct": false},
  "output": {"alias": "avg_order_value", "label": "客单价"}
}
```

要点：

- **term** 与指标公式中的自然语言词一一对应，编译器负责把公式词解析为绑定；
- **kind=scoped** 表达"某物品的行数"这类跨表过滤计数；
- **keyMappings** 是唯一允许的 JOIN 依据，由配置期人肉/半自动确认；
- **grain** 决定聚合粒度（按天/按类别/按明细），与参数、维度共同决定分组。

### 3.2 语义目录（Semantic Catalog）

新增管理端实体 `ass_field_synonym`（或复用 `ass_field_annotation` 扩展列），
收录**业务概念 → 物理列**的别名与同义词：

```text
概念"命中次数" → hit_count（表 weapon_hit_record）
概念"战损率"  → damaged_ratio / 由 damaged_count / total_count 计算
概念"物品"    → item_type / category（表 products）
```

配置期：

- 自动扫描表结构 + 字段标注，构建目录索引（含同义词、大小写/全半角归一化）；
- 提供"概念 → 列"搜索接口，管理员或 LLM 建议都能走同一入口；
- 目录增量维护：新表/新标注入库后自动索引，供编译器确定性解析。

运行期：

- 编译器只查目录，不做字符串相似度猜测；
- 目录中查不到的 term 明确报"未绑定"，进入缺口清单，而不是让 LLM 猜。

---

## 四、查询管线重构

### 4.1 新管线（替换 `run_indicator_query` 主流程）

```
用户问题 + 已确认指标
  → 1. 指标就绪度检查（Preflight）        ← 替代"充分性判定"后置位置
  → 2. 语义目录解析 + 规格加载
  → 3. 查询计划编译（确定性）
      ├─ 绑定完备 → 直接生成 SQL 计划（含 JOIN / GROUP BY / 参数替换）
      └─ 有缺口   → 明确列出缺口 + 可选项，不再静默跳过
  → 4. 计划执行 + 结果校验（行数/列数/空值）
  → 5. 结果解读（LLM 窄任务：只解读，不编造）
```

### 4.2 查询计划（Query Plan）成为一等输出

每次查询先输出一个结构化计划，前端可渲染，用户可检查：

```json
{
  "indicators": [
    {"name": "客单价", "status": "ready",
     "tables": ["orders", "order_items"],
     "formula": "销售额 / 订单数",
     "bindings": {"销售额": "SUM(order_items.price)", "订单数": "COUNT(DISTINCT orders.order_id)"}}
  ],
  "joins": ["orders.order_id = order_items.order_id"],
  "parameters": {"物品类别": "A类"},
  "gaps": []
}
```

### 4.3 LLM 的边界（弱模型也可用）

| 环节 | 是否用 LLM | 说明 |
|------|-----------|------|
| 表选择 / 列映射 / JOIN | 否 | 配置期确定，运行期查目录与规格 |
| 公式编译 | 否 | 编译器 + dry-run 校验 |
| 参数抽取（问题 → 维度/过滤值） | 是（窄任务） | 只输出参数 JSON，代码校验合法性 |
| 缺口补建议 | 是（提建议） | 建议需人工确认 + dry-run，成功后回写配置 |
| 结果解读 | 是（窄任务） | 只解读查询结果，禁编造 |
| SQL 重试修正 | 否（新方案） | 执行失败 → 报错 + 定位到配置/数据问题，而不是反复重试 |

### 4.4 多粒度/多语句问题

- 同一指标集的粒度一致时，编译为**单条 SQL**；
- 粒度不一致（如"逐日趋势 + 汇总均值"），按粒度分组生成**多条 SQL**，
  每条对应一个 QueryPlan 子计划，结果按指标名归并；
- 禁止"一条 SQL 里塞所有指标"的现状，避免结果列名与指标对应错位。

### 4.5 未配置指标（知识库 / LLM 生成）的处理路径

这是本方案必须明确回答的边界：**没有管理端规格的指标，确定性编译器没有绑定可编译，
"正常计算"的承诺必须分场景定义，不能假装能算。** 分三层：

1. **知识库指标**：知识库中的指标定义若含"公式 = 表.列"或明确的业务词定义，
   配置向导可一键导入为"待确认规格"（LLM 建议 + dry-run + 人工确认），
   确认后与 admin 配置指标完全同权，走确定性编译路径。
2. **LLM 生成指标（本次会话）**：运行期走**受限的即时绑定（On-the-fly Binding）**流程：
   - LLM 只做一件事：把公式 term 与语义目录/当前表结构的候选列配对，输出候选 JSON；
   - 编译器组装候选 → 生成 SQL 计划 → **先 dry-run 再执行**；
   - 关键差异：**不允许 LLM 直接产出整条 SQL**，且绑定结果必须经过
     "列存在性 + 类型 + dry-run 通过"三道校验；
   - 即时绑定结果在用户确认后回写语义目录与指标规格，下次即确定性路径。
3. **绑定失败 / 用户不确认**：进入"未就绪"缺口清单，明确告知缺什么、
   怎么补（补绑定 / 查知识库 / 请管理员配置），**不静默跳过，不让 LLM 猜着算**。

诚实结论：对未配置指标，"能正常算"成立的前提是**绑定被确认**。
本方案不承诺无绑定也能算对——那正是当前架构失败的原因；
而是把"算不准"变成"先确认、可回写、逐步沉淀为配置"。

---

## 五、充分性判定 → 指标就绪度检查（Preflight）

### 5.1 判定时机前移

配置期（管理端）：

- 绑定完备性：公式每个 term 都有 binding；
- 连接键校验：keyMappings 引用真实存在的列；
- dry-run：用 `LIMIT 1` 试执行，确认语法与权限；
- 数据量快照：记录每张来源表的行数，供趋势/对比类指标判断样本量。

运行期（查询前）：

- 对每个指标输出 `ready / missing_binding / no_join / empty_source`；
- 数据量不足（趋势 < 3 个时间点等）在查询前给出提示，仍允许用户强制查询。

### 5.2 用户可执行的结果

查询结束后，如果某指标无数据，给出**具体原因 + 下一步动作**：

- 绑定缺失 → "指标 X 的'某物品'未绑定列，请到管理端补齐或让我推荐映射"；
- 数据为空 → "表 orders 在所选时间范围内无数据，可尝试扩大时间范围"；
- 数据不足 → "仅 1 个时间点，不足以判断趋势，建议按周聚合或补充数据"。

前端把 Preflight 报告和 Query Plan 渲染为独立面板，替代埋在 thinking 区里的技术报告。

---

## 六、LLM 辅助配置（弱模型可用性设计）

### 6.1 配置向导（管理端新增）

1. 管理员输入公式（自然语言）：`客单价 = 销售额 / 订单数`；
2. 系统解析公式 term（代码层分词，不依赖 LLM）；
3. LLM 基于语义目录**建议**绑定（候选 top-3）；
4. 管理员选择/修正 → 编译器 dry-run → 保存；
5. dry-run 失败或绑定不齐 → 指标状态标 `未就绪`，不进入运行期查询。

### 6.2 反馈闭环

- 运行期"缺口清单"里可一键发起"LLM 推荐映射"；
- 管理员确认过的映射回写语义目录与指标规格；
- 每次确认都是一次训练数据沉淀，目录越用越准，运行期 LLM 依赖越来越小。

---

## 七、落地步骤（分阶段，每阶段可交付可验证）

### 阶段 A：配置层改造（管理端 + Admin Service）

- `ass_indicator` 新增 `indicator_spec` JSON 列 + `bind_status` 状态列；
- 新增 `ass_field_synonym` 语义目录表与索引构建；
- `ass_dataset` 扩展 `key_mappings`（表间连接键）配置；
- Admin 接口：`POST /indicator/{id}/spec`、`POST /indicator/{id}/dry-run`、
  `GET /catalog/search?term=`；
- 前端：指标详情页从"权重勾选"改为**公式项绑定编辑器**（term → 表.列 / 聚合 / 过滤），
  显示绑定状态与 dry-run 结果。

### 阶段 B：查询期确定化（QA Service + Indicator Service）

- 新增 `indicator_compiler.py`：规格 → SQL 表达式（确定性）；
- 新增 `query_planner.py`：多表 JOIN / 分组 / 参数替换 / 多粒度拆 SQL；
- 改造 `indicator_query.py`：表选择改为目录 + 规格驱动，删除 bigram 打分主路径；
- 新增 Preflight 就绪度检查，替代 `suffficiency.py` 的后验判定主逻辑；
- 新增受限即时绑定（On-the-fly Binding）流程：LLM 只出候选映射，
  编译器组装 + dry-run + 三道校验，用户确认后回写配置；
- 知识库指标一键导入为待确认规格；
- 无规格且未确认的指标标记"未就绪"，进缺口清单，不走原自由生成 fallback。

### 阶段 C：LLM 辅助与闭环

- 配置向导接入 LLM 绑定建议（候选 + dry-run + 人工确认）；
- 运行期缺口清单 → 一键推荐映射 → 回写配置；
- 参数抽取：问题 → 维度/过滤值 JSON（窄任务 + 代码校验）。

### 阶段 D：体验层

- 前端新增 Query Plan / Preflight 面板（指标状态、涉及表、公式、缺口、建议动作）；
- 无数据/不足场景改为"原因 + 下一步"卡片；
- 指标来源与可算性状态在指标卡片上一目了然。

### 验收口径

- 同一指标查询两次结果一致（确定性）；
- 配置齐备的指标 100% 走编译路径，不经过运行期选表/猜列；
- 配置缺口的指标在查询前给出明确缺口清单，不静默跳过；
- 单条 SQL 结果列与指标一一对应（sufficiency 不再依赖列名猜匹配）；
- 手工构造 20 条跨表/行数类指标用例，dry-run + 查询通过率 ≥ 90%。

---

## 八、涉及模块清单

| 模块 | 文件 | 改动 |
|------|------|------|
| Admin Service | `java/.../model/Indicator.java` | 新增 `indicator_spec`、`bind_status` |
| Admin Service | `java/.../model/Dataset.java` | 新增 `key_mappings` |
| Admin Service | `java/.../model/FieldSynonym.java`（新） | 语义目录实体 |
| Admin Service | `java/.../controller/AdminController.java` | spec/dry-run/catalog 接口 |
| Admin Service | `java/.../service/SchemaService.java` | 目录索引、列解析、dry-run |
| Frontend | `frontend/src/pages/AdminSystem.vue` | 公式项绑定编辑器 |
| QA Service | `agents/indicator_query.py` | 编译器/规划器接入，删选表打分主路径 |
| QA Service | `agents/indicator_compiler.py`（新） | 规格 → SQL |
| QA Service | `agents/query_planner.py`（新） | 多表/多粒度计划 |
| QA Service | `agents/suffficiency.py` | 改为 Preflight 就绪度检查 |
| QA Service | `agents/text_to_sql.py` | 仅保留参数抽取/计划兜底，去掉自由生成主路径 |
| Indicator Service | `python/indicator-service/main.py` | 透传 Query Plan/Preflight 到前端 |
| Frontend | `frontend/src/pages/IndicatorAnalysis.vue` | Query Plan/Preflight 面板 |

---

## 九、风险与对策

| 风险 | 对策 |
|------|------|
| 旧配置迁移成本 | 保留旧字段兼容；有 spec 的指标立即走确定性路径，无 spec 的走即时绑定或"未就绪"缺口清单，并提示一键升级 |
| 即时绑定仍可能出错 | 三道校验（列存在、类型、dry-run）+ 人工确认兜底；确认结果回写，错误绑定可从目录移除并记录，逐步收敛 |
| 多表模型复杂 | 先支持 2–3 表 + 1 个维度/参数，按真实用例逐步扩展 DSL |
| LLM 建议错误 | 建议必过 dry-run + 人工确认；错误映射可从目录移除并记录 |
| 参数抽取失败 | 参数未解析时查询前交互式追问，不让 LLM 猜值 |

---

## 十、总结

这套方案把"选表、映射、JOIN、聚合、充分性"五件事从运行期 LLM 自由发挥，
迁移到**配置期人机协同的确定性规格**上。大模型只保留两个窄任务
（参数抽取、结果解读）和一个提建议角色，模型强弱都不影响核心查询正确性；
查询错误从"随机失败"变成"可定位、可修正、可沉淀"。

---

## 十一、实施进展（2026-08-12）

### 已完成

**阶段 A — 管理端配置层（Java Admin Service，已编译通过）**

- `Indicator` 新增 `indicator_spec`（JSON 规格）与 `bind_status`（ready / not_ready）；
- `Dataset` 新增 `key_mappings`（表间连接键）；
- 新增 `FieldSynonym` 语义目录实体与索引构建（从字段标注自动重建）；
- 新增接口：
  - `POST /api/admin/indicator/{id}/spec` — 校验并保存规格（回写绑定状态）
  - `POST /api/admin/indicator/spec/validate` — 只校验不落库
  - `POST /api/admin/indicator/{id}/dry-run` — 来源表只读试查询
  - `POST /api/admin/catalog/rebuild` / `GET /api/admin/catalog/search`
  - `GET /api/admin/catalog/database` / `POST /api/admin/catalog/synonym`
  - `POST /api/admin/dataset/{id}/key-mappings`

**阶段 B — 查询期确定化（Python QA Service）**

- 新增 `agents/indicator_engine.py`：规格编译器 + 查询规划器 + Preflight 就绪度检查；
  - JOIN 只认 keyMappings；绑定列/连接键必须存在于 schema 目录，否则编译失败并报缺口；
  - scoped 绑定支持"某物品的行数"类跨表过滤计数；
  - 粒度不一致自动拆多条 SQL，多指标同粒度合并，游离表自动拆分防笛卡尔积；
- `indicator_query.py` 接入确定性编译路径：
  - 指标携带 `indicatorSpec` 时优先走 Preflight → 编译 → 执行（不经 LLM 生成 SQL）；
  - 规格引用的表即使启发式选表未命中也会被强制读取；
  - 未配置规格的指标仍走原 fallback（标记未就绪，不阻塞）；
- 测试：`test_indicator_engine.py`（5 项）+ `test_indicator_compiled_flow.py`
  （端到端编译路径）全部通过。

### 本轮新增（2026-08-12 第二轮）

- **LLM 辅助配置**：`POST /evaluation/indicator-spec/suggest` —
  基于公式分词 + 语义目录由 LLM 生成绑定建议（JSON 候选，需校验/dry-run/人工确认）；
- **参数抽取窄任务**：编译路径查询前用 LLM 从问题抽取规格参数值，
  失败时问题文本关键词兜底；
- **前端 AdminSystem.vue**：新增「配置规格」按钮与规格配置对话框
  （规格 JSON 编辑、语义目录表结构预览、重建目录索引、校验、dry-run、LLM 建议绑定、保存回写 bind_status）；
- **前端 IndicatorAnalysis.vue**：新增「查询计划 / 指标就绪度」面板
  （Preflight 逐指标状态表 + 每条确定性 SQL 计划 + 未就绪指标列表，持久化到会话）；
- 前端类型检查：新增代码无 TS 错误（GeoMap/SituationMap 报错为仓库既有问题）。

### 待办收尾（2026-08-12 第四轮，已完成）

- **知识库指标一键导入**：`POST /evaluation/indicator-spec/import-from-knowledge`
  从知识库文档解析「指标名 = 公式」候选，逐条由 LLM 生成待确认规格；
  管理端「指标管理 → 从知识库导入」选择文档与目标数据源，解析后逐条人工核对并保存为新指标。
- **运行期即时绑定交互确认**：`POST /evaluation/indicator-spec/runtime-bind`
  对未就绪指标执行「LLM 建议绑定 → 代码编译 SQL 计划 → 来源表只读 dry-run」三道校验
  （多来源表无 keyMappings 时拒绝笛卡尔积）；指标分析页未就绪列表新增「即时绑定」，
  人工确认后保存规格（已存在指标回写，未存在自动新建），下次查询即走确定性编译路径。
- **语义目录可视化维护页**：管理端新增「语义目录」页签，支持同义词搜索、新增、编辑、删除
  （`GET /catalog/synonyms` / `POST /catalog/synonym` / `DELETE /catalog/synonym/{id}`）与一键重建索引。

### 现存指标迁移（2026-08-12 第三轮，已完成）

**迁移结果：11/11 指标全部完成 Indicator Spec 适配，且全部在实库执行通过。**

迁移脚本：`scripts/migrate_indicator_specs.py`（预演/写入双模式），
执行验证：`scripts/verify_indicator_specs.py`。

| 指标 | 数据源 | 状态 | 实库结果示例 |
|------|--------|------|--------------|
| 客单价 | Olist order_payment | ready | 160.99 |
| 平均评分 | Olist order_review | ready | 4.09 |
| 平均配送天数 | Olist orders | ready | 12.50 天 |
| GMV | Olist order_item | ready | 1584.8 万 |
| 复购率 | Olist orders + customer | ready | 3.12% |
| 基本每股收益 | 天池 income statement | ready | 22.00 |
| 毛利率 | 天池 income statement | ready | 5.42% |
| 净利率 | 天池 income statement | ready | 5.50% |
| 营业利润率 | 天池 income statement | ready | 6.45% |
| 实际税率 | 天池 income statement | ready | 21.30% |
| 市值 | 天池 market data | ready | 5.77e12 |

本轮引擎新增能力（复购率等跨表/按客户聚合指标所需）：

- `preAggregations`（CTE 预聚合）：支持"orders JOIN customer → 按客户唯一ID聚合订单数"，
  主查询以 CTE 为数据源；
- `kind: "expr"` 表达式绑定（白名单校验：仅关键字/函数/别名.列/数字/运算符），
  支持 `SUM(A)/SUM(B)*100` 与 `COUNT(CASE WHEN ...)` 类公式；
- 达梦/Oracle 含空格表名（`"income statement"`）双引号标识符支持；
- MySQL 聚合函数不引号化，仅表名/别名按方言引用。

**数据缺口与说明（用户要求指出）：**

1. **字段标注不完整**：`order_id`、`customer_id`、`customer_unique_id`、`product_id`、
   `TICKER_SYMBOL` 等关键列未做字段标注（语义目录重建时缺失），
   本轮已补齐 20 条关键列同义词（catalog/synonym），目录总计 248 条；
2. **两张表无任何字段标注**：`category_translation`、`seller`（列级标注为空），
   若后续指标涉及这两张表，LLM 建议/搜索会缺少上下文；
3. **复购率数据口径**：按 `customer_unique_id` 去重统计（≥2 单客户数/总客户数），
   实库当前约 3.12%，符合"复购客户数/总客户数"定义；
4. 天池财务指标未带时间/公司维度过滤（如 `END_DATE`、`TICKER_SYMBOL` 维度），
   当前返回全表聚合值；如需按报告期/个股查询，需在规格 dimensions 中补充配置。
