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
    query: str
    draftId: Optional[str] = None
    source: str = "manual"
    context: Dict[str, Any] = Field(default_factory=dict)
    userId: str = "local-admin"
    teamIds: List[str] = Field(default_factory=list)
    autoRefresh: bool = False


class ChartSpec(BaseModel):
    """单个统计图表规格（ECharts option 内联数据）。"""
    chartId: str
    type: str                         # bar | line | pie | radar | gauge | scatter | heatmap | relation | sankey | map
    title: str
    option: Dict[str, Any]
    explanation: str = ""
    datasetRef: str = ""


class MapLayerSpec(BaseModel):
    """地图图层规格（points/routes/areas 与前端 GeoMap.vue 同形，WGS84）。"""
    layerId: str
    points: List[Dict[str, Any]] = Field(default_factory=list)
    routes: List[Dict[str, Any]] = Field(default_factory=list)
    areas: List[Dict[str, Any]] = Field(default_factory=list)
    layerConfig: Dict[str, Any] = Field(default_factory=dict)


class Explanation(BaseModel):
    """图表说明，绑定 chartId。"""
    chartId: str
    text: str


class Narrative(BaseModel):
    """态势介绍 + 逐图说明（介绍性，非结论先行）。"""
    intro: str
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
    userId: str = "local-admin"
    teamIds: List[str] = Field(default_factory=list)
    status: str = "generating"        # generating | ready | partial | failed
    charts: List[ChartSpec] = Field(default_factory=list)
    map: Dict[str, Any] = Field(default_factory=dict)         # { layers: [MapLayerSpec] }
    narrative: Narrative = Field(default_factory=Narrative)
    datasets: List[DatasetSummary] = Field(default_factory=list)
