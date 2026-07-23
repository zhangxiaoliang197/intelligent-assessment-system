"""
多智能体评估系统的共享状态定义。

============================================================
模块在系统架构中的位置
============================================================

本模块位于 qa-service 的多智能体框架层（agents/），是整个评估工作流的
"状态容器"（State Container）。它定义了一个 @dataclass 类 EvaluationState，
作为 LangGraph StateGraph 中所有节点之间传递共享数据的唯一载体。

============================================================
在 LangGraph 工作流中的角色
============================================================

LangGraph 的工作流由多个节点（Node）通过边（Edge）连接而成，每个节点
接收 state 作为输入，返回更新后的 state（或部分更新）。EvaluationState
就是 StateGraph 的类型参数：

    graph = StateGraph(EvaluationState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("sql_generator", sql_generator_node)
    ...

各节点按阶段读写 state 中的对应字段：
  orchestrator_node    → 写 intent / entities / analysis_plan
  discovery_node       → 写 database_tables / table_schemas / indicator_defs
  sql_generator_node   → 写 generated_sql / sql_explanation / sql_valid
  executor_node        → 写 raw_results / execution_error
  analyst_node         → 写 final_answer / report_sections
  chart_agent_node     → 写 need_chart / chart_config

============================================================
设计原则
============================================================
1. 单一数据源：所有节点共享同一个 state 实例，避免参数在多函数间传递
2. 字段按阶段分区：用注释明确划分输入/编排/发现/SQL/执行/回答/图表等阶段
3. 丰富默认值：所有非必填字段都有合理的默认值（空字符串/空列表/False）
4. 步骤追踪：steps 字段记录工作流执行轨迹，用于前端流式展示进度
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class EvaluationState:
    """评估工作流的完整状态容器。

    该数据类承载从用户提问到最终回答的全部中间数据。每个字段对应
    工作流中某个节点的输入或输出，由 LangGraph 自动在各节点间传递。

    字段按工作流阶段组织，共分为 8 个逻辑区块：
    1. 输入阶段       — 用户原始输入和补充上下文
    2. 编排阶段       — 意图识别、实体提取、分析计划
    3. 数据源发现阶段 — 从数据库动态读取元数据
    4. SQL 生成阶段   — LLM 生成的 SQL 及校验信息
    5. SQL 执行阶段   — 查询结果和错误信息
    6. 分析回答阶段   — 最终回答和报告段落
    7. 图表阶段       — 可视化配置
    8. 追踪与错误     — 执行步骤记录、异常信息
    """

    # ============================================================
    # 第一阶段：输入 — 用户原始提问和辅助上下文
    # ============================================================

    # 用户在对话界面输入的自然语言问题
    question: str

    # 会话 ID，用于关联多轮对话记录；新建会话时为 None
    session_id: Optional[str] = None

    # 用户在前端选择的数据源 ID（对应 admin-service 中的 database 配置记录）
    # 为空字符串表示用户尚未选择数据源
    database_id: str = ""

    # 数据源名称（如 "作战数据库"），用于前端展示和 Prompt 上下文
    database_name: str = ""

    # 数据库类型（MySQL / PostgreSQL / Oracle / SQL Server / 达梦数据库V8.1）
    # 用于 text-to-sql 告诉 LLM 生成对应方言的 SQL
    database_type: str = ""

    # 用户关联的数据集 ID 列表（数据集是表 + 业务标注的组合）
    # 用于提供额外的表结构信息和业务上下文
    dataset_ids: List[str] = field(default_factory=list)

    # 用户关联的指标 ID 列表（指标是预定义的计算规则，如命中率、摧毁率）
    # 用于 LLM 生成包含聚合逻辑的 SQL
    indicator_ids: List[str] = field(default_factory=list)

    # ============================================================
    # 第二阶段：编排 — Orchestrator Agent 的输出
    # ============================================================

    # 用户意图分类结果，取值：data_query / combat_effectiveness / air_superiority / general_analysis
    intent: str = ""

    # 从用户问题中提取的实体信息（过滤条件、时间范围、区域名称等）
    # 示例：{"区域": "东海", "时间范围": "2024年", "装备类型": "战斗机"}
    entities: Dict[str, Any] = field(default_factory=dict)

    # 编排智能体制定的分析步骤计划（自然语言描述的执行计划）
    analysis_plan: str = ""

    # ============================================================
    # 第三阶段：数据源发现 — 从数据库动态读取元数据
    # ============================================================

    # 目标数据库中包含的所有表名（通过 information_schema 实时查询）
    database_tables: List[str] = field(default_factory=list)

    # 目标表的完整结构信息列表，每个元素包含 tableName / columns 等字段
    # 结构来源优先级：数据集标注 > information_schema 直接查询
    table_schemas: List[Dict] = field(default_factory=list)

    # 与目标数据集关联的指标定义列表
    indicator_defs: List[Dict] = field(default_factory=list)

    # ============================================================
    # 第四阶段：SQL 生成 — SQL Agent 的输出
    # ============================================================

    # LLM 生成的 SQL 查询语句（仅允许 SELECT 或 WITH 开头）
    generated_sql: str = ""

    # SQL 语句的通俗解释（用于前端展示，帮助用户理解查询逻辑）
    sql_explanation: str = ""

    # SQL 安全校验是否通过（校验规则包括：只允许 SELECT、无 DROP/ALTER 等危险操作）
    sql_valid: bool = False

    # SQL 生成失败时的重试次数（最多重试 2 次，超过则降级为 general_analysis）
    sql_retry_count: int = 0

    # 上一次 SQL 执行的 MySQL 错误信息（用于执行重试时的上下文注入）
    # 为空字符串表示无历史错误；非空时 run_text_to_sql 会将其加入 prompt
    previous_error: str = ""

    # ============================================================
    # 第五阶段：SQL 执行 — 在目标数据库上实际执行 SQL
    # ============================================================

    # SQL 执行返回的原始结果数据（rows 列表，每个元素为一行数据的字典）
    raw_results: List[Dict] = field(default_factory=list)

    # SQL 执行过程中发生的错误信息（成功时为 None）
    execution_error: Optional[str] = None

    # ============================================================
    # 第六阶段：分析回答 — Analyst Agent 的输出
    # ============================================================

    # 最终生成的自然语言回答（含 2-3 条数据分析建议）
    final_answer: str = ""

    # 报告各段落内容，key 为段落标题，value 为段落正文
    # 用于 combat_effectiveness 和 air_superiority 的多维度汇总报告
    report_sections: Dict[str, str] = field(default_factory=dict)

    # ============================================================
    # 第七阶段：图表 — Chart Agent 的输出
    # ============================================================

    # 是否需要生成图表（由 Orchestrator 判断，或数据量适中时自动触发）
    need_chart: bool = False

    # ECharts 图表配置字典，包含 chartType / xField / yField / title 等字段
    chart_config: Dict[str, Any] = field(default_factory=dict)

    # ============================================================
    # 第八阶段：追踪与错误 — 工作流执行监控
    # ============================================================

    # 执行步骤列表，每个元素为一个步骤记录字典
    # 字典结构：{step, description, status, detail, thinking, subStep, progress}
    # 用于前端流式展示工作流进度（如 "第 1 步：意图识别 → 已完成"）
    steps: List[Dict[str, Any]] = field(default_factory=list)

    # 工作流级别的错误信息（节点执行异常时设置，成功时为 None）
    error: Optional[str] = None

    # ============================================================
    # 方法：步骤追踪
    # ============================================================

    def add_step(self, step_num: int, description: str,
                 status: str = "pending", detail: str = "",
                 thinking: str = "", sub_step: str = ""):
        """向步骤列表中添加一个新的执行步骤记录。

        用于在工作流各节点执行前后记录状态，实现前端流式进度展示。
        每个步骤包含进度百分比：pending=0%，in_progress=50%，completed=100%。

        Args:
            step_num:    步骤序号（从 1 开始）
            description: 步骤描述文本（如 "意图识别"、"SQL 生成"）
            status:      步骤状态，取值为 "pending" / "in_progress" / "completed"
            detail:      步骤详细输出（如生成的 SQL 文本、分析建议）
            thinking:    思考过程描述（用于展示 LLM 的思维链）
            sub_step:    子步骤标识（用于多维度评估场景中的子维度名称）
        """
        # 根据 status 自动计算 progress 百分比
        if status == "completed":
            progress = 100
        elif status == "in_progress":
            progress = 50
        else:
            progress = 0  # pending 状态

        self.steps.append({
            "step": step_num,
            "description": description,
            "status": status,
            "detail": detail,
            "thinking": thinking,
            "subStep": sub_step,
            "progress": progress,
        })

    def update_step(self, step_num: int, **kwargs):
        """更新指定步骤的状态信息。

        通过 step_num 定位步骤记录，然后用 kwargs 中的键值对覆盖/补充
        步骤字典的字段。常用于将步骤从 in_progress 更新为 completed。

        Args:
            step_num: 要更新的步骤序号
            **kwargs:  要更新的字段键值对（如 status="completed", detail="...")
        """
        for s in self.steps:
            if s["step"] == step_num:
                s.update(kwargs)
                break  # 找到目标步骤后立即停止遍历
