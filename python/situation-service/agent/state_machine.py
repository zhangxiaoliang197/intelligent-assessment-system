"""State Machine —— 状态机（态势图 Agent 架构重构 v1.1 阶段 5）。

设计目标（参见方案文档 §4.2.6）：
- 用 dataclass + enum 表达阶段流转（无外部依赖）
- 状态枚举：PLAN → RESEARCH → WRITE → VERIFY → EMIT | FAILED
- 每个状态进入/退出可被观察（Observer 模式），便于 SSE 推送 + 日志 + 后续 SQLite 持久化

阶段 5 实现范围：
- 状态枚举 + StateMachine 类（进程内）
- 进入/退出钩子（on_enter/on_exit）
- SQLite 持久化预留接口（persist()/restore()），但暂不强制启用
"""
import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("situation-service")


class Stage(str, enum.Enum):
    """态势生成阶段枚举。"""
    PLAN = "plan"          # Planner Agent 规划
    RESEARCH = "research"  # Executor Agents 并行取数
    WRITE = "write"        # Writer Agents 并行产图 + 产地图
    VERIFY = "verify"      # Verifier Agent 校验
    NARRATIVE = "narrative"  # narrative Writer 文本（最后串行）
    EMIT = "emit"          # 输出 SSE done 事件
    FAILED = "failed"


# 允许的状态转换（防误跳）
_ALLOWED_TRANSITIONS: Dict[Stage, List[Stage]] = {
    Stage.PLAN: [Stage.RESEARCH, Stage.FAILED],
    Stage.RESEARCH: [Stage.WRITE, Stage.FAILED],
    Stage.WRITE: [Stage.VERIFY, Stage.NARRATIVE, Stage.FAILED],  # VERIFY 跳过则直入 NARRATIVE
    Stage.VERIFY: [Stage.WRITE, Stage.NARRATIVE, Stage.EMIT, Stage.FAILED],  # WRITE = Reflection 回写
    Stage.NARRATIVE: [Stage.EMIT, Stage.FAILED],
    Stage.EMIT: [],  # 终态
    Stage.FAILED: [],  # 终态
}


@dataclass
class StageRecord:
    """单个阶段的执行记录。"""
    stage: Stage
    entered_at: str = ""
    exited_at: str = ""
    duration_ms: int = 0
    success: bool = True
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


class StateMachine:
    """态势生成状态机。

    生命周期：单个 report_id 一个实例。
    用法：
        sm = StateMachine(report_id)
        await sm.enter(Stage.PLAN)
        ... do plan ...
        await sm.exit(Stage.PLAN, success=True, meta={"planner": "tool-call"})

        await sm.enter(Stage.RESEARCH)
        ... do executors ...
        await sm.exit(Stage.RESEARCH, success=True, meta={"evidences": 3})
    """

    def __init__(self, report_id: str):
        self.report_id = report_id
        self._current: Optional[Stage] = None
        self._history: List[StageRecord] = []
        self._on_enter: List[Callable[[Stage, StageRecord], Any]] = []
        self._on_exit: List[Callable[[Stage, StageRecord], Any]] = []
        # Reflection 计数器（每个阶段的失败重试次数）
        self._reflection_counts: Dict[Stage, int] = {}

    @property
    def current(self) -> Optional[Stage]:
        return self._current

    @property
    def history(self) -> List[StageRecord]:
        return list(self._history)

    def add_on_enter(self, callback: Callable[[Stage, StageRecord], Any]) -> None:
        self._on_enter.append(callback)

    def add_on_exit(self, callback: Callable[[Stage, StageRecord], Any]) -> None:
        self._on_exit.append(callback)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def enter(self, stage: Stage, meta: Optional[Dict[str, Any]] = None) -> StageRecord:
        """进入指定阶段（校验转换合法性）。"""
        if self._current is not None:
            allowed = _ALLOWED_TRANSITIONS.get(self._current, [])
            if stage not in allowed and stage != self._current:
                # Reflection 回写场景：允许 VERIFY → WRITE
                if not (self._current == Stage.VERIFY and stage == Stage.WRITE):
                    raise RuntimeError(
                        f"非法状态转换: {self._current.value} → {stage.value}"
                    )

        record = StageRecord(
            stage=stage,
            entered_at=self._now(),
            meta=meta or {},
        )
        self._current = stage
        self._history.append(record)

        for cb in self._on_enter:
            try:
                result = cb(stage, record)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.warning("on_enter 回调异常 (%s): %s", stage.value, exc)
        logger.info(
            "状态机进入 %s (reportId=%s, history_len=%s)",
            stage.value, self.report_id, len(self._history),
        )
        return record

    async def exit(
        self,
        stage: Stage,
        success: bool = True,
        error: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> StageRecord:
        """退出指定阶段（补充退出时间和持续时间）。"""
        if not self._history or self._history[-1].stage != stage:
            logger.warning("exit 调用与最近 enter 不匹配: 期望 %s, 实际 history 末尾 %s",
                           stage.value, self._history[-1].stage.value if self._history else "(空)")
            return StageRecord(stage=stage)

        record = self._history[-1]
        record.exited_at = self._now()
        # 计算持续时间（毫秒）
        try:
            entered = datetime.fromisoformat(record.entered_at.replace("Z", "+00:00"))
            exited = datetime.fromisoformat(record.exited_at.replace("Z", "+00:00"))
            record.duration_ms = int((exited - entered).total_seconds() * 1000)
        except (ValueError, AttributeError):
            pass
        record.success = success
        record.error = error
        if meta:
            record.meta.update(meta)

        for cb in self._on_exit:
            try:
                result = cb(stage, record)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.warning("on_exit 回调异常 (%s): %s", stage.value, exc)
        logger.info(
            "状态机退出 %s (success=%s, duration_ms=%s, reportId=%s)",
            stage.value, success, record.duration_ms, self.report_id,
        )
        return record

    def increment_reflection(self, stage: Stage) -> int:
        """增加某阶段的 Reflection 计数（用于限制重试轮次）。"""
        self._reflection_counts[stage] = self._reflection_counts.get(stage, 0) + 1
        return self._reflection_counts[stage]

    def reflection_count(self, stage: Stage) -> int:
        return self._reflection_counts.get(stage, 0)

    def snapshot(self) -> Dict[str, Any]:
        """导出状态机快照（供 SQLite 持久化用，阶段 5 后续启用）。"""
        return {
            "reportId": self.report_id,
            "current": self._current.value if self._current else None,
            "history": [
                {
                    "stage": r.stage.value,
                    "entered_at": r.entered_at,
                    "exited_at": r.exited_at,
                    "duration_ms": r.duration_ms,
                    "success": r.success,
                    "error": r.error,
                    "meta": r.meta,
                }
                for r in self._history
            ],
            "reflection_counts": {k.value: v for k, v in self._reflection_counts.items()},
        }


__all__ = ["Stage", "StageRecord", "StateMachine"]
