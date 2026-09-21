"""ipage-service 请求/响应数据模型。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """POST /ipage/generate 请求体。"""

    query: str = Field("", description="用户的态势问题")
    source: str = Field("manual", description="来源标记：manual/topic/draft")
    dataSourceId: str = Field("", description="可选：限定数据源（databaseId）")
    parentPageId: str = Field("", description="可选：基于历史页面带修改意见重新设计（复用其数据包）")
    sessionId: str = Field("", description="可选：归属会话；为空时自动新建或沿用父页面会话")
    context: Dict[str, Any] = Field(default_factory=dict, description="附加上下文（parentQuery 等）")


class SessionCreate(BaseModel):
    """POST /ipage/sessions 请求体。"""

    title: str = Field("", description="会话标题（默认空，由首个问题命名）")


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
