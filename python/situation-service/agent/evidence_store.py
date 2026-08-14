"""Evidence Store —— 证据存储（态势图 Agent 架构重构 v1.1 阶段 2）。

设计目标（参见方案文档 §4.2.3）：
- Ptah 的 Visual Working Memory 简化版
- 进程内 dataclass，按 report_id 隔离，关键节点持久化到 admin-service snapshot_json
- 作为下游 Writer 的单一数据源（Single Source of Truth），消除重复取数
- 支持 chart 元数据回写，供 narrative 反向引用（解决 P2 文本与图表脱节）

并发安全：
- 单个 report_id 内的 add 操作用 asyncio.Lock 串行化
- 不同 report_id 之间隔离，互不影响
"""
import asyncio
import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("situation-service")


def _evidence_digest(rows: List[Dict[str, Any]]) -> str:
    """计算证据行的稳定摘要（用于 cross-check 取数一致性）。

    与 orchestrator._evidence_digest 同口径，避免循环依赖。
    """
    if not rows:
        return ""
    payload = json.dumps(rows, ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Evidence:
    """单条证据：一个子问题的取数结果 + 摘要。

    Attributes:
        id: 子问题 ID（与 Planner.subQuestions[*].id 对齐）
        sub_question: 子问题自然语言描述
        rows: 脱敏聚合后的真实数据（受 SITUATION_LLM_EVIDENCE_ROWS 截断）
        columns: 字段名列表（与 rows 顺序对齐）
        summary: 数据摘要（LLM 生成或确定性统计）
        source: 来源标记（dataset_id / knowledge / indicator）
        dataset_ref: 实际取数的 datasetId（可能与 source 不同：如 fallback 到全表）
        timestamp: ISO8601 时间戳
        hash: rows 的稳定摘要
        meta: 附加元数据（如 filters/aggregation/rowCount/totalRows）
    """
    id: str
    sub_question: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    summary: str = ""
    source: str = ""
    dataset_ref: str = ""
    timestamp: str = ""
    hash: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChartMetadata:
    """图表元数据，由 chart Writer 写回，供 narrative 反向引用。"""
    chart_id: str
    title: str
    chart_type: str
    explanation: str = ""
    dataset_ref: str = ""
    field_mapping: Dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    verify_failed_reason: str = ""


class EvidenceStore:
    """单个 report_id 的证据存储。

    生命周期：在 Orchestrator 启动时创建，整个态势生成过程内共享，结束时丢弃。
    持久化由 Orchestrator 在关键节点调用 snapshot() 完成。
    """

    def __init__(self, report_id: str):
        self.report_id = report_id
        self._evidences: Dict[str, Evidence] = {}  # evidence_id -> Evidence
        self._chart_meta: Dict[str, ChartMetadata] = {}  # chart_id -> ChartMetadata
        self._lock = asyncio.Lock()

    async def add_evidence(self, evidence: Evidence) -> None:
        """写入或更新一条证据。同 id 视为更新（如 Executor 重试）。"""
        async with self._lock:
            if not evidence.timestamp:
                evidence.timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
            if not evidence.hash:
                evidence.hash = _evidence_digest(evidence.rows)
            self._evidences[evidence.id] = evidence

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        return self._evidences.get(evidence_id)

    def list_evidences(self) -> List[Evidence]:
        return list(self._evidences.values())

    def rows_for(self, evidence_id: str) -> List[Dict[str, Any]]:
        ev = self._evidences.get(evidence_id)
        return ev.rows if ev else []

    async def add_chart_metadata(self, meta: ChartMetadata) -> None:
        async with self._lock:
            self._chart_meta[meta.chart_id] = meta

    def get_chart_metadata(self, chart_id: str) -> Optional[ChartMetadata]:
        return self._chart_meta.get(chart_id)

    def list_chart_metadata(self) -> List[ChartMetadata]:
        return list(self._chart_meta.values())

    def snapshot(self) -> Dict[str, Any]:
        """导出可序列化快照，用于持久化到 admin-service snapshot_json 字段。"""
        return {
            "reportId": self.report_id,
            "evidences": [ev.to_dict() for ev in self._evidences.values()],
            "charts": [asdict(m) for m in self._chart_meta.values()],
            "evidenceCount": len(self._evidences),
            "chartCount": len(self._chart_meta),
        }

    def format_for_llm(self, max_rows_per_evidence: int = 30) -> str:
        """格式化为 LLM 可读文本，供 chart/narrative Writer 使用。

        与 prompts._format_data 的差异：按 evidence_id 组织，附摘要，
        便于 Writer 在 prompt 中区分不同来源。
        """
        if not self._evidences:
            return "（Evidence Store 暂无证据）"
        lines = []
        for ev in self._evidences.values():
            sample = ev.rows[:max_rows_per_evidence]
            lines.append(
                f"--- 证据 {ev.id}（来源：{ev.source or ev.dataset_ref}） ---"
            )
            lines.append(f"子问题：{ev.sub_question}")
            if ev.summary:
                lines.append(f"摘要：{ev.summary}")
            payload = {
                "columns": ev.columns,
                "rows": sample,
                "totalRows": ev.meta.get("totalRows", len(ev.rows)),
            }
            lines.append("数据：" + json.dumps(payload, ensure_ascii=False, default=str))
        return "\n".join(lines)


__all__ = ["Evidence", "ChartMetadata", "EvidenceStore"]
