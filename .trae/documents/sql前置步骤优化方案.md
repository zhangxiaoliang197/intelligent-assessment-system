# SQL 生成前置步骤优化方案

## Context

指标分析路径在"生成 SQL 之前"的步骤（数据探查 → 数据集/指标检查 → 表选择 → 字段映射）过于粗糙，导致 LLM 拿到的上下文质量低，直接影响 SQL 生成准确率。本方案优化 4 个核心问题：表注释缺失、表数量硬限制、字段映射粗糙、指标联动信息未利用。

## 问题清单与修改方案

### 问题 1：表注释缺失（Java + Python）

**现状**：Java 端 `appendMetadataTables` 使用 JDBC `metadata.getTables()` 但未读取 REMARKS 列；Python 端 `fetch_database_tables` 默认只返回表名字符串列表。

#### 1.1 Java 端修改

**文件**：`java/admin-service/src/main/java/com/assessment/admin/controller/AdminController.java`
**位置**：`appendMetadataTables` 方法（L941-981）

在 `while (rs.next())` 循环内（L962 `String tableName = ...` 之后）增加：
```java
String tableComment = Objects.toString(rs.getString("REMARKS"), "");
```
在构造 `table` LinkedHashMap 时（L970-974）追加：
```java
table.put("tableComment", tableComment);
```

同时修改 `appendTablesViaSql`（L1048-1082，Oracle 兜底查询），在 SQL 中追加表注释查询，或在结果中设置 `tableComment` 为空串（保持结构一致）。

#### 1.2 Python 端修改

**文件**：`python/qa-service/agents/tools.py`
**位置**：`fetch_database_tables`（L158-191）

新增可选参数 `with_comments: bool = False`：
- `with_comments=False`（默认）：维持原行为返回 `list[str]`，向后兼容 4 个现有调用点
- `with_comments=True`：返回 `list[dict]`，含 `tableName` / `tableComment` / `schemaName` / `catalogName`

---

### 问题 2：表数量硬限制 + 中文分词失效

**现状**：`_pick_relevant_tables` 在两个文件中各有一份，用 `question.split()` 按空格分词（中文失效），且固定 `max_tables` 硬截断。

#### 修改方案（各自原地修改，不抽取共享文件）

**文件 1**：`python/qa-service/agents/indicator_query.py` L45-123
**文件 2**：`python/qa-service/agents/langgraph_workflow.py` L204-276

两处做相同逻辑的修改：

**a) 引入 2-gram 分词替代 `split()`**：
复制 `indicator-service/main.py:320-346` 的 `_normalize_name` / `_char_bigrams` / `_jaccard` 三个工具函数到各自文件顶部。中文按 2 字滑窗，英文按 2 字符滑窗，无需 jieba。

**b) 表注释纳入打分**：
- 调用方改用 `fetch_database_tables(db_id, with_comments=True)` 获取带注释的表列表
- 打分新增：表注释中包含问题 bigram → +15/词

**c) 动态阈值替代硬截断**：
- 取所有得分 > 0 的表，按得分降序排列
- 上限放宽到 `max_tables=12`（从 5/8 提升）
- 得分相同时优先非系统表（不以 `ass_`/`sys_`/`test_` 开头）
- 完全无匹配时保持原 fallback（取非系统表前 N 张）

**d) 移除 `indicator_query.py` 的 `_CN_EN_MAP`**（L53-76 医疗字典）：bigram 匹配 + 表注释已覆盖中文语义。

#### 调用点适配

`fetch_database_tables` 改为 `with_comments=True` 后，返回类型从 `list[str]` 变为 `list[dict]`，需适配以下位置：

| 文件 | 位置 | 适配内容 |
|------|------|---------|
| `indicator_query.py` | L167 `data_explore_node` | `all_tables` 改为 list[dict]，显示时用 `t["tableName"]` |
| `indicator_query.py` | L178-180 | `"\n".join(f"  • {t}" ...)` → 用 `t["tableName"]` |
| `indicator_query.py` | L243-249 `table_select_node` | `dataset_table_map` 的 key 仍为表名字符串，需用 `t["tableName"]` 比较 |
| `langgraph_workflow.py` | L644 `data_explore_node` | 同上 |
| `langgraph_workflow.py` | L664-665 | 显示表数时用 `len(all_tables)` 不变 |
| `langgraph_workflow.py` | L798 `table_select_node` | `_pick_relevant_tables` 内部适配 dict 输入 |

**注意**：`langgraph_workflow.py` 的 `dataset_check_node`（L739-742）在数据库未连接时用数据集表名回填 `database_tables`，该分支保持返回 `list[str]`。`_pick_relevant_tables` 需兼容 `list[str]` 和 `list[dict]` 两种输入。

---

### 问题 3：字段映射粗糙（替换硬编码字典）

**现状**：`build_field_hints` 用硬编码 `_CN2EN_MAP`（L341-405，医疗场景字典）做匹配，与项目实际场景不符。

**文件**：`python/qa-service/agents/indicator_query.py`
**位置**：`build_field_hints`（L322-441）

#### 修改方案

**a) 删除整个 `_CN2EN_MAP` 字典**（L341-405）

**b) 用 bigram Jaccard 相似度替代**：
对每个 `formula_word`（L410 的 `re.findall` 提取）：
1. 保留原有"精确命中 col_index"（L412-413）作为高分快路径
2. 精确未命中时，计算 `fw_bigrams = _char_bigrams(_normalize_name(fw))`
3. 遍历 `col_index` 关键词，计算 Jaccard 相似度
4. 取 Jaccard ≥ 0.3 的列，按相似度降序取 top-2

**c) 复用问题 2 引入的 `_char_bigrams` / `_jaccard` / `_normalize_name`**，避免重复代码。

