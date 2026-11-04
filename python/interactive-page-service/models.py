"""ipage-service 请求/响应数据模型。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ArtifactItem(BaseModel):
    """评估分析产物的单条数据项（已由前端归一化）。"""

    artifactId: str = Field(..., max_length=64, description="评估步骤/产物的稳定 id（如 q1）")
    name: str = Field("", max_length=160, description="步骤名或数据集名")
    purpose: str = Field("", max_length=1000, description="步骤说明，作为数据包 purpose")
    mode: str = Field("aggregate", description="aggregate=聚合结果（图表）；detail=明细（表格/地图）")
    columns: List[str] = Field(default_factory=list, description="结果列名")
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="结果行数据")
    totalRows: int = Field(0, description="结果总行数（可能是截断前的行数）")
    truncated: bool = Field(False, description="前端是否已截断")
    chartHint: Optional[Dict[str, Any]] = Field(
        None, description="评估结果自带的图表建议（vizType/xAxis/yAxis/chartTitle）",
    )
    geo: Optional[Dict[str, List[Dict[str, Any]]]] = Field(
        None, description="该数据项的地图标注：markers/routes/areas",
    )


class EvaluationArtifacts(BaseModel):
    """评估分析结果产物：用户勾选后由前端整理，用于直接生成态势页面。"""

    sourceSessionId: str = Field("", max_length=128, description="来源评估会话 id")
    question: str = Field("", max_length=2000, description="原评估问题")
    title: str = Field("", max_length=120, description="态势页面标题（用户可编辑）")
    dataSourceId: str = Field("", max_length=128, description="评估时使用的数据源（仅溯源）")
    skillId: str = Field("", max_length=128, description="评估使用的 Skill id")
    skillName: str = Field("", max_length=160, description="评估使用的 Skill 名称")
    conclusion: str = Field("", max_length=50000, description="综合评估结论（未勾选时为空）")
    presentation: Dict[str, bool] = Field(
        default_factory=dict, description="呈现偏好：kpi/chart/map/table",
    )
    items: List[ArtifactItem] = Field(default_factory=list, description="勾选的数据产物")


class GenerateRequest(BaseModel):
    """POST /ipage/generate 请求体。"""

    query: str = Field("", description="用户的态势问题")
    source: str = Field("manual", description="来源标记：manual/topic/draft/evaluation")
    dataSourceId: str = Field("", description="可选：限定数据源（databaseId）")
    parentPageId: str = Field("", description="可选：基于历史页面带修改意见重新设计（复用其数据包）")
    sessionId: str = Field("", description="可选：归属会话；为空时自动新建或沿用父页面会话")
    skillId: str = Field("", description="可选：显式指定技能（生成剧本）；非空即视为手动指定，忽略 skillMode")
    skillMode: str = Field("auto", description="技能套用方式：auto=按问题语义自动匹配；off=关闭技能走自由规划")
    context: Dict[str, Any] = Field(default_factory=dict, description="附加上下文（parentQuery 等）")
    artifacts: Optional[EvaluationArtifacts] = Field(
        None, description="评估产物模式：非空时跳过规划与取数，直接用勾选产物生成页面",
    )


class SessionCreate(BaseModel):
    """POST /ipage/sessions 请求体。"""

    title: str = Field("", description="会话标题（默认空，由首个问题命名）")


class SkillMatchRequest(BaseModel):
    """POST /ipage/skills/match 请求体（阈值标定与前端预判用）。"""

    query: str = Field("", description="待匹配的用户问题")
    topK: int = Field(3, description="返回候选数量上限")


class PageRecord(BaseModel):
    """交互页面产物（内存聚合态 + 落库快照共用）。"""

    pageId: str
    title: str = ""
    query: str = ""
    source: str = "manual"
    parentId: str = ""
    sessionId: str = ""
    userId: str = "local-admin"
    teamIds: List[str] = Field(default_factory=list)
    status: str = "generating"
    intent: str = ""
    directAnswer: str = ""
    html: str = ""
    dataBundle: Dict[str, Any] = Field(default_factory=dict)
    plan: Dict[str, Any] = Field(default_factory=dict)
    sqlLog: List[Dict[str, Any]] = Field(default_factory=list)
    error: str = ""
    createdAt: str = ""
    updatedAt: str = ""

    def to_store(self) -> Dict[str, Any]:
        """转为 page_store 接受的字典。"""
        return {
            "id": self.pageId,
            "title": self.title,
            "query": self.query,
            "userId": self.userId,
            "teamIds": self.teamIds,
            "status": self.status,
            "intent": self.intent,
            "directAnswer": self.directAnswer,
            "html": self.html,
            "dataBundle": self.dataBundle,
            "plan": self.plan,
            "parentId": self.parentId,
            "sessionId": self.sessionId,
            "sqlLog": self.sqlLog,
            "error": self.error,
        }

    @classmethod
    def from_store(cls, item: Dict[str, Any]) -> "PageRecord":
        """从 page_store 字典还原。"""
        return cls(
            pageId=item.get("pageId", ""),
            title=item.get("title", ""),
            query=item.get("query", ""),
            parentId=item.get("parentId", "") or "",
            sessionId=item.get("sessionId", "") or "",
            userId=item.get("userId", ""),
            teamIds=item.get("teamIds") or [],
            status=item.get("status", ""),
            intent=item.get("intent", ""),
            directAnswer=item.get("directAnswer", ""),
            html=item.get("html", ""),
            dataBundle=item.get("dataBundle") or {},
            plan=item.get("plan") or {},
            sqlLog=item.get("sqlLog") or [],
            error=item.get("error", ""),
            createdAt=item.get("createdAt", ""),
            updatedAt=item.get("updatedAt", ""),
        )
