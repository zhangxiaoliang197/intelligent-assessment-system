"""
多智能体评估系统的共享状态定义
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class EvaluationState:
    """评估工作流的完整状态"""
    # 输入
    question: str
    session_id: Optional[str] = None
    database_id: str = ""                     # 用户选择的数据源（数据库配置ID）
    database_name: str = ""                   # 数据源名称
    dataset_ids: List[str] = field(default_factory=list)   # 补充信息：关联的数据集ID
    indicator_ids: List[str] = field(default_factory=list) # 补充信息：关联的指标ID

    # 编排阶段
    intent: str = ""
    entities: Dict[str, Any] = field(default_factory=dict)
    analysis_plan: str = ""

    # 数据源发现阶段（从数据库实时读取）
    database_tables: List[str] = field(default_factory=list)       # 数据库中所有表名
    table_schemas: List[Dict] = field(default_factory=list)        # 完整表结构 DDL
    indicator_defs: List[Dict] = field(default_factory=list)

    # SQL 阶段
    generated_sql: str = ""
    sql_explanation: str = ""
    sql_valid: bool = False
    sql_retry_count: int = 0

    # 执行阶段
    raw_results: List[Dict] = field(default_factory=list)
    execution_error: Optional[str] = None

    # 回答阶段
    final_answer: str = ""
    report_sections: Dict[str, str] = field(default_factory=dict)

    # 图表阶段（Chart Agent）
    need_chart: bool = False
    chart_config: Dict[str, Any] = field(default_factory=dict)

    # 执行步骤（用于前端流式展示）
    steps: List[Dict[str, Any]] = field(default_factory=list)

    # 错误
    error: Optional[str] = None

    def add_step(self, step_num: int, description: str,
                 status: str = "pending", detail: str = "",
                 thinking: str = "", sub_step: str = ""):
        self.steps.append({
            "step": step_num,
            "description": description,
            "status": status,
            "detail": detail,
            "thinking": thinking,
            "subStep": sub_step,
            "progress": 100 if status == "completed" else (50 if status == "in_progress" else 0)
        })

    def update_step(self, step_num: int, **kwargs):
        for s in self.steps:
            if s["step"] == step_num:
                s.update(kwargs)
                break