**影响面**：仅 `text_to_sql.py:203` 消费 `_field_hints`，无测试依赖内部结构。

---

### 问题 4：指标联动信息未利用（最高杠杆）

**现状**：`/indicator/list` 返回的 Indicator 对象**已包含** `fieldMapping` 和 `calculationMethod` 字段，Python 端 `fetch_indicators_for_datasets` 已拿到，但 `build_field_hints` 和 text_to_sql prompt 完全没使用。

#### 4.1 build_field_hints 优先使用 admin 字段映射

**文件**：`python/qa-service/agents/indicator_query.py`
**位置**：`build_field_hints`（L322-441），`for ind in merged_indicators` 循环内

在 `hints = []` 之后（L411 附近）插入优先级逻辑：
1. **优先级 1**：解析 `ind.get("fieldMapping")`（JSON 字符串），映射格式为 `{"中文计算项": "表名.字段名"}`，解析成功则直接生成 hints 并标注 `[admin配置]`，跳过 bigram 兜底
2. **优先级 2**：bigram 模糊匹配（问题 3 的逻辑）
3. 新增 `e["_calc_method"]` 字段存储 `calculationMethod`（截断 500 字符）

#### 4.2 text_to_sql.py 消费 calculationMethod

**文件**：`python/qa-service/agents/text_to_sql.py`

**a) prompt 构建**（L200-210）：在 `if ind.get("description"):` 之后增加：
```python
if ind.get("_calc_method"):
    ic += f"\n  计算方法: {ind['_calc_method']}"
```

**b) system prompt 规则**（L53-114 的 `TEXT_TO_SQL_SYSTEM_PROMPT`）：在规则 8-10 附近追加：
> 如果指标定义中提供了"字段映射"（标 `[admin配置]`）或"计算方法"，必须严格遵守该映射，不要自行猜测字段。

---

### 问题 5：indicator-service 传递的指标缺少联动信息

**现状**：`_annotate_indicators` 只给 LLM 生成的指标打 `type` 标签，不合并 admin 指标的 `fieldMapping`/`calculationMethod`。

**文件**：`python/indicator-service/main.py`
**位置**：`_annotate_indicators`（L495-529）

在 L511-514 的 `admin-db` 匹配分支中，合并 admin 指标的字段：
```python
matched = _match_admin_indicator(name, admin_indicators)
if matched:
    ind["type"] = "admin-db"
    if matched.get("fieldMapping"):
        ind["fieldMapping"] = matched["fieldMapping"]
    if matched.get("calculationMethod"):
        ind["calculationMethod"] = matched["calculationMethod"]
    if matched.get("datasetId"):
        ind["datasetId"] = matched["datasetId"]
    continue
```

**向后兼容**：LLM 生成的指标原只有 name/definition/formula/criteria/weight，新增字段是加法式扩展，前端指标卡片不消费这些字段。

---

## 影响面汇总

| 修改文件 | 修改内容 | 影响范围 |
|---------|---------|---------|
| `AdminController.java` L941-981 | `appendMetadataTables` 读 REMARKS | Java 端需重新编译；前端无需改（向后兼容） |
| `AdminController.java` L1048-1082 | `appendTablesViaSql` 保持结构一致 | Oracle 兜底路径 |
| `tools.py` L158-191 | `fetch_database_tables` 加 `with_comments` 参数 | 默认参数向后兼容；4 个现有调用点零改动 |
| `indicator_query.py` L45-123 | `_pick_relevant_tables` 改 bigram + 动态阈值 | 删除 `_CN_EN_MAP`；调用点适配 dict 输入 |
| `indicator_query.py` L322-441 | `build_field_hints` 用 fieldMapping + bigram | 删除 `_CN2EN_MAP`；仅 text_to_sql.py 消费 |
| `langgraph_workflow.py` L204-276 | `_pick_relevant_tables` 同步修改 | 与 indicator_query.py 保持一致 |
| `langgraph_workflow.py` L644, L798 | 调用点适配 dict 输入 | data_explore + table_select 节点 |
| `text_to_sql.py` L200-210 | prompt 消费 `_calc_method` | 新增可选段，不破坏现有逻辑 |
| `text_to_sql.py` L53-114 | system prompt 加规则 | 强化 LLM 对 admin 配置的遵从 |
| `indicator-service/main.py` L495-529 | `_annotate_indicators` 合并 admin 字段 | 加法式扩展，向后兼容 |

---

## 验证方案

### 单元测试
1. **表选择**：构造 12 张中英混合表名 + 注释，验证中文问题能选出相关表且不超过 max_tables
2. **字段映射**：构造 schema 列 `[{"columnName":"hit_count","comment":"命中次数"}]` + formula="命中次数/攻击次数"，验证 `_field_hints` 含正确映射
3. **fieldMapping 优先**：构造含 `fieldMapping='{"命中次数":"t.hit_count"}'` 的指标，验证 hints 含 `[admin配置]` 标签
4. **指标合并**：构造 LLM 指标 + admin 指标（同名），验证 `_annotate_indicators` 合并了 fieldMapping

### 集成测试
1. Java 编译后 `GET /api/admin/database/{id}/tables` 验证返回含 `tableComment`
2. 跑完整指标分析流程，检查 `qa-service/logs/sql_gen.log`：
   - prompt 的"指标定义"段含"字段映射提示 [admin配置]"和"计算方法"行
   - 生成的 SQL 使用了映射指定的字段
3. 对 10+ 张表的真实库跑指标查询，验证选表不再漏掉相关表

### 回归保护
- 验证 `fetch_database_tables` 默认参数仍返回 `list[str]`
- 验证无 fieldMapping 的指标走 bigram 兜底路径
- 验证前端指标卡片渲染不受影响
