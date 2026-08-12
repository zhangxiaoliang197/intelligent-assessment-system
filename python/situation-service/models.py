"""态势图服务数据模型（Pydantic）。

定义草稿态、生成请求、态势产物（Report）及其子结构。
字段与 docs/situation-map/04-接口契约.md 对齐。
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DraftContext(BaseModel):
    """跨功能跳转携带的上下文（各字段按来源可选）。"""
    query: str = ""
    indicatorIds: List[str] = Field(default_factory=list)
    evaluationId: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    autoGenerate: bool = False


class DraftRequest(BaseModel):
    """创建草稿态请求。"""
    source: str = "manual"           # manual | qa | indicator | evaluation
    context: DraftContext = Field(default_factory=DraftContext)
    userId: str = "local-admin"
    teamIds: List[str] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    """发起态势生成请求。"""
    query: str = Field(min_length=1, max_length=2000)
    draftId: Optional[str] = None
    source: str = "manual"
    context: Dict[str, Any] = Field(default_factory=dict)
    userId: str = "local-admin"
    teamIds: List[str] = Field(default_factory=list)
    autoRefresh: bool = False
    skillId: str = ""
    skillParameters: Dict[str, Any] = Field(default_factory=dict)
    # 数据源 ID：非空时按此数据源过滤数据集 schema 与指标（export/for-llm?databaseId=xxx）
    dataSourceId: str = ""


class SkillRecommendRequest(BaseModel):
    """根据自然语言问题推荐态势图 Skill。"""
    query: str = Field(default="", max_length=2000)
    limit: int = Field(default=3, ge=1, le=10)
    context: Dict[str, Any] = Field(default_factory=dict)


class SkillApplyRequest(BaseModel):
    """预执行 Skill，返回最终问题和可审计执行计划。"""
    query: str = Field(default="", max_length=2000)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class SkillFavoriteRequest(BaseModel):
    """收藏或取消收藏 Skill。"""
    favorite: bool = True


class SkillUpsertRequest(BaseModel):
    """创建或更新自定义 Skill。"""
    definition: Dict[str, Any]
    expectedRevision: Optional[int] = None


class SkillPublishRequest(BaseModel):
    """发布自定义 Skill。"""
    changeNote: str = Field(default="", max_length=300)


class SkillRollbackRequest(BaseModel):
    """回滚到指定已保存版本，回滚后进入草稿态。"""
    version: int = Field(ge=1)


class SkillMarkdownUpdateRequest(BaseModel):
    """更新完整 SKILL.md，并用内容哈希避免覆盖并发修改。"""
    content: str = Field(min_length=1, max_length=131072)
    expectedHash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class ChartSpec(BaseModel):
    """单个统计图表规格（ECharts option 内联数据）。"""
    chartId: str
    type: str                         # bar | line | pie | radar | gauge | scatter | heatmap | relation | sankey | map
    title: str
    option: Dict[str, Any]
    explanation: str = ""
    datasetRef: str = ""


class MapLayerSpec(BaseModel):
    """地图图层规格（points/routes/areas/circles 与前端 GeoMap.vue 同形，WGS84）。"""
    layerId: str
    points: List[Dict[str, Any]] = Field(default_factory=list)
    routes: List[Dict[str, Any]] = Field(default_factory=list)
    areas: List[Dict[str, Any]] = Field(default_factory=list)
    circles: List[Dict[str, Any]] = Field(default_factory=list)
    layerConfig: Dict[str, Any] = Field(default_factory=dict)


class Explanation(BaseModel):
    """图表说明，绑定 chartId。"""
    chartId: str
    text: str


class Narrative(BaseModel):
    """态势介绍 + 逐图说明（介绍性，非结论先行）。"""
    intro: str = ""
    explanations: List[Explanation] = Field(default_factory=list)


class DatasetSummary(BaseModel):
    """数据集摘要（流式推送 dataset 事件用）。"""
    datasetId: str
    source: str
    summary: str
    rows: int = 0


class Report(BaseModel):
    """完整态势产物。"""
    reportId: str
    title: str
    query: str
    source: str = "manual"
    skillId: str = ""
    skillName: str = ""
    skillCategory: str = ""
    skillParameters: Dict[str, Any] = Field(default_factory=dict)
    userId: str = "local-admin"
    teamIds: List[str] = Field(default_factory=list)
    status: str = "generating"        # generating | ready | partial | failed
    # 数据源 ID（透传到 stream 阶段供 real_generate 过滤数据集 schema；仅生成期使用，落库 snapshot 也包含）
    dataSourceId: str = ""
    charts: List[ChartSpec] = Field(default_factory=list)
    map: Dict[str, Any] = Field(default_factory=dict)         # { layers: [MapLayerSpec] }
    narrative: Narrative = Field(default_factory=Narrative)
    datasets: List[DatasetSummary] = Field(default_factory=list)
