"""本体模型服务（ontology-service）。

负责本体模型的构建与管理，建立概念之间的语义关系，提供知识图谱可视化数据。
A 阶段实现：多本体隔离、元模型类型约束、JSON 属性、持久化加固、路径查询、示例数据。

数据持久化策略：
- 每个本体独立一个 JSON 文件 data/ontology_{id}.json（含本体元信息 + 实体 + 关系）
- data/ontologies_index.json 存本体列表索引
- 原子写入（临时文件 + rename + .bak 备份）+ filelock 跨进程锁 + asyncio.Lock 协程锁
"""

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

from fastapi import FastAPI, HTTPException, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from collections import defaultdict, deque
import uuid
import json
import os
import logging
import tempfile
import asyncio
from filelock import FileLock

# ---------- 分步构建模块 ----------
from doc_parser import extract_text, truncate_for_llm
from llm_client import call_llm_json
import build_prompts
import config
from text_batcher import split_into_batches
from migration import migrate_ontology_dict, backup_data_dir

# ---------- 统一日志 ----------
from logging_config import setup_logging
setup_logging("ontology-service")
logger = logging.getLogger("ontology-service")

app = FastAPI(
    title="本体模型服务",
    description="本体构建与知识图谱展示",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 默认元模型 ----------
# 创建本体时若未指定类型，使用以下默认类型集
# 元模型定义粗粒度类型分类（概念/实体/属性/事件），ConceptType 在此基础上做细粒度类型定义
DEFAULT_ENTITY_TYPES = [
    {"name": "概念", "color": "#5470c6"},
    {"name": "实体", "color": "#91cc75"},
    {"name": "属性", "color": "#fac858"},
    {"name": "事件", "color": "#ee6666"},
]
DEFAULT_RELATION_TYPES = [
    {"name": "包含"},
    {"name": "关联"},
    {"name": "影响"},
    {"name": "衡量"},
    {"name": "继承"},
]

# 数据 schema 版本（与 migration.SCHEMA_VERSION 保持一致）
SCHEMA_VERSION = 2


# ---------- 数据模型：三层分离（概念层 / 实体层 / 属性层）----------
class EntityType(BaseModel):
    """元模型实体类型（粗分类，定义允许的类型与颜色）。"""
    name: str
    color: Optional[str] = None


class RelationType(BaseModel):
    """元模型关系类型。"""
    name: str


class PropertySchema(BaseModel):
    """属性骨架：定义某类概念应具备的属性模板。

    ConceptType 携带 property_schema 列表，实例化为实体时 LLM 按此骨架填充属性。
    """
    name: str                            # 属性名，如"资产负债率"
    category: str = "descriptive"        # descriptive（描述型）| metric（指标型）
    data_type: str = "string"            # string | number | date | enum
    unit: str = ""                       # 单位，如"%""万元"
    required: bool = False
    description: str = ""


class PropertyHistoryEntry(BaseModel):
    """属性历史值条目（仅指标型属性会有历史值）。"""
    value: Any = None
    recorded_at: Optional[datetime] = None   # 采集时间
    source_snippet: str = ""                 # 该历史值的来源原文
    note: str = ""


class PropertyVerification(BaseModel):
    """属性验证结果（step4 LLM 自检后写入，Phase 1 预留字段）。"""
    status: str = "verified"             # verified | suspect | unverified
    reason: str = ""                     # 存疑原因


class Property(BaseModel):
    """结构化属性：依附实体或关系，区分描述型/指标型。

    指标型属性支持历史版本（history）和数据字段绑定（bindings）。
    """
    id: str                              # prop_xxxx
    entity_id: str = ""                  # 所属实体/关系ID（关系属性时存关系ID）
    name: str                            # 属性名，如"资产负债率"
    value: Any = None                    # 当前值
    category: str = "descriptive"        # descriptive（描述型）| metric（指标型）
    data_type: str = "string"            # string | number | date | enum
    unit: str = ""                       # 单位
    source_snippet: str = ""             # 属性值来源原文（可溯源）
    # 指标型属性的数据字段绑定（复用 ass_field_annotation）
    bindings: Dict[str, str] = Field(default_factory=dict)
    # 指标历史版本：指标型属性更新时旧值自动追加
    history: List[PropertyHistoryEntry] = Field(default_factory=list)
    # 验证标记（step4 LLM 自检后写入）
    verification: Optional[PropertyVerification] = None
    create_time: datetime
    update_time: datetime


class ConceptType(BaseModel):
    """概念（类型层）：实体实例化的模板。

    每个概念属于元模型中的某个 entity_type（粗分类），
    携带 property_schema 定义该类实体的属性骨架。
    """
    id: str                              # concept_xxxx
    ontology_id: str
    name: str                            # 概念名，如"公司""人""城市"
    entity_type: str = ""                # 归属的元模型 entity_type name，如"实体"
    description: str = ""                # 概念释义
    color: Optional[str] = None          # 前端展示颜色（继承自 entity_type）
    property_schema: List[PropertySchema] = Field(default_factory=list)
    source_snippet: str = ""             # 概念来源原文（防幻觉）
    create_time: datetime
    update_time: datetime


class Entity(BaseModel):
    """实体（实例层）：具体的人/物/事。

    instance_of 指向 ConceptType.id，取代原 type 字符串字段。
    属性升级为 List[Property]，支持结构化分类与历史版本。
    """
    id: str
    ontology_id: str
    name: str
    instance_of: str = ""                # 概念ID（ConceptType.id），替代原 type 字段
    # 兼容旧数据：迁移后的实体保留 type 字段为空串，新实体不用
    type: str = ""
    is_primary: bool = False             # 是否主要实体（多本体拆分依据）
    properties: List[Property] = Field(default_factory=list)
    # 数据字段绑定（实体级，保留向后兼容；指标型属性也可在 property.bindings 单独绑定）
    bindings: Dict[str, str] = Field(default_factory=dict)
    source_snippet: str = ""             # 实体来源原文
    create_time: datetime
    update_time: datetime


class Relation(BaseModel):
    """关系（概念之间的有向边）。"""
    id: str
    ontology_id: str
    source_id: str
    target_id: str
    relation_type: str
    properties: List[Property] = Field(default_factory=list)
    # 数据绑定：关系绑定到具体指标（ass_indicator）
    bindings: Dict[str, str] = Field(default_factory=dict)
    weight: float = 1.0
    source_snippet: str = ""             # 关系来源原文
    create_time: datetime


class OntologyModel(BaseModel):
    """本体模型（一个独立的本体空间，隔离概念/实体/关系）。"""
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    entity_types: List[EntityType] = Field(default_factory=list)
    relation_types: List[RelationType] = Field(default_factory=list)
    create_time: datetime
    update_time: datetime
    status: str = "活跃"
    # 默认本体标志，三服务自动取默认本体的依据；同一时刻仅一个为 True
    is_default: bool = False
    # 数据 schema 版本：1=旧（Dict 属性）, 2=新（List[Property] 属性 + 概念层）
    schema_version: int = SCHEMA_VERSION


class BuildJob(BaseModel):
    """本体分步构建任务（五阶段状态机）。

    支持断点续作：每步结果持久化到 data/build_jobs/job_{id}.json。
    五阶段流程：
      upload → step0 元模型+粒度 → step1 概念提取（类型层）
      → step2 实体+属性提取（实例层）→ step3 关系建模 → step4 验证+报告

    旧任务（四阶段 schema）保留向后兼容：step<=4 且 status=completed 视为 legacy。
    """
    id: str                                    # job_xxxxxxxx
    name: str                                  # 本体名称
    description: str = ""
    step: int = 0                              # 0=待开始,1=概念,2=实体属性,3=关系,4=验证报告,5=已完成
    status: str = "draft"                      # draft | completed | abandoned | legacy

    # 文档源（持久化，支持断点续作）
    source_filename: str = ""
    source_text: str = ""                      # 解析后的纯文本
    char_count: int = 0                        # 文档字符数（前端展示用）

    # Step 0 结果：元模型 + 粒度 + 阶段提示词
    meta_entity_types: List[Dict[str, Any]] = []
    meta_relation_types: List[Dict[str, Any]] = []
    meta_confirmed: bool = False
    granularity: str = "medium"                # coarse | medium | fine（三档粒度预设）
    stage_hints: Dict[int, str] = {}           # {1: "重点关注财务指标", 2: "...", ...}

    # Step 1 结果：概念清单（类型层，不提取具体实例）
    step1_concepts: List[Dict[str, Any]] = []
    step1_confirmed: bool = False

    # Step 2 结果：实体+属性（实例层，每个实体 instance_of 指向 step1 概念）
    step2_entities: List[Dict[str, Any]] = []
    step2_confirmed: bool = False
    # 主要实体识别（step2 完成后 LLM 标注，用户勾选）
    primary_entity_candidates: List[str] = []  # LLM 推荐的主要实体名
    primary_entity_selected: List[str] = []    # 用户勾选的主要实体名

    # Step 3 结果：关系建模
    step3_relations: List[Dict[str, Any]] = []
    step3_confirmed: bool = False

    # Step 4 结果：验证 + 报告
    step4_verification: Optional[Dict[str, Any]] = None  # {verified_count, suspect_count, suspects: [...]}
    step4_report: Optional[str] = None                    # LLM 生成的 markdown 简报
    step4_confirmed: bool = False

    # Step 1 分批状态（长文档分批提取概念，支持断点续作）
    step1_batches_total: int = 0
    step1_batches_done: int = 0
    step1_batch_results: List[List[Dict[str, Any]]] = []
    step1_failed_batch: int = -1
    step1_failed_reason: Optional[str] = None

    # Step 2 分批状态（长文档分批提取实体，支持断点续作）
    step2_batches_total: int = 0
    step2_batches_done: int = 0
    step2_batch_results: List[List[Dict[str, Any]]] = []
    step2_failed_batch: int = -1
    step2_failed_reason: Optional[str] = None

    # Step 3 分组状态（实体过多时分组构建关系，支持断点续作）
    step3_groups_total: int = 0
    step3_groups_done: int = 0
    step3_group_results: List[Dict[str, Any]] = []  # 每组 {"relations": [...]}
    step3_failed_group: int = -1
    step3_failed_reason: Optional[str] = None
    # Step 3 跨组关系补充
    step3_cross_group_done: bool = False
    step3_cross_group_relations: List[Dict[str, Any]] = []
    step3_cross_group_failed: bool = False
    step3_cross_group_reason: Optional[str] = None

    # ── 旧字段保留（向后兼容旧四阶段任务，新流程不使用）──
    step2_relations: List[Dict[str, Any]] = []          # 旧 step2 关系（新流程关系在 step3_relations）
    step3_entities: List[Dict[str, Any]] = []           # 旧 step3 序列化实体（新流程废弃）
    step2_groups_total_legacy: int = 0                  # 旧 step2 分组（新流程分组在 step3）
    step2_groups_done_legacy: int = 0
    step2_group_results_legacy: List[Dict[str, Any]] = []
    step2_failed_group_legacy: int = -1
    step2_failed_reason_legacy: Optional[str] = None
    step2_cross_group_done_legacy: bool = False
    step2_cross_group_relations_legacy: List[Dict[str, Any]] = []
    step2_cross_group_failed_legacy: bool = False
    step2_cross_group_reason_legacy: Optional[str] = None

    # 关联正式本体（step4 确认后生成）
    ontology_id: Optional[str] = None

    # 后台任务进度跟踪
    running_step: int = -1                     # -1=空闲, 1=概念提取, 2=实体提取, 3=关系建模, 4=验证
    progress: int = 0                          # 0-100
    progress_message: str = ""
    progress_stages: List[Dict[str, Any]] = []  # 真实进度：[{name, status, started_at, finished_at}]
    error_message: Optional[str] = None

    create_time: datetime
    update_time: datetime


# ---------- 后台任务管理 ----------
# 存储正在运行的后台LLM任务（asyncio.Task），即使HTTP连接断开也继续执行
_background_tasks: Dict[str, Any] = {}


# ---------- SSE 事件订阅 ----------
# 每个 job 维护一组订阅者队列，后台任务产出增量时广播给所有订阅者
# 支持同一 job 多浏览器标签同时订阅；队列满则丢事件，保证慢消费者不阻塞后台任务
_stream_subscribers: Dict[str, set] = defaultdict(set)
# 单个订阅者队列上限：超出则丢弃新事件（后台任务不阻塞，前端断线重连时靠回放补全）
_SSE_QUEUE_MAXSIZE = 50
# SSE 空闲心跳间隔（秒）：防止 nginx/浏览器因空闲超时掐断连接
_SSE_HEARTBEAT_TIMEOUT = 15


def _emit_event(job_id: str, event_type: str, data: Any) -> None:
    """向某 job 的所有 SSE 订阅者广播事件（非阻塞）。

    Args:
        job_id: 构建任务 ID
        event_type: 事件类型（batch_done / group_done / cross_group_done / step_done / error / progress）
        data: 事件数据（将被 JSON 序列化）

    说明：
        - 用 put_nowait 非阻塞写入，队列满则丢弃并告警，保证后台 LLM 任务不被慢消费者拖住
        - 前端断线重连时通过 SSE 端点的"回放已完成批次"机制补全丢失事件
    """
    for queue in list(_stream_subscribers.get(job_id, [])):
        try:
            queue.put_nowait({"type": event_type, "data": data})
        except asyncio.QueueFull:
            logger.warning(f"[{job_id}] SSE 订阅队列已满，丢弃事件: {event_type}")


def _sse_format(event_type: str, data: Any) -> str:
    """格式化为 SSE 数据帧（event + data 两行，空行结尾）。"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _set_job_progress(job_id: str, running_step: int, progress: int, message: str) -> None:
    """更新任务进度（线程安全）。"""
    job = build_jobs_db.get(job_id)
    if not job:
        return
    job.running_step = running_step
    job.progress = progress
    job.progress_message = message
    job.update_time = datetime.now()
    save_build_job(job_id)
    save_build_jobs_index()


# ---------- 分批/合并辅助函数 ----------
def _normalize_name(name: str) -> str:
    """名称归一化：trim 空白 + 全角括号转半角，用于跨批/跨组去重比较。

    防止"命中率（%）"与"命中率(%)"被误判为不同概念。
    """
    if not name:
        return ""
    s = name.strip()
    # 全角括号转半角
    s = s.replace("（", "(").replace("）", ")")
    # 全角空格转半角
    s = s.replace("\u3000", " ")
    return s


def _merge_concepts(all_concepts: list) -> list:
    """合并多批提取的概念，按 name 去重。

    Args:
        all_concepts: 所有批次的概念列表（已展开为一维）

    Returns:
        去重合并后的概念列表，保持首次出现顺序
    """
    merged = {}
    order = []
    for c in all_concepts:
        if not isinstance(c, dict):
            continue
        key = _normalize_name(c.get("name", ""))
        if not key:
            continue
        if key not in merged:
            merged[key] = dict(c)
            # 归一化 name 字段本身
            merged[key]["name"] = c.get("name", "").strip()
            order.append(key)
        else:
            existing = merged[key]
            # type 不覆盖（首次出现的已受元模型约束）
            # description / source_snippet 取首个非空
            if not existing.get("description") and c.get("description"):
                existing["description"] = c["description"]
            if not existing.get("source_snippet") and c.get("source_snippet"):
                existing["source_snippet"] = c["source_snippet"]
    return [merged[k] for k in order]


def _group_concepts(concepts: list, group_size: int) -> list:
    """按 type 聚类后再按 group_size 切分，同类型概念尽量同组。

    同类型概念之间关系最密集，同组内能让 LLM 建立更完整的关系网。
    某 type 概念过多仍切多组；某 type 概念极少单独成组。

    Args:
        concepts: 已确认的概念清单
        group_size: 每组概念数上限

    Returns:
        概念分组列表，每个元素是该组的概念子集
    """
    by_type = {}
    type_order = []  # 保持 type 首次出现顺序，避免分组顺序不稳定
    for c in concepts:
        t = c.get("type", "未分类")
        if t not in by_type:
            by_type[t] = []
            type_order.append(t)
        by_type[t].append(c)

    groups = []
    for t in type_order:
        items = by_type[t]
        for i in range(0, len(items), group_size):
            groups.append(items[i:i + group_size])
    return groups


def _merge_entities(all_entities: list) -> list:
    """合并多批/多组构建的实体，按 name 去重。

    兼容两种 properties 格式：
    - List[Dict]（新五阶段 step2 产出）：按属性 name 去重合并，保留首次出现的值
    - Dict[str,str]（旧四阶段产出）：浅合并，后者补充前者没有的 key

    Args:
        all_entities: 所有批次/组的实体列表（已展开为一维）

    Returns:
        去重合并后的实体列表，保持首次出现顺序
    """
    merged = {}
    order = []
    for e in all_entities:
        if not isinstance(e, dict):
            continue
        key = _normalize_name(e.get("name", ""))
        if not key:
            continue
        if key not in merged:
            merged[key] = dict(e)
            merged[key]["name"] = e.get("name", "").strip()
            order.append(key)
        else:
            existing = merged[key]
            # instance_of 不覆盖（首次出现的已受概念清单约束）
            if not existing.get("instance_of") and e.get("instance_of"):
                existing["instance_of"] = e["instance_of"]
            # 旧字段 parent 取首个非空（向后兼容）
            if not existing.get("parent") and e.get("parent"):
                existing["parent"] = e["parent"]
            # source_snippet 取首个非空
            if not existing.get("source_snippet") and e.get("source_snippet"):
                existing["source_snippet"] = e["source_snippet"]
            # is_primary_candidate: 任一批标注为 True 则保留 True
            if e.get("is_primary_candidate") and not existing.get("is_primary_candidate"):
                existing["is_primary_candidate"] = True
            # properties 合并：按格式分流
            ex_props = existing.get("properties")
            new_props = e.get("properties")
            if isinstance(ex_props, list) or isinstance(new_props, list):
                # 新格式 List[Dict]：按属性 name 去重合并
                ex_list = ex_props if isinstance(ex_props, list) else []
                new_list = new_props if isinstance(new_props, list) else []
                seen_names = {_normalize_name(p.get("name", "")) for p in ex_list if isinstance(p, dict)}
                for p in new_list:
                    if not isinstance(p, dict):
                        continue
                    pname = _normalize_name(p.get("name", ""))
                    if pname and pname not in seen_names:
                        ex_list.append(p)
                        seen_names.add(pname)
                existing["properties"] = ex_list
            elif isinstance(ex_props, dict) or isinstance(new_props, dict):
                # 旧格式 Dict：浅合并
                ex_dict = ex_props if isinstance(ex_props, dict) else {}
                new_dict = new_props if isinstance(new_props, dict) else {}
                for k, v in new_dict.items():
                    if k not in ex_dict:
                        ex_dict[k] = v
                existing["properties"] = ex_dict
    return [merged[k] for k in order]


def _derive_concept_color(entity_type: str, meta_entity_types: list) -> str:
    """根据概念的 entity_type 从元模型中查找对应颜色。

    Args:
        entity_type: 概念归属的元模型类型名
        meta_entity_types: 已确认的元模型实体类型 [{"name","color"}]

    Returns:
        颜色 hex 值，未匹配则返回默认色 #5470c6
    """
    for t in meta_entity_types:
        if t.get("name") == entity_type:
            return t.get("color", "#5470c6")
    return "#5470c6"


def _enrich_concepts_with_color(concepts: list, meta_entity_types: list) -> list:
    """为合并后的概念列表填充 color 字段（从 meta_entity_types 按 entity_type 推导）。

    LLM 输出概念时只给 entity_type，color 由后端统一推导，避免 LLM 输出不一致。

    Args:
        concepts: 合并去重后的概念列表
        meta_entity_types: 已确认的元模型实体类型

    Returns:
        填充 color 后的概念列表（原地修改并返回）
    """
    for c in concepts:
        if not c.get("color"):
            c["color"] = _derive_concept_color(c.get("entity_type", ""), meta_entity_types)
    return concepts


# ---------- 阶段进度跟踪（真实进度条）----------
# progress_stages 记录每个阶段的开始/结束时间，前端按时间线展示真实进度
_STAGE_NAMES = {
    1: "概念提取",
    2: "实体+属性提取",
    3: "关系建模",
    4: "验证+报告",
}


def _mark_stage_started(job_id: str, stage: int) -> None:
    """标记某阶段开始（在 progress_stages 中追加 running 条目）。"""
    job = build_jobs_db.get(job_id)
    if not job:
        return
    # 同一阶段不重复追加（断点续作时复用已有条目）
    for s in job.progress_stages:
        if s.get("stage") == stage:
            if s.get("status") != "running":
                s["status"] = "running"
                s["started_at"] = datetime.now().isoformat()
                s["finished_at"] = None
            return
    job.progress_stages.append({
        "stage": stage,
        "name": _STAGE_NAMES.get(stage, f"阶段{stage}"),
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
    })
    job.update_time = datetime.now()
    save_build_job(job_id)


def _mark_stage_finished(job_id: str, stage: int, success: bool = True) -> None:
    """标记某阶段结束（更新对应条目为 done/failed）。"""
    job = build_jobs_db.get(job_id)
    if not job:
        return
    for s in job.progress_stages:
        if s.get("stage") == stage:
            s["status"] = "done" if success else "failed"
            s["finished_at"] = datetime.now().isoformat()
            break
    else:
        # 未找到已有条目（异常场景），补一条
        job.progress_stages.append({
            "stage": stage,
            "name": _STAGE_NAMES.get(stage, f"阶段{stage}"),
            "status": "done" if success else "failed",
            "started_at": datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
        })
    job.update_time = datetime.now()
    save_build_job(job_id)


def _deduplicate_relations(relations: list) -> list:
    """关系去重：按 (source, target, relation_type) 三元组去重，保留首次出现。

    跨组补充的关系可能与组内关系重复，需去重。

    Args:
        relations: 所有关系列表（组内 + 跨组补充）

    Returns:
        去重后的关系列表
    """
    seen = set()
    result = []
    for r in relations:
        if not isinstance(r, dict):
            continue
        key = (
            _normalize_name(r.get("source", "")),
            _normalize_name(r.get("target", "")),
            r.get("relation_type", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(r)
    return result


async def _background_extract_concepts(job_id: str) -> None:
    """后台任务：Step 1 概念提取（类型层，LLM调用，支持长文档分批 + 断点续作）。

    注入粒度预设（granularity）和阶段提示词（stage_hints[1]）控制提取数量与侧重。
    """
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        _mark_stage_started(job_id, 1)
        # ---- 1. 判断是首次还是续跑 ----
        # 续跑条件：已分批过、未跑完、有失败标记
        is_resume = (job.step1_batches_total > 0
                     and job.step1_batches_done < job.step1_batches_total
                     and job.step1_failed_batch >= 0)
        # 已有完整 step1_concepts 且无失败 → 直接结束（防重复跑）
        if not is_resume and job.step1_concepts and job.step1_failed_batch < 0:
            _set_job_progress(job_id, -1, 100, "概念提取已完成")
            _mark_stage_finished(job_id, 1)
            return

        # ---- 2. 重建 batches（无论首次还是续跑都重新切分，纯函数结果稳定）----
        if len(job.source_text) <= config.STEP1_BATCH_THRESHOLD_CHARS:
            # 短文档：单批，保持兼容
            batches = [job.source_text]
            total = 1
        else:
            batches = split_into_batches(
                job.source_text,
                max_chars=config.STEP1_BATCH_MAX_CHARS,
                overlap=config.STEP1_BATCH_OVERLAP,
            )
            total = len(batches)

        # 首次运行：记录总批数
        if job.step1_batches_total == 0:
            async with build_lock:
                job.step1_batches_total = total
                # 扩容 step1_batch_results 到 total 长度
                while len(job.step1_batch_results) < total:
                    job.step1_batch_results.append([])
                job.update_time = datetime.now()
                save_build_job(job_id)
        elif job.step1_batches_total != total:
            # config 参数被改导致批数变化：以新批数为准，重置 done 为已完成批次的最小值
            logger.warning(
                f"[{job_id}] 分批数变化 {job.step1_batches_total}→{total}，"
                f"已成功 {job.step1_batches_done} 批结果保留，按新边界续跑"
            )
            async with build_lock:
                job.step1_batches_total = total
                while len(job.step1_batch_results) < total:
                    job.step1_batch_results.append([])
                save_build_job(job_id)

        total = job.step1_batches_total
        # 续跑从已成功批次数开始；首次从 0 开始
        start_idx = job.step1_batches_done if is_resume else 0

        logger.info(
            f"[{job_id}] Step1 概念提取：共 {total} 批，"
            f"{'续跑从第 ' + str(start_idx + 1) + ' 批' if is_resume else '首次从头'}开始"
        )

        # ---- 3. 串行跑每批 ----
        stage_hint_1 = job.stage_hints.get(1, "") if job.stage_hints else ""
        for idx in range(start_idx, total):
            _set_job_progress(
                job_id, 1,
                10 + int(85 * idx / max(total, 1)),
                f"正在提取概念（第 {idx + 1}/{total} 批）..." if total > 1 else "正在调用AI提取概念..."
            )
            batch_text = batches[idx] if idx < len(batches) else ""
            messages = build_prompts.build_step1_batch_messages(
                batch_text, job.name, job.meta_entity_types,
                batch_idx=idx, total_batches=total,
                granularity=job.granularity, stage_hint=stage_hint_1
            )
            batch_concepts = await _llm_json_async(messages, temperature=0.3, max_tokens=config.LLM_MAX_TOKENS)
            if not isinstance(batch_concepts, list):
                raise ValueError(f"第 {idx + 1}/{total} 批返回格式异常（非数组），原始类型: {type(batch_concepts).__name__}")

            # 持久化本批结果 + 推进 done
            async with build_lock:
                while len(job.step1_batch_results) <= idx:
                    job.step1_batch_results.append([])
                job.step1_batch_results[idx] = batch_concepts
                job.step1_batches_done = idx + 1
                job.step1_failed_batch = -1
                job.step1_failed_reason = None
                job.update_time = datetime.now()
                save_build_job(job_id)
            logger.info(f"[{job_id}] Step1 第 {idx + 1}/{total} 批完成: {len(batch_concepts)} 个概念")
            # 实时推送本批概念给前端（SSE 订阅者），前端按名称去重后追加
            _emit_event(job_id, "batch_done", {
                "batch_idx": idx,
                "batches_done": idx + 1,
                "batches_total": total,
                "concepts": batch_concepts
            })

        # ---- 4. 全部成功后合并去重 + 填充颜色 ----
        _set_job_progress(job_id, 1, 96, "正在合并概念...")
        all_concepts = [c for batch in job.step1_batch_results for c in batch]
        merged = _merge_concepts(all_concepts)
        # color 由后端按 entity_type 从元模型推导（LLM 不输出 color，避免不一致）
        _enrich_concepts_with_color(merged, job.meta_entity_types)
        async with build_lock:
            job.step1_concepts = merged
            job.step = max(job.step, 1)
            job.running_step = -1
            job.progress = 100
            job.progress_message = (
                f"概念提取完成，共 {len(merged)} 个概念" + (f"（{total} 批合并）" if total > 1 else "")
            )
            job.error_message = None
            job.update_time = datetime.now()
            save_build_job(job_id)
            save_build_jobs_index()
        _mark_stage_finished(job_id, 1)
        logger.info(f"[{job_id}] 后台概念提取完成: {len(merged)} 个概念（{total} 批合并）")
        # 推送 Step1 完成事件，前端据此启用"确认概念清单"按钮
        _emit_event(job_id, "step_done", {
            "step": 1,
            "concepts": merged,
            "total": len(merged)
        })
    except Exception as e:
        logger.error(f"[{job_id}] 后台概念提取失败: {e}")
        _mark_stage_finished(job_id, 1, success=False)
        async with build_lock:
            # 失败批次 = 当前正在跑这批（done 未推进时即 idx）
            failed_idx = job.step1_batches_done
            job.running_step = -1
            job.progress = 0
            job.step1_failed_batch = failed_idx
            job.step1_failed_reason = str(e)[:200]
            job.error_message = f"第 {failed_idx + 1}/{job.step1_batches_total} 批失败: {str(e)[:150]}"
            job.progress_message = f"第 {failed_idx + 1}/{job.step1_batches_total} 批失败，可点击继续提取从该批续跑"
            job.update_time = datetime.now()
            save_build_job(job_id)
        # 推送失败事件，前端展示错误并显示"继续提取概念"断点续作按钮
        _emit_event(job_id, "error", {"step": 1, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


async def _background_extract_entities(job_id: str) -> None:
    """后台任务：Step 2 实体+属性提取（实例层，LLM调用，支持长文档分批 + 断点续作）。

    从文档提取具体实例，每个实体 instance_of 一个 step1 概念，并按 property_schema 填充属性。
    注入粒度预设（granularity）和阶段提示词（stage_hints[2]）。
    提取完成后聚合 is_primary_candidate=True 的实体名为 primary_entity_candidates。
    """
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        _mark_stage_started(job_id, 2)
        concepts = job.step1_concepts or []
        if not concepts:
            raise ValueError("概念清单为空，无法提取实体")

        # ---- 1. 判断是首次还是续跑 ----
        is_resume = (job.step2_batches_total > 0
                     and job.step2_batches_done < job.step2_batches_total
                     and job.step2_failed_batch >= 0)
        if not is_resume and job.step2_entities and job.step2_failed_batch < 0:
            _set_job_progress(job_id, -1, 100, "实体提取已完成")
            _mark_stage_finished(job_id, 2)
            return

        # ---- 2. 重建 batches（按文档分批，与 step1 同源策略）----
        if len(job.source_text) <= config.STEP2_BATCH_THRESHOLD_CHARS:
            batches = [job.source_text]
            total = 1
        else:
            batches = split_into_batches(
                job.source_text,
                max_chars=config.STEP2_BATCH_MAX_CHARS,
                overlap=config.STEP2_BATCH_OVERLAP,
            )
            total = len(batches)

        if job.step2_batches_total == 0:
            async with build_lock:
                job.step2_batches_total = total
                while len(job.step2_batch_results) < total:
                    job.step2_batch_results.append([])
                job.update_time = datetime.now()
                save_build_job(job_id)
        elif job.step2_batches_total != total:
            logger.warning(
                f"[{job_id}] step2 分批数变化 {job.step2_batches_total}→{total}，"
                f"已成功 {job.step2_batches_done} 批结果保留，按新边界续跑"
            )
            async with build_lock:
                job.step2_batches_total = total
                while len(job.step2_batch_results) < total:
                    job.step2_batch_results.append([])
                save_build_job(job_id)

        total = job.step2_batches_total
        start_idx = job.step2_batches_done if is_resume else 0
        logger.info(
            f"[{job_id}] Step2 实体提取：共 {total} 批，"
            f"{'续跑从第 ' + str(start_idx + 1) + ' 批' if is_resume else '首次从头'}开始"
        )

        # ---- 3. 串行跑每批 ----
        stage_hint_2 = job.stage_hints.get(2, "") if job.stage_hints else ""
        for idx in range(start_idx, total):
            _set_job_progress(
                job_id, 2,
                10 + int(85 * idx / max(total, 1)),
                f"正在提取实体+属性（第 {idx + 1}/{total} 批）..." if total > 1 else "正在调用AI提取实体..."
            )
            batch_text = batches[idx] if idx < len(batches) else ""
            messages = build_prompts.build_step2_batch_messages(
                batch_text, job.name, concepts, job.meta_entity_types,
                batch_idx=idx, total_batches=total,
                granularity=job.granularity, stage_hint=stage_hint_2
            )
            batch_entities = await _llm_json_async(messages, temperature=0.3, max_tokens=config.LLM_MAX_TOKENS)
            if not isinstance(batch_entities, list):
                raise ValueError(f"第 {idx + 1}/{total} 批返回格式异常（非数组），原始类型: {type(batch_entities).__name__}")

            async with build_lock:
                while len(job.step2_batch_results) <= idx:
                    job.step2_batch_results.append([])
                job.step2_batch_results[idx] = batch_entities
                job.step2_batches_done = idx + 1
                job.step2_failed_batch = -1
                job.step2_failed_reason = None
                job.update_time = datetime.now()
                save_build_job(job_id)
            logger.info(f"[{job_id}] Step2 第 {idx + 1}/{total} 批完成: {len(batch_entities)} 个实体")
            _emit_event(job_id, "batch_done", {
                "batch_idx": idx,
                "batches_done": idx + 1,
                "batches_total": total,
                "entities": batch_entities
            })

        # ---- 4. 全部成功后合并去重 + 聚合主要实体候选 ----
        _set_job_progress(job_id, 2, 96, "正在合并实体...")
        all_entities = [e for batch in job.step2_batch_results for e in batch]
        merged = _merge_entities(all_entities)
        # 聚合 is_primary_candidate=True 的实体名作为主要实体候选
        primary_candidates = [e.get("name", "") for e in merged if e.get("is_primary_candidate")]
        async with build_lock:
            job.step2_entities = merged
            job.primary_entity_candidates = primary_candidates
            job.step = max(job.step, 2)
            job.running_step = -1
            job.progress = 100
            job.progress_message = (
                f"实体提取完成，共 {len(merged)} 个实体"
                + (f"（{total} 批合并，{len(primary_candidates)} 个主要实体候选）" if total > 1
                   else f"（{len(primary_candidates)} 个主要实体候选）")
            )
            job.error_message = None
            job.update_time = datetime.now()
            save_build_job(job_id)
            save_build_jobs_index()
        _mark_stage_finished(job_id, 2)
        logger.info(f"[{job_id}] 后台实体提取完成: {len(merged)} 个实体（{total} 批合并）")
        _emit_event(job_id, "step_done", {
            "step": 2,
            "entities": merged,
            "primary_entity_candidates": primary_candidates,
            "total": len(merged)
        })
    except Exception as e:
        logger.error(f"[{job_id}] 后台实体提取失败: {e}")
        _mark_stage_finished(job_id, 2, success=False)
        async with build_lock:
            failed_idx = job.step2_batches_done
            job.running_step = -1
            job.progress = 0
            job.step2_failed_batch = failed_idx
            job.step2_failed_reason = str(e)[:200]
            job.error_message = f"第 {failed_idx + 1}/{job.step2_batches_total} 批失败: {str(e)[:150]}"
            job.progress_message = f"第 {failed_idx + 1}/{job.step2_batches_total} 批失败，可点击继续提取从该批续跑"
            job.update_time = datetime.now()
            save_build_job(job_id)
        _emit_event(job_id, "error", {"step": 2, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


def _group_entities_by_concept(entities: list, group_size: int) -> list:
    """按 instance_of 概念聚类后再按 group_size 切分，同概念实体尽量同组。

    同概念实体之间关系最密集，同组内能让 LLM 建立更完整的关系网。

    Args:
        entities: 已确认的实体清单
        group_size: 每组实体数上限

    Returns:
        实体分组列表，每个元素是该组的实体子集
    """
    by_concept = {}
    concept_order = []
    for e in entities:
        c = e.get("instance_of", "未分类") or "未分类"
        if c not in by_concept:
            by_concept[c] = []
            concept_order.append(c)
        by_concept[c].append(e)
    groups = []
    for c in concept_order:
        items = by_concept[c]
        for i in range(0, len(items), group_size):
            groups.append(items[i:i + group_size])
    return groups


async def _background_build_relations(job_id: str) -> None:
    """后台任务：Step 3 关系建模（LLM调用，支持实体分组 + 跨组关系补充 + 断点续作）。

    在已确认的实体间建立关系。实体过多时按 instance_of 概念分组，同组内关系完整后
    补充跨组关系。注入阶段提示词（stage_hints[3]）。
    """
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        _mark_stage_started(job_id, 3)
        entities = job.step2_entities or []
        if not entities:
            raise ValueError("实体清单为空，无法建立关系")

        # ---- 1. 判断续跑状态 ----
        is_group_resume = (job.step3_groups_total > 0
                           and job.step3_groups_done < job.step3_groups_total
                           and job.step3_failed_group >= 0)
        is_cross_resume = (job.step3_groups_total > 0
                           and job.step3_groups_done == job.step3_groups_total
                           and not job.step3_cross_group_done)
        if (not is_group_resume and not is_cross_resume
                and job.step3_relations and job.step3_failed_group < 0
                and (job.step3_cross_group_done or not job.step3_cross_group_failed)):
            _set_job_progress(job_id, -1, 100, "关系建模已完成")
            _mark_stage_finished(job_id, 3)
            return

        # ---- 2. 重建 groups（按 instance_of 概念分组）----
        if len(entities) <= config.STEP3_GROUP_THRESHOLD_ENTITIES:
            groups = [entities]
            total = 1
        else:
            groups = _group_entities_by_concept(entities, config.STEP3_GROUP_SIZE)
            total = len(groups)

        if job.step3_groups_total == 0:
            async with build_lock:
                job.step3_groups_total = total
                while len(job.step3_group_results) < total:
                    job.step3_group_results.append({"relations": []})
                job.update_time = datetime.now()
                save_build_job(job_id)
        elif job.step3_groups_total != total:
            logger.warning(
                f"[{job_id}] step3 分组数变化 {job.step3_groups_total}→{total}，"
                f"已成功 {job.step3_groups_done} 组结果保留，按新边界续跑"
            )
            async with build_lock:
                job.step3_groups_total = total
                while len(job.step3_group_results) < total:
                    job.step3_group_results.append({"relations": []})
                save_build_job(job_id)

        total = job.step3_groups_total
        stage_hint_3 = job.stage_hints.get(3, "") if job.stage_hints else ""

        # ---- 3. 分组续跑：从失败组开始跑剩余分组 ----
        if not is_cross_resume:
            start_idx = job.step3_groups_done if is_group_resume else 0
            logger.info(
                f"[{job_id}] Step3 关系建模：共 {total} 组，"
                f"{'续跑从第 ' + str(start_idx + 1) + ' 组' if is_group_resume else '首次从头'}开始"
            )
            for idx in range(start_idx, total):
                _set_job_progress(
                    job_id, 3,
                    10 + int(70 * idx / max(total, 1)),
                    f"正在建立关系（第 {idx + 1}/{total} 组）..." if total > 1 else "正在调用AI建立关系..."
                )
                group_entities = groups[idx] if idx < len(groups) else []
                messages = build_prompts.build_step3_group_messages(
                    group_entities, job.meta_relation_types,
                    group_idx=idx, total_groups=total, stage_hint=stage_hint_3
                )
                result = await _llm_json_async(messages, temperature=0.3, max_tokens=config.LLM_MAX_TOKENS)
                if not isinstance(result, dict):
                    raise ValueError(f"第 {idx + 1}/{total} 组返回格式异常（非对象），原始类型: {type(result).__name__}")
                group_relations = result.get("relations", [])
                if not isinstance(group_relations, list):
                    group_relations = []

                async with build_lock:
                    while len(job.step3_group_results) <= idx:
                        job.step3_group_results.append({"relations": []})
                    job.step3_group_results[idx] = {"relations": group_relations}
                    job.step3_groups_done = idx + 1
                    job.step3_failed_group = -1
                    job.step3_failed_reason = None
                    job.update_time = datetime.now()
                    save_build_job(job_id)
                logger.info(f"[{job_id}] Step3 第 {idx + 1}/{total} 组完成: {len(group_relations)} 条关系")
                _emit_event(job_id, "group_done", {
                    "group_idx": idx,
                    "groups_done": idx + 1,
                    "groups_total": total,
                    "relations": group_relations
                })

        # ---- 4. 合并组内关系 ----
        _set_job_progress(job_id, 3, 82, "正在合并关系...")
        all_relations = [r for g in job.step3_group_results for r in g.get("relations", [])]
        logger.info(f"[{job_id}] Step3 合并: {len(all_relations)} 组内关系（{total} 组）")

        # ---- 5. LLM 补充跨组关系（仅多组时执行）----
        if total > 1 and not job.step3_cross_group_done:
            _set_job_progress(job_id, 3, 88, "正在补充跨组关系...")
            entities_for_prompt = entities[:config.STEP3_CROSS_GROUP_ENTITY_BATCH]
            cross_messages = build_prompts.build_step3_cross_group_messages(
                entities_for_prompt, all_relations,
                job.meta_relation_types, stage_hint=stage_hint_3
            )
            try:
                cross_result = await _llm_json_async(cross_messages, temperature=0.3, max_tokens=config.LLM_MAX_TOKENS)
                if not isinstance(cross_result, dict):
                    raise ValueError(f"跨组关系补充返回格式异常（非对象），原始类型: {type(cross_result).__name__}")
                cross_relations = cross_result.get("relations", [])
                if not isinstance(cross_relations, list):
                    cross_relations = []
                logger.info(f"[{job_id}] Step3 跨组关系补充: {len(cross_relations)} 条")
                async with build_lock:
                    job.step3_cross_group_relations = cross_relations
                    job.step3_cross_group_done = True
                    job.step3_cross_group_failed = False
                    job.step3_cross_group_reason = None
                    job.update_time = datetime.now()
                    save_build_job(job_id)
                _emit_event(job_id, "cross_group_done", {"relations": cross_relations})
            except Exception as _e:
                logger.warning(f"[{job_id}] Step3 跨组关系补充失败，降级为仅组内关系: {_e}")
                async with build_lock:
                    job.step3_cross_group_failed = True
                    job.step3_cross_group_reason = str(_e)[:200]
                    job.step3_cross_group_done = False
                    job.update_time = datetime.now()
                    save_build_job(job_id)
        elif total <= 1:
            async with build_lock:
                job.step3_cross_group_done = True
                job.step3_cross_group_relations = []
                save_build_job(job_id)

        # ---- 6. 合并所有关系（组内 + 跨组）并去重 ----
        final_relations = _deduplicate_relations(all_relations + job.step3_cross_group_relations)
        cross_count = len(final_relations) - len(_deduplicate_relations(all_relations))

        async with build_lock:
            job.step3_relations = final_relations
            job.step = max(job.step, 3)
            job.running_step = -1
            job.progress = 100
            if total > 1:
                job.progress_message = (
                    f"关系建模完成，共 {len(final_relations)} 条关系"
                    f"（{total} 组合并，含 {cross_count} 条跨组关系）"
                )
            else:
                job.progress_message = f"关系建模完成，共 {len(final_relations)} 条关系"
            job.error_message = None
            job.update_time = datetime.now()
            save_build_job(job_id)
            save_build_jobs_index()
        _mark_stage_finished(job_id, 3)
        logger.info(
            f"[{job_id}] 后台关系建模完成: {len(final_relations)} 条关系"
            + (f"（含 {cross_count} 跨组）" if total > 1 else "")
        )
        _emit_event(job_id, "step_done", {
            "step": 3,
            "relations": final_relations,
            "total": len(final_relations)
        })
    except Exception as e:
        logger.error(f"[{job_id}] 后台关系建模失败: {e}")
        _mark_stage_finished(job_id, 3, success=False)
        async with build_lock:
            job.running_step = -1
            job.progress = 0
            if job.step3_groups_done < job.step3_groups_total:
                failed_idx = job.step3_groups_done
                job.step3_failed_group = failed_idx
                job.step3_failed_reason = str(e)[:200]
                job.error_message = f"第 {failed_idx + 1}/{job.step3_groups_total} 组失败: {str(e)[:150]}"
                job.progress_message = f"第 {failed_idx + 1}/{job.step3_groups_total} 组失败，可点击继续从该组续跑"
            else:
                job.step3_cross_group_failed = True
                job.step3_cross_group_reason = str(e)[:200]
                job.error_message = f"跨组关系补充失败: {str(e)[:150]}"
                job.progress_message = "跨组关系补充失败，可点击继续重新补充跨组关系"
            job.update_time = datetime.now()
            save_build_job(job_id)
        _emit_event(job_id, "error", {"step": 3, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


async def _background_verify_and_report(job_id: str) -> None:
    """后台任务：Step 4 验证 + 报告生成（LLM 自检）。

    LLM 逐项检查实体/属性/关系是否可溯源，标记存疑项，生成简报。
    注入阶段提示词（stage_hints[4]）。验证结果存入 step4_verification/step4_report。
    本体生成在用户确认（build_confirm_step4）时触发，不在此任务内。
    """
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        _mark_stage_started(job_id, 4)
        concepts = job.step1_concepts or []
        entities = job.step2_entities or []
        relations = job.step3_relations or []
        if not entities:
            raise ValueError("实体清单为空，无法验证")

        _set_job_progress(job_id, 4, 20, "正在准备验证数据...")
        # 截断原文防止 prompt 过长
        doc_text = job.source_text[:config.VERIFICATION_MAX_DOC_CHARS]
        stage_hint_4 = job.stage_hints.get(4, "") if job.stage_hints else ""

        _set_job_progress(job_id, 4, 40, "正在调用AI做自检验证...")
        messages = build_prompts.build_step4_verification_messages(
            concepts, entities, relations, doc_text, stage_hint=stage_hint_4
        )
        result = await _llm_json_async(messages, temperature=0.3, max_tokens=config.LLM_MAX_TOKENS)
        if not isinstance(result, dict):
            raise ValueError(f"验证返回格式异常（非对象），原始类型: {type(result).__name__}")

        verification = {
            "verified_count": result.get("verified_count", 0),
            "suspect_count": result.get("suspect_count", 0),
            "suspects": result.get("suspects", []) if isinstance(result.get("suspects"), list) else [],
        }
        report = result.get("report", "") or ""

        async with build_lock:
            job.step4_verification = verification
            job.step4_report = report
            job.step = max(job.step, 4)
            job.running_step = -1
            job.progress = 100
            job.progress_message = (
                f"验证完成：{verification['verified_count']} 项通过，"
                f"{verification['suspect_count']} 项存疑"
            )
            job.error_message = None
            job.update_time = datetime.now()
            save_build_job(job_id)
            save_build_jobs_index()
        _mark_stage_finished(job_id, 4)
        logger.info(
            f"[{job_id}] 后台验证完成: {verification['verified_count']} 通过, "
            f"{verification['suspect_count']} 存疑"
        )
        _emit_event(job_id, "step_done", {
            "step": 4,
            "verification": verification,
            "report": report
        })
    except Exception as e:
        logger.error(f"[{job_id}] 后台验证失败: {e}")
        _mark_stage_finished(job_id, 4, success=False)
        async with build_lock:
            job.running_step = -1
            job.progress = 0
            job.error_message = str(e)[:200]
            job.progress_message = f"验证失败: {str(e)[:150]}"
            job.update_time = datetime.now()
            save_build_job(job_id)
        _emit_event(job_id, "error", {"step": 4, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


def _generate_formal_ontology(job_id: str) -> str:
    """从已确认的 step1-3 数据生成正式本体（step4 确认时调用）。

    五阶段数据 → 正式本体：
    - step1_concepts → ConceptType（含 entity_type/property_schema/color）
    - step2_entities → Entity（instance_of = 概念名 → 概念ID）
    - step3_relations → Relation（source/target = 实体名 → 实体ID）
    - step4_report 挂到本体元信息（description 补充）

    Phase 2 仅生成单本体（多本体实例化留待 Phase 3）。

    Returns:
        新生成的本体 ID
    """
    job = build_jobs_db.get(job_id)
    if not job:
        raise ValueError("构建任务不存在")

    now = datetime.now()
    new_oid = f"ont_{uuid.uuid4().hex[:8]}"
    ont = OntologyModel(
        id=new_oid, name=job.name, description=job.description, version="1.0.0",
        entity_types=[EntityType(**t) for t in job.meta_entity_types],
        relation_types=[RelationType(**t) for t in job.meta_relation_types],
        create_time=now, update_time=now, status="活跃",
        schema_version=SCHEMA_VERSION,
    )

    # ── step1_concepts → ConceptType ──
    concept_map = {}  # concept_name -> concept_id
    new_concepts: List[ConceptType] = []
    for cd in (job.step1_concepts or []):
        cname = cd.get("name", "")
        if not cname:
            continue
        cid = f"concept_{uuid.uuid4().hex[:8]}"
        concept_map[_normalize_name(cname)] = cid
        # property_schema 转 PropertySchema
        ps_list = []
        for ps in (cd.get("property_schema") or []):
            if isinstance(ps, dict):
                try:
                    ps_list.append(PropertySchema(
                        name=ps.get("name", ""),
                        category=ps.get("category", "descriptive"),
                        data_type=ps.get("data_type", "string"),
                        unit=ps.get("unit", ""),
                        required=bool(ps.get("required", False)),
                        description=ps.get("description", ""),
                    ))
                except Exception:
                    pass
        new_concepts.append(ConceptType(
            id=cid, ontology_id=new_oid, name=cname,
            entity_type=cd.get("entity_type", ""),
            description=cd.get("description", ""),
            color=cd.get("color") or _derive_concept_color(cd.get("entity_type", ""), job.meta_entity_types),
            property_schema=ps_list,
            source_snippet=cd.get("source_snippet", ""),
            create_time=now, update_time=now,
        ))

    # ── step2_entities → Entity（instance_of = 概念名 → 概念ID）──
    ent_map = {}  # entity_name -> entity_id
    new_entities: List[Entity] = []
    # 用户勾选的主要实体（Phase 3 用于多本体拆分；Phase 2 仅标记 is_primary）
    primary_selected = set(_normalize_name(n) for n in (job.primary_entity_selected or []))
    for ed in (job.step2_entities or []):
        ename = ed.get("name", "")
        if not ename:
            continue
        new_eid = f"ent_{uuid.uuid4().hex[:8]}"
        ent_map[_normalize_name(ename)] = new_eid
        # instance_of: 概念名 → 概念ID
        inst_name = ed.get("instance_of", "")
        instance_of = concept_map.get(_normalize_name(inst_name), "") if inst_name else ""
        props = _parse_properties(ed.get("properties", []), new_eid)
        is_primary = _normalize_name(ename) in primary_selected
        new_entities.append(Entity(
            id=new_eid, ontology_id=new_oid, name=ename,
            instance_of=instance_of,
            is_primary=is_primary,
            properties=props,
            source_snippet=ed.get("source_snippet", ""),
            create_time=now, update_time=now,
        ))

    # ── step3_relations → Relation ──
    new_relations: List[Relation] = []
    for rd in (job.step3_relations or []):
        src = ent_map.get(_normalize_name(rd.get("source", "")))
        tgt = ent_map.get(_normalize_name(rd.get("target", "")))
        if not src or not tgt:
            continue
        rel_id = f"rel_{uuid.uuid4().hex[:8]}"
        props = _parse_properties(rd.get("properties", []), rel_id)
        new_relations.append(Relation(
            id=rel_id, ontology_id=new_oid,
            source_id=src, target_id=tgt,
            relation_type=rd.get("relation_type", "关联"),
            properties=props, weight=rd.get("weight", 1.0),
            source_snippet=rd.get("source_snippet", ""),
            create_time=now,
        ))

    # 持久化到内存 + 文件
    ontologies_db[new_oid] = ont
    concepts_db[new_oid] = new_concepts
    entities_db[new_oid] = new_entities
    relations_db[new_oid] = new_relations
    save_ontology(new_oid)
    save_index()
    return new_oid


# ---------- 持久化 ----------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
INDEX_FILE = os.path.join(DATA_DIR, 'ontologies_index.json')
LOCK_DIR = os.path.join(DATA_DIR, '.locks')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOCK_DIR, exist_ok=True)

# 用户本体数据目录：构建/编辑生成的运行时数据统一存放于此（已 gitignore，避免误提交）
USER_ONTOLOGIES_DIR = os.path.join(DATA_DIR, 'user_ontologies')
os.makedirs(USER_ONTOLOGIES_DIR, exist_ok=True)


def _ontology_file(ontology_id: str) -> str:
    """本体数据文件写入路径（新生成的本体统一存放在 user_ontologies 目录）。"""
    return os.path.join(USER_ONTOLOGIES_DIR, f'ontology_{ontology_id}.json')


def _resolve_ontology_file(ontology_id: str) -> str:
    """定位本体数据文件用于读取/删除：优先新目录，兼容 data 根目录下已入库的历史本体文件。"""
    new_path = _ontology_file(ontology_id)
    if os.path.exists(new_path):
        return new_path
    legacy_path = os.path.join(DATA_DIR, f'ontology_{ontology_id}.json')
    if os.path.exists(legacy_path):
        return legacy_path
    return new_path


def _lock_path(name: str) -> str:
    """文件锁路径。"""
    return os.path.join(LOCK_DIR, f'{name}.lock')


def atomic_write_json(path: str, data: Any) -> None:
    """原子写入 JSON：先校验可序列化，写临时文件，备份旧文件，再原子替换。

    复用 knowledge-service 的持久化模式，失败时清理临时文件并保留旧文件。

    Args:
        path: 目标文件路径
        data: 待序列化数据
    """
    # 先校验可序列化，避免写到一半失败
    json.dumps(data, ensure_ascii=False, default=str)

    dir_path = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        # 备份旧文件
        if os.path.exists(path):
            if os.path.exists(path + '.bak'):
                os.remove(path + '.bak')
            os.rename(path, path + '.bak')
        # 原子替换
        os.rename(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def load_json_with_backup(path: str, default: Any) -> Any:
    """读取 JSON，主文件失败时尝试从 .bak 恢复。

    Args:
        path: 文件路径
        default: 文件不存在或恢复失败时的默认值

    Returns:
        解析后的数据或默认值
    """
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"读取文件失败 {path}: {e}，尝试从备份恢复")
        bak = path + '.bak'
        if os.path.exists(bak):
            try:
                with open(bak, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e2:
                logger.error(f"备份恢复也失败 {bak}: {e2}")
        return default


def _parse_json_arg(value: str, default: Any) -> Any:
    """解析前端传入的 JSON 字符串参数，失败或为空时返回默认值。"""
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _parse_properties(props_input: Any, entity_id: str = "") -> List[Property]:
    """解析前端传入的 properties，兼容 Dict（旧）和 List（新）两种格式。

    - Dict[str, str]：旧格式，自动转为 List[Property]（category=descriptive）
    - List[dict]：新格式，逐项构造 Property（缺失字段补默认值）
    - None/空：返回空列表

    Args:
        props_input: 前端传入的属性数据（已 JSON 解码）
        entity_id: 所属实体ID（用于回填 property.entity_id）

    Returns:
        结构化属性列表
    """
    if not props_input:
        return []
    now = datetime.now()
    # 旧格式 Dict[str,str] → List[Property]
    if isinstance(props_input, dict):
        result = []
        for name, value in props_input.items():
            result.append(Property(
                id=f"prop_{uuid.uuid4().hex[:8]}",
                entity_id=entity_id,
                name=name, value=value,
                category="descriptive", data_type="string",
                create_time=now, update_time=now,
            ))
        return result
    # 新格式 List[dict] → List[Property]
    if isinstance(props_input, list):
        result = []
        for item in props_input:
            if not isinstance(item, dict):
                continue
            pid = item.get("id") or f"prop_{uuid.uuid4().hex[:8]}"
            # 解析 history（兼容 dict 列表）
            raw_history = item.get("history", []) or []
            history = []
            for h in raw_history:
                if isinstance(h, dict):
                    history.append(PropertyHistoryEntry(
                        value=h.get("value"),
                        recorded_at=h.get("recorded_at"),
                        source_snippet=h.get("source_snippet", ""),
                        note=h.get("note", ""),
                    ))
            # 解析 verification
            raw_ver = item.get("verification")
            verification = None
            if isinstance(raw_ver, dict):
                verification = PropertyVerification(
                    status=raw_ver.get("status", "verified"),
                    reason=raw_ver.get("reason", ""),
                )
            result.append(Property(
                id=pid,
                entity_id=entity_id,
                name=item.get("name", ""),
                value=item.get("value"),
                category=item.get("category", "descriptive"),
                data_type=item.get("data_type", "string"),
                unit=item.get("unit", ""),
                source_snippet=item.get("source_snippet", ""),
                bindings=item.get("bindings", {}) or {},
                history=history,
                verification=verification,
                create_time=item.get("create_time", now) or now,
                update_time=now,
            ))
        return result
    return []


# ---------- 内存数据（按 ontology_id 组织，实现多本体隔离）----------
# ontologies_db: ontology_id -> OntologyModel
# concepts_db: ontology_id -> List[ConceptType]  （概念层：类型定义节点）
# entities_db: ontology_id -> List[Entity]
# relations_db: ontology_id -> List[Relation]
ontologies_db: Dict[str, OntologyModel] = {}
concepts_db: Dict[str, List[ConceptType]] = {}
entities_db: Dict[str, List[Entity]] = {}
relations_db: Dict[str, List[Relation]] = {}

# 协程锁：保护内存全局变量，防 FastAPI 异步并发竞态
db_lock = __import__('asyncio').Lock()


def save_ontology(ontology_id: str) -> None:
    """持久化单个本体（元信息 + 概念 + 实体 + 关系）到独立文件。"""
    ont = ontologies_db.get(ontology_id)
    if not ont:
        return
    data = {
        'ontology': ont.dict(),
        'concepts': [c.dict() for c in concepts_db.get(ontology_id, [])],
        'entities': [e.dict() for e in entities_db.get(ontology_id, [])],
        'relations': [r.dict() for r in relations_db.get(ontology_id, [])],
    }
    with FileLock(_lock_path(f'ontology_{ontology_id}')):
        atomic_write_json(_ontology_file(ontology_id), data)


def save_index() -> None:
    """持久化本体列表索引。"""
    data = [o.dict() for o in ontologies_db.values()]
    with FileLock(_lock_path('index')):
        atomic_write_json(INDEX_FILE, data)


# ---------- 构建任务持久化 ----------
BUILD_JOBS_DIR = os.path.join(DATA_DIR, 'build_jobs')
BUILD_JOBS_INDEX = os.path.join(BUILD_JOBS_DIR, 'index.json')
os.makedirs(BUILD_JOBS_DIR, exist_ok=True)

# 内存字典：job_id -> BuildJob
build_jobs_db: Dict[str, BuildJob] = {}
# 协程锁：保护 build_jobs_db 并发写
build_lock = __import__('asyncio').Lock()


def _build_job_file(job_id: str) -> str:
    """构建任务数据文件路径。job_id 已含 job_ 前缀。"""
    return os.path.join(BUILD_JOBS_DIR, f'{job_id}.json')


def save_build_job(job_id: str) -> None:
    """持久化单个构建任务。"""
    job = build_jobs_db.get(job_id)
    if not job:
        return
    with FileLock(_lock_path(f'build_job_{job_id}')):
        atomic_write_json(_build_job_file(job_id), job.dict())


def save_build_jobs_index() -> None:
    """持久化构建任务索引。"""
    data = [j.dict() for j in build_jobs_db.values()]
    with FileLock(_lock_path('build_jobs_index')):
        atomic_write_json(BUILD_JOBS_INDEX, data)


def load_build_jobs() -> None:
    """启动时加载所有构建任务到内存，并重试卡死的后台任务。"""
    global build_jobs_db
    build_jobs_db = {}
    index = load_json_with_backup(BUILD_JOBS_INDEX, [])
    if not isinstance(index, list):
        index = []
    for item in index:
        try:
            job = BuildJob(**item)
            build_jobs_db[job.id] = job
        except Exception as e:
            logger.warning(f"构建任务解析失败，跳过: {e}")
    logger.info(f"加载完成: {len(build_jobs_db)} 个构建任务")

    # 重试卡死的后台任务（服务重启前未完成的）
    for job in list(build_jobs_db.values()):
        if job.running_step == -1 or job.status == "completed":
            continue
        logger.info(f"检测到卡死任务 {job.id} (running_step={job.running_step})，将自动重试")
        job.running_step = -1
        job.progress = 0
        job.error_message = "服务重启中断，已自动重试"
        save_build_job(job.id)
        # 根据 confirmed 状态判断该重试哪一步
        # 延迟启动，等事件循环就绪后在 startup 事件中触发
        _pending_retries.append(job.id)


# 启动时待重试的任务 ID 列表（在 startup 事件中处理）
_pending_retries: List[str] = []


def _get_job_or_404(job_id: str) -> BuildJob:
    """获取构建任务，不存在则抛 404。"""
    job = build_jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="构建任务不存在")
    return job


def load_db() -> None:
    """启动时加载所有本体数据到内存。

    加载前检测 schema_version，若存在 v1 数据则自动迁移：
    1. 备份整个 data 目录（仅首次迁移时备份一次）
    2. 逐个本体调用 migrate_ontology_dict 迁移
    3. 迁移后回写文件
    4. 加载到内存
    """
    global ontologies_db, concepts_db, entities_db, relations_db
    ontologies_db = {}
    concepts_db = {}
    entities_db = {}
    relations_db = {}

    index = load_json_with_backup(INDEX_FILE, [])
    if not isinstance(index, list):
        index = []

    # ── 迁移检测：扫描所有本体文件，判断是否需要迁移 ──
    needs_migration = False
    for item in index:
        if not isinstance(item, dict):
            continue
        if item.get("schema_version", 1) < SCHEMA_VERSION:
            needs_migration = True
            break
    # 即使索引项标记了 v2，本体文件内部可能仍是 v1（索引与文件不同步的防御性检查）
    if not needs_migration:
        for item in index:
            if not isinstance(item, dict):
                continue
            ont_id = item.get("id")
            if not ont_id:
                continue
            data = load_json_with_backup(_resolve_ontology_file(ont_id), None)
            if data is None:
                continue
            ont_meta = data.get("ontology", {}) if isinstance(data, dict) else {}
            if isinstance(ont_meta, dict) and ont_meta.get("schema_version", 1) < SCHEMA_VERSION:
                needs_migration = True
                break

    if needs_migration:
        try:
            backup_data_dir(DATA_DIR)
            logger.info("检测到旧格式数据，已启动自动迁移")
        except Exception as e:
            logger.error(f"备份 data 目录失败，中止迁移: {e}")
            raise

    # ── 逐个加载（必要时迁移）──
    migrated_count = 0
    for item in index:
        if not isinstance(item, dict):
            continue
        try:
            ont = OntologyModel(**item)
        except Exception as e:
            logger.warning(f"索引项解析失败，跳过: {e}")
            continue

        # 读取本体数据文件
        data = load_json_with_backup(_resolve_ontology_file(ont.id), {'entities': [], 'relations': []})
        ont_meta = data.get('ontology', {}) if isinstance(data, dict) else {}

        # 数据文件缺失或 ontology 元数据不完整时，以索引条目为准，
        # 避免迁移出残缺元数据（仅 schema_version）导致后续构造失败
        if not isinstance(ont_meta, dict) or not ont_meta.get('id'):
            data = dict(data) if isinstance(data, dict) else {}
            data['ontology'] = dict(item)
            ont_meta = data['ontology']

        data_schema_version = ont_meta.get('schema_version', 1) if isinstance(ont_meta, dict) else 1

        # 需要迁移：调用迁移函数，回写文件
        if data_schema_version < SCHEMA_VERSION:
            try:
                data = migrate_ontology_dict(data, ont.id)
                # 回写迁移后的数据
                with FileLock(_lock_path(f'ontology_{ont.id}')):
                    atomic_write_json(_ontology_file(ont.id), data)
                migrated_count += 1
            except Exception as e:
                logger.error(f"本体 {ont.id} 迁移失败，跳过: {e}")
                continue

        # 重新从迁移后的数据构造 OntologyModel（含 schema_version）
        # 以 index 条目为基础，用 data.ontology 覆盖（data.ontology 可能只有 schema_version）
        merged_ontology = dict(item)  # 始终保留 index 中的 id/name/create_time 等
        onto_from_data = data.get('ontology', {}) if isinstance(data, dict) else {}
        if isinstance(onto_from_data, dict):
            merged_ontology.update(onto_from_data)
        ont = OntologyModel(**merged_ontology)
        ontologies_db[ont.id] = ont

        # 加载概念
        conps = []
        for c in data.get('concepts', []):
            try:
                conps.append(ConceptType(**c))
            except Exception as e2:
                logger.warning(f"概念解析失败，跳过: {e2}")
        concepts_db[ont.id] = conps

        # 加载实体
        ents = []
        for e in data.get('entities', []):
            try:
                ents.append(Entity(**e))
            except Exception as e2:
                logger.warning(f"实体解析失败，跳过: {e2}")
        entities_db[ont.id] = ents

        # 加载关系
        rels = []
        for r in data.get('relations', []):
            try:
                rels.append(Relation(**r))
            except Exception as e2:
                logger.warning(f"关系解析失败，跳过: {e2}")
        relations_db[ont.id] = rels

    if migrated_count > 0:
        # 迁移后回写索引（更新 schema_version）
        save_index()
        logger.info(f"迁移完成：{migrated_count} 个本体已升级到 schema_version={SCHEMA_VERSION}")

    logger.info(f"加载完成: {len(ontologies_db)} 个本体, "
                f"{sum(len(v) for v in concepts_db.values())} 个概念, "
                f"{sum(len(v) for v in entities_db.values())} 个实体, "
                f"{sum(len(v) for v in relations_db.values())} 条关系")


def _count_entities(ontology_id: str) -> int:
    """统计某本体的实体数。"""
    return len(entities_db.get(ontology_id, []))


def _count_concepts(ontology_id: str) -> int:
    """统计某本体的概念数。"""
    return len(concepts_db.get(ontology_id, []))


def _count_relations(ontology_id: str) -> int:
    """统计某本体的关系数。"""
    return len(relations_db.get(ontology_id, []))


def _ontology_summary(ont: OntologyModel) -> Dict[str, Any]:
    """返回本体摘要（含实时计数）。"""
    d = ont.dict()
    d['concepts_count'] = _count_concepts(ont.id)
    d['entities_count'] = _count_entities(ont.id)
    d['relations_count'] = _count_relations(ont.id)
    return d


def _get_ontology_or_404(ontology_id: str) -> OntologyModel:
    """获取本体，不存在则抛 404。"""
    ont = ontologies_db.get(ontology_id)
    if not ont:
        raise HTTPException(status_code=404, detail="本体模型不存在")
    return ont


def _find_concept(ontology_id: str, concept_id: str) -> Optional[ConceptType]:
    """在本体内查找概念。"""
    for c in concepts_db.get(ontology_id, []):
        if c.id == concept_id:
            return c
    return None


def _find_entity(ontology_id: str, entity_id: str) -> Optional[Entity]:
    """在本体内查找实体。"""
    for e in entities_db.get(ontology_id, []):
        if e.id == entity_id:
            return e
    return None


def _find_relation(ontology_id: str, relation_id: str) -> Optional[Relation]:
    """在本体内查找关系。"""
    for r in relations_db.get(ontology_id, []):
        if r.id == relation_id:
            return r
    return None


def _find_property(entity: Entity, property_id: str) -> Optional[Property]:
    """在实体的属性列表中查找属性。"""
    for p in entity.properties:
        if p.id == property_id:
            return p
    return None


def _entity_dict_with_type(entity: Entity, ontology_id: str) -> Dict[str, Any]:
    """返回实体 dict，确保 type 字段有值（从 instance_of 推导）。

    兼容前端：前端多处用 entity.type 做颜色匹配和类型显示（getEntityTypeColor、
    entityTypeMap 等）。迁移后 type 为空串，需从 instance_of → ConceptType.entity_type
    推导填充，避免前端全回退蓝色。

    若 instance_of 也为空（极端兼容场景），回退到 "未分类"。
    """
    d = entity.dict()
    if not d.get("type"):
        concept = _find_concept(ontology_id, entity.instance_of)
        if concept:
            d["type"] = concept.entity_type or concept.name
        else:
            d["type"] = "未分类"
    return d


def _validate_instance_of(ontology_id: str, instance_of: str) -> None:
    """校验 instance_of 指向本体内存在的 ConceptType。

    迁移后的旧数据可能 instance_of 为空（防御性放行）；
    新建实体必须指向有效概念。
    """
    if not instance_of:
        return  # 空值放行（兼容旧数据）
    if _find_concept(ontology_id, instance_of):
        return
    raise HTTPException(
        status_code=400,
        detail=f"概念ID '{instance_of}' 在本体内不存在"
    )


def _validate_entity_type(ontology_id: str, entity_type: str) -> None:
    """校验实体类型在本体元模型定义内（向后兼容，保留给旧 API 使用）。

    新 API 应使用 instance_of 指向 ConceptType，此函数仅用于元模型类型校验。
    """
    ont = ontologies_db.get(ontology_id)
    if not ont:
        return
    allowed = {t.name for t in ont.entity_types}
    if allowed and entity_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"实体类型 '{entity_type}' 不在本体允许类型内: {sorted(allowed)}"
        )


def _validate_relation_type(ontology_id: str, relation_type: str) -> None:
    """校验关系类型在本体元模型定义内。"""
    ont = ontologies_db.get(ontology_id)
    if not ont:
        return
    allowed = {t.name for t in ont.relation_types}
    if allowed and relation_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"关系类型 '{relation_type}' 不在本体允许类型内: {sorted(allowed)}"
        )


# ---------- 示例数据 ----------
def _seed_property(prop_id: str, entity_id: str, name: str, value: Any,
                   category: str, unit: str = "", data_type: str = "string",
                   source_snippet: str = "") -> Property:
    """构造 seed 用的结构化属性对象。"""
    now = datetime.now()
    return Property(
        id=prop_id, entity_id=entity_id, name=name, value=value,
        category=category, data_type=data_type, unit=unit,
        source_snippet=source_snippet,
        create_time=now, update_time=now,
    )


def seed_if_empty() -> None:
    """首次启动且无任何本体时，写入作战指挥示例本体（新格式 v2）。

    与 v1 的关键差异：
    - 命中率/摧毁率/战损率 从独立实体改为「打击能力/生存能力」的指标型属性
    - 新增概念层（ConceptType），每个实体 instance_of 指向概念
    - 属性使用结构化 Property 对象，区分描述型/指标型
    """
    if ontologies_db:
        return

    oid = "ont_seed_combat"
    now = datetime.now()
    ont = OntologyModel(
        id=oid,
        name="作战效能评估本体",
        description="作战指挥场景的示例本体，包含作战效能、打击/生存/保障能力及相关指标概念",
        version="1.0.0",
        entity_types=[EntityType(**t) for t in DEFAULT_ENTITY_TYPES],
        relation_types=[RelationType(**t) for t in DEFAULT_RELATION_TYPES],
        create_time=now,
        update_time=now,
        status="活跃",
        schema_version=SCHEMA_VERSION,
    )
    ontologies_db[oid] = ont

    # ── 概念层（ConceptType）：类型定义 ──
    # 每个概念属于元模型的一个 entity_type，携带属性骨架
    seed_concepts = [
        # (name, entity_type, description, color, property_schema)
        ("能力维度", "概念", "作战能力的分类维度", "#5470c6", [
            PropertySchema(name="权重", category="metric", data_type="number", unit="", description="该能力在综合评估中的权重"),
            PropertySchema(name="定义", category="descriptive", data_type="string"),
        ]),
        ("参战方", "实体", "参与作战的部队", "#91cc75", [
            PropertySchema(name="阵营", category="descriptive", data_type="string"),
            PropertySchema(name="编制类型", category="descriptive", data_type="string"),
        ]),
        ("装备", "实体", "武器装备平台", "#91cc75", [
            PropertySchema(name="类别", category="descriptive", data_type="string"),
            PropertySchema(name="状态", category="descriptive", data_type="string"),
            PropertySchema(name="命中率", category="metric", data_type="number", unit="%", description="命中/射击*100%"),
            PropertySchema(name="摧毁率", category="metric", data_type="number", unit="%", description="摧毁/命中*100%"),
        ]),
        ("战场事件", "事件", "作战过程中的事件", "#ee6666", [
            PropertySchema(name="单位", category="descriptive", data_type="string"),
            PropertySchema(name="阶段", category="descriptive", data_type="string"),
            PropertySchema(name="战损率", category="metric", data_type="number", unit="%", description="损失/总数*100%"),
        ]),
    ]
    concept_map = {}  # name -> id
    conps = []
    for idx, (cname, etype, desc, color, pschema) in enumerate(seed_concepts):
        cid = f"concept_seed_{idx:02d}"
        concept_map[cname] = cid
        conps.append(ConceptType(
            id=cid, ontology_id=oid, name=cname, entity_type=etype,
            description=desc, color=color, property_schema=pschema,
            create_time=now, update_time=now,
        ))
    concepts_db[oid] = conps

    # ── 实体层（Entity）：具体实例 ──
    # 命中率/摧毁率/战损率 作为指标型属性融入对应实体，不再作为独立实体
    seed_entities = [
        # (name, instance_of概念名, is_primary, properties)
        ("作战效能", "能力维度", True, [
            _seed_property("prop_seed_00", "ent_seed_00", "定义", "综合评估指标", "descriptive"),
            _seed_property("prop_seed_01", "ent_seed_00", "权重", "1.0", "metric", data_type="number"),
            _seed_property("prop_seed_02", "ent_seed_00", "重要性", "高", "descriptive"),
        ]),
        ("打击能力", "能力维度", False, [
            _seed_property("prop_seed_10", "ent_seed_01", "定义", "武器打击效果", "descriptive"),
            _seed_property("prop_seed_11", "ent_seed_01", "权重", "0.4", "metric", data_type="number"),
        ]),
        ("生存能力", "能力维度", False, [
            _seed_property("prop_seed_20", "ent_seed_02", "定义", "存活概率", "descriptive"),
            _seed_property("prop_seed_21", "ent_seed_02", "权重", "0.3", "metric", data_type="number"),
        ]),
        ("保障能力", "能力维度", False, [
            _seed_property("prop_seed_30", "ent_seed_03", "定义", "后勤保障水平", "descriptive"),
            _seed_property("prop_seed_31", "ent_seed_03", "权重", "0.3", "metric", data_type="number"),
        ]),
        ("红方部队", "参战方", False, [
            _seed_property("prop_seed_40", "ent_seed_04", "阵营", "红方", "descriptive"),
            _seed_property("prop_seed_41", "ent_seed_04", "编制类型", "合成营", "descriptive"),
        ]),
        ("蓝方部队", "参战方", False, [
            _seed_property("prop_seed_50", "ent_seed_05", "阵营", "蓝方", "descriptive"),
            _seed_property("prop_seed_51", "ent_seed_05", "编制类型", "机步连", "descriptive"),
        ]),
        ("武器平台", "装备", False, [
            _seed_property("prop_seed_60", "ent_seed_06", "类别", "装备", "descriptive"),
            _seed_property("prop_seed_61", "ent_seed_06", "状态", "在役", "descriptive"),
            _seed_property("prop_seed_62", "ent_seed_06", "命中率", "85", "metric", unit="%", data_type="number",
                           source_snippet="武器平台命中率约85%"),
            _seed_property("prop_seed_63", "ent_seed_06", "摧毁率", "70", "metric", unit="%", data_type="number",
                           source_snippet="武器平台摧毁率约70%"),
        ]),
        ("弹药消耗", "战场事件", False, [
            _seed_property("prop_seed_70", "ent_seed_07", "单位", "发", "descriptive"),
            _seed_property("prop_seed_71", "ent_seed_07", "阶段", "全期", "descriptive"),
            _seed_property("prop_seed_72", "ent_seed_07", "战损率", "12", "metric", unit="%", data_type="number",
                           source_snippet="本次作战战损率约12%"),
        ]),
    ]
    ent_map = {}  # name -> id
    ents = []
    for idx, (name, concept_name, is_primary, props) in enumerate(seed_entities):
        eid = f"ent_seed_{idx:02d}"
        ent_map[name] = eid
        ents.append(Entity(
            id=eid, ontology_id=oid, name=name,
            instance_of=concept_map.get(concept_name, ""),
            is_primary=is_primary,
            properties=props,
            create_time=now, update_time=now,
        ))
    entities_db[oid] = ents

    # ── 关系层（Relation）：层级包含 + 影响关系 ──
    # 去掉了指向"命中率/摧毁率/战损率"的边（它们现在是属性，不再是实体）
    seed_relations = [
        ("作战效能", "包含", "打击能力", 1.0),
        ("作战效能", "包含", "生存能力", 1.0),
        ("作战效能", "包含", "保障能力", 1.0),
        ("红方部队", "关联", "武器平台", 0.6),
        ("蓝方部队", "关联", "武器平台", 0.6),
        ("红方部队", "关联", "蓝方部队", 0.9),
        ("弹药消耗", "衡量", "打击能力", 0.6),
    ]
    rels = []
    for idx, (src, rtype, tgt, w) in enumerate(seed_relations):
        if src not in ent_map or tgt not in ent_map:
            continue
        rels.append(Relation(
            id=f"rel_seed_{idx:02d}", ontology_id=oid,
            source_id=ent_map[src], target_id=ent_map[tgt],
            relation_type=rtype, weight=w,
            create_time=now,
        ))
    relations_db[oid] = rels

    save_ontology(oid)
    save_index()
    logger.info(f"已写入示例本体: {ont.name} ({len(conps)} 概念, {len(ents)} 实体, {len(rels)} 关系)")


# 启动时加载数据并按需 seed
load_db()
seed_if_empty()
load_build_jobs()


@app.on_event("startup")
async def _retry_pending_build_jobs():
    """服务启动时重试卡死的构建任务（事件循环就绪后执行）。

    根据各阶段 confirmed 状态判断该重试哪一步：
    - step3 已确认 + step4 未完成 → 重试 step4（验证+报告）
    - step2 已确认 + step3 未完成 → 重试 step3（关系建模）
    - step1 已确认 + step2 未完成 → 重试 step2（实体提取）
    - meta 已确认 + step1 未完成 → 重试 step1（概念提取）
    """
    if not _pending_retries:
        return
    # 延迟 2 秒，确保服务完全就绪
    await asyncio.sleep(2)
    for job_id in _pending_retries:
        job = build_jobs_db.get(job_id)
        if not job or job.status == "completed":
            continue
        # 根据 confirmed 状态判断该重试哪一步（五阶段优先级从后往前）
        if job.step3_confirmed and not job.step4_confirmed:
            logger.info(f"[{job_id}] 自动重试 step4（验证+报告）")
            _set_job_progress(job_id, 4, 5, "服务重启后自动重试...")
            task = asyncio.create_task(_background_verify_and_report(job_id))
            _background_tasks[job_id] = task
        elif job.step2_confirmed and not job.step3_confirmed:
            logger.info(f"[{job_id}] 自动重试 step3（关系建模）")
            _set_job_progress(job_id, 3, 5, "服务重启后自动重试...")
            task = asyncio.create_task(_background_build_relations(job_id))
            _background_tasks[job_id] = task
        elif job.step1_confirmed and not job.step2_confirmed:
            logger.info(f"[{job_id}] 自动重试 step2（实体提取）")
            _set_job_progress(job_id, 2, 5, "服务重启后自动重试...")
            task = asyncio.create_task(_background_extract_entities(job_id))
            _background_tasks[job_id] = task
        elif job.meta_confirmed and not job.step1_confirmed:
            logger.info(f"[{job_id}] 自动重试 step1（概念提取）")
            _set_job_progress(job_id, 1, 5, "服务重启后自动重试...")
            task = asyncio.create_task(_background_extract_concepts(job_id))
            _background_tasks[job_id] = task
    _pending_retries.clear()


# ---------- 图谱与路径辅助 ----------
def _graph_data(ontology_id: str) -> Dict[str, Any]:
    """聚合某本体的图谱数据（nodes/links）。

    包含：
    - 概念节点（node_type="concept"）
    - 实体节点（node_type="entity"，带 concept_type/concept_id）
    - instance_of 边（概念→实体）
    - 本体内关系边

    重要：`type` 字段保持为类型名（如"人物""事件"），供前端按 entity_types
    颜色匹配（前端 OntologyDetail.vue 用 n.type 查 catIndex）。`node_type`
    字段区分概念节点与实体节点，供新前端使用。
    """
    nodes = []
    links = []
    # 概念对象映射（concept_id -> ConceptType）
    concept_map = {c.id: c for c in concepts_db.get(ontology_id, [])}

    # 概念节点
    for c in concepts_db.get(ontology_id, []):
        nodes.append({
            "id": c.id,
            "name": c.name,
            "type": c.entity_type or c.name or "概念",   # 类型名，供前端颜色匹配
            "node_type": "concept",                        # 节点类型：概念/实体
            "entity_type": c.entity_type,
            "color": c.color,
        })
    # 实体节点
    for e in entities_db.get(ontology_id, []):
        concept = concept_map.get(e.instance_of)
        concept_name = concept.name if concept else ""
        # type 用概念的 entity_type（元模型类型名），兼容旧前端颜色匹配；
        # 兼容旧数据：无 instance_of 时回退到 e.type
        type_name = concept.entity_type if concept else (e.type or "未分类")
        nodes.append({
            "id": e.id,
            "name": e.name,
            "type": type_name,                             # 类型名，供前端颜色匹配
            "node_type": "entity",                         # 节点类型：概念/实体
            "concept_type": concept_name,
            "concept_id": e.instance_of,
            "is_primary": e.is_primary,
        })
        # instance_of 边（概念→实体）
        if e.instance_of:
            links.append({
                "source": e.instance_of,
                "target": e.id,
                "relation": "instance_of",
                "weight": 1.0,
            })
    # 关系边
    for r in relations_db.get(ontology_id, []):
        links.append({
            "source": r.source_id,
            "target": r.target_id,
            "relation": r.relation_type,
            "weight": r.weight,
        })
    return {"nodes": nodes, "links": links}


def _bfs_path(ontology_id: str, source_id: str, target_id: str) -> Optional[Dict[str, Any]]:
    """在本体内求 source->target 最短路径（按无向图处理），返回路径上的实体与关系。

    Args:
        ontology_id: 本体ID
        source_id: 起点实体ID
        target_id: 终点实体ID

    Returns:
        {"entities":[...], "relations":[...]} 或 None（不可达）
    """
    ents = entities_db.get(ontology_id, [])
    rels = relations_db.get(ontology_id, [])
    ent_map = {e.id: e for e in ents}

    if source_id not in ent_map or target_id not in ent_map:
        return None

    # 建无向邻接表：节点 -> [(邻居id, 关系对象)]
    adj = defaultdict(list)
    for r in rels:
        adj[r.source_id].append((r.target_id, r))
        adj[r.target_id].append((r.source_id, r))

    # BFS
    visited = {source_id}
    prev = {}  # 节点 -> (上一节点, 关系)
    queue = deque([source_id])
    while queue:
        cur = queue.popleft()
        if cur == target_id:
            break
        for nxt, r in adj.get(cur, []):
            if nxt not in visited:
                visited.add(nxt)
                prev[nxt] = (cur, r)
                queue.append(nxt)

    if target_id not in visited:
        return None

    # 回溯路径
    path_entities = []
    path_relations = []
    cur = target_id
    while cur != source_id:
        path_entities.append(ent_map[cur])
        prev_node, rel = prev[cur]
        path_relations.append(rel)
        cur = prev_node
    path_entities.append(ent_map[source_id])
    path_entities.reverse()
    path_relations.reverse()

    return {
        "entities": [_entity_dict_with_type(e, ontology_id) for e in path_entities],
        "relations": [r.dict() for r in path_relations],
    }


# ---------- 本体上下文（供 B2 三服务 prompt 注入消费）----------
def _select_entities_by_question(ents: List[Entity], question: str, top_k: int) -> List[Entity]:
    """按问题关键词筛选实体，命中优先，不超过 top_k。

    简单 in 匹配（实体名/属性名/属性值），不引入向量检索。
    命中数为 0 时退化为取前 top_k 个，保证上下文非空。
    """
    if len(ents) <= top_k:
        return list(ents)
    if not question:
        return ents[:top_k]
    q_lower = question.lower()
    hits, misses = [], []
    for e in ents:
        # 遍历结构化属性列表，匹配属性名和属性值
        hit = (q_lower in e.name.lower()
               or any(q_lower in str(p.name).lower() or q_lower in str(p.value).lower()
                      for p in e.properties))
        (hits if hit else misses).append(e)
    if not hits:
        return ents[:top_k]
    result = hits[:top_k]
    if len(result) < top_k:
        result.extend(misses[:top_k - len(result)])
    return result


def _build_ontology_context(ontology_id: str, question: str = "", top_k: int = 20) -> Dict[str, Any]:
    """构建本体上下文（summary_text + 结构化数据），供 B2 三服务塞入 LLM prompt。

    Args:
        ontology_id: 本体ID
        question:    用户问题（非空时按关键词命中筛选实体，命中优先）
        top_k:       最大返回实体数（默认 20）

    Returns:
        {
            "summary_text": 可直接塞 prompt 的中文文本,
            "entities":     结构化实体列表,
            "relations":    结构化关系列表（仅两端实体都在选中集合内的）,
            "ontology":     本体元信息
        }
        本体不存在时返回空结构（summary_text 为空串，消费方据此降级）。
    """
    ont = ontologies_db.get(ontology_id)
    if not ont:
        return {"summary_text": "", "entities": [], "relations": [], "ontology": None}

    ents = entities_db.get(ontology_id, [])
    rels = relations_db.get(ontology_id, [])
    ent_map = {e.id: e for e in ents}
    # 概念ID→概念名映射，用于 summary 中展示实体类型
    concept_name_map = {c.id: c.name for c in concepts_db.get(ontology_id, [])}

    selected = _select_entities_by_question(ents, question, top_k)
    selected_ids = {e.id for e in selected}
    # 关系：仅保留两端实体都在选中集合内的，避免 summary 出现"未知"节点
    selected_rels = [r for r in rels
                     if r.source_id in selected_ids and r.target_id in selected_ids]

    # ── 拼接可直接塞 prompt 的中文背景文本 ──
    lines = [f"【领域本体：{ont.name}】"]
    if ont.description:
        lines.append(f"说明：{ont.description}")
    lines.append(f"实体清单（共 {len(selected)} 个）：")
    for e in selected:
        concept_name = concept_name_map.get(e.instance_of, e.type or "")
        parts = [f"- {e.name}（类型：{concept_name}）"]
        if e.properties:
            # 遍历结构化属性，区分描述型/指标型
            prop_parts = []
            for p in e.properties:
                val_str = f"{p.value}" if not p.unit else f"{p.value}{p.unit}"
                tag = "[指标]" if p.category == "metric" else ""
                prop_parts.append(f"{p.name}{tag}:{val_str}")
            parts.append(f"属性[{', '.join(prop_parts)}]")
        if e.bindings and e.bindings.get("table_name") and e.bindings.get("column_name"):
            parts.append(f"绑定数据字段[{e.bindings['table_name']}.{e.bindings['column_name']}]")
        lines.append(" ".join(parts))

    if selected_rels:
        lines.append(f"关系链路（共 {len(selected_rels)} 条）：")
        for r in selected_rels:
            src = ent_map.get(r.source_id)
            tgt = ent_map.get(r.target_id)
            src_name = src.name if src else "未知"
            tgt_name = tgt.name if tgt else "未知"
            line = f"- {src_name} —[{r.relation_type}]→ {tgt_name}"
            if r.bindings.get("indicator_id"):
                line += f"（衡量指标ID：{r.bindings['indicator_id']}）"
            lines.append(line)

    return {
        "summary_text": "\n".join(lines),
        "entities": [_entity_dict_with_type(e, ontology_id) for e in selected],
        "relations": [r.dict() for r in selected_rels],
        "ontology": {
            "id": ont.id,
            "name": ont.name,
            "description": ont.description,
        }
    }


# ---------- 接口 ----------
@app.get("/")
async def root():
    return {
        "service": "本体模型服务",
        "version": "2.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ontology-service"}


@app.post("/ontology/create")
async def create_ontology(
    name: str = Form(...),
    description: str = Form(""),
    entity_types: str = Form(""),
    relation_types: str = Form("")
):
    """创建本体模型。

    Args:
        name: 本体名称
        description: 描述
        entity_types: 实体类型定义 JSON 字符串，如 [{"name":"概念","color":"#xxx"}]
        relation_types: 关系类型定义 JSON 字符串，如 [{"name":"包含"}]
    """
    et_list = _parse_json_arg(entity_types, None)
    rt_list = _parse_json_arg(relation_types, None)
    if et_list is None:
        et_list = DEFAULT_ENTITY_TYPES
    if rt_list is None:
        rt_list = DEFAULT_RELATION_TYPES

    now = datetime.now()
    ontology = OntologyModel(
        id=f"ont_{uuid.uuid4().hex[:8]}",
        name=name,
        description=description,
        version="1.0.0",
        entity_types=[EntityType(**t) for t in et_list],
        relation_types=[RelationType(**t) for t in rt_list],
        create_time=now,
        update_time=now,
        status="活跃",
    )

    async with db_lock:
        ontologies_db[ontology.id] = ontology
        entities_db[ontology.id] = []
        relations_db[ontology.id] = []
        save_ontology(ontology.id)
        save_index()

    return {
        "success": True,
        "message": "本体模型创建成功",
        "data": _ontology_summary(ontology)
    }


@app.get("/ontology/list")
async def list_ontologies():
    """列出所有本体模型。"""
    items = [_ontology_summary(o) for o in ontologies_db.values()]
    return {
        "success": True,
        "total": len(items),
        "items": items
    }


@app.get("/ontology/stats")
async def get_stats():
    """全局统计信息。"""
    entity_types = defaultdict(int)
    relation_types = defaultdict(int)
    total_entities = 0
    total_relations = 0
    total_concepts = 0
    for oid, ents in entities_db.items():
        total_entities += len(ents)
        # 概念ID→概念名映射，用于按概念名统计
        concept_name_map = {c.id: c.name for c in concepts_db.get(oid, [])}
        for e in ents:
            type_name = concept_name_map.get(e.instance_of, e.type or "未分类")
            entity_types[type_name] += 1
    for oid, rels in relations_db.items():
        total_relations += len(rels)
        for r in rels:
            relation_types[r.relation_type] += 1
    total_concepts = sum(len(v) for v in concepts_db.values())
    return {
        "success": True,
        "data": {
            "total_entities": total_entities,
            "total_relations": total_relations,
            "total_concepts": total_concepts,
            "total_ontologies": len(ontologies_db),
            "entity_types": dict(entity_types),
            "relation_types": dict(relation_types),
            "avg_relations_per_entity": total_relations / total_entities if total_entities else 0
        }
    }


@app.get("/ontology/default")
async def get_default_ontology():
    """获取默认本体。

    优先返回 is_default=True 的本体；无则降级返回第一个；再无则 404。
    注意：此静态路由必须声明在 /ontology/{ontology_id} 之前，否则 "default"
    会被捕获为路径参数。
    """
    if not ontologies_db:
        raise HTTPException(status_code=404, detail="尚无本体模型")
    # 优先 is_default=True
    for o in ontologies_db.values():
        if o.is_default:
            return {"success": True, "data": _ontology_summary(o)}
    # 降级：返回第一个本体（不修改其 is_default 标志，仅作返回）
    first = next(iter(ontologies_db.values()))
    return {"success": True, "data": _ontology_summary(first)}


@app.get("/ontology/{ontology_id}")
async def get_ontology(ontology_id: str):
    """获取单个本体详情（含实时实体/关系计数）。"""
    ont = _get_ontology_or_404(ontology_id)
    return {
        "success": True,
        "data": _ontology_summary(ont)
    }


@app.put("/ontology/{ontology_id}")
async def update_ontology(
    ontology_id: str,
    name: str = Form(...),
    description: str = Form(""),
    entity_types: str = Form(""),
    relation_types: str = Form("")
):
    """更新本体元信息与元模型类型定义。"""
    async with db_lock:
        ont = _get_ontology_or_404(ontology_id)
        ont.name = name
        ont.description = description
        ont.update_time = datetime.now()
        et_list = _parse_json_arg(entity_types, None)
        rt_list = _parse_json_arg(relation_types, None)
        if et_list is not None:
            ont.entity_types = [EntityType(**t) for t in et_list]
        if rt_list is not None:
            ont.relation_types = [RelationType(**t) for t in rt_list]
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "本体模型更新成功"}


@app.delete("/ontology/{ontology_id}")
async def delete_ontology(ontology_id: str):
    """删除本体及其下属的所有概念/实体/关系（仅删该本体，不影响其他本体）。"""
    async with db_lock:
        if ontology_id not in ontologies_db:
            raise HTTPException(status_code=404, detail="本体模型不存在")
        ontologies_db.pop(ontology_id)
        concepts_db.pop(ontology_id, None)
        entities_db.pop(ontology_id, None)
        relations_db.pop(ontology_id, None)
        save_index()
        # 删除本体数据文件（保留 .bak 以便误删恢复）
        path = _resolve_ontology_file(ontology_id)
        with FileLock(_lock_path(f'ontology_{ontology_id}')):
            if os.path.exists(path):
                if os.path.exists(path + '.bak'):
                    os.remove(path + '.bak')
                os.rename(path, path + '.bak')

    return {"success": True, "message": "本体模型删除成功"}


@app.get("/ontology/{ontology_id}/meta")
async def get_ontology_meta(ontology_id: str):
    """获取本体的元模型（实体类型/关系类型），供前端表单下拉使用。"""
    ont = _get_ontology_or_404(ontology_id)
    return {
        "success": True,
        "data": {
            "entity_types": [t.dict() for t in ont.entity_types],
            "relation_types": [t.dict() for t in ont.relation_types],
        }
    }


# ---------- 实体 CRUD ----------
@app.post("/ontology/{ontology_id}/entity")
async def add_entity(
    ontology_id: str,
    name: str = Form(...),
    instance_of: str = Form(""),
    entity_type: str = Form(""),       # 兼容旧前端：传类型名时自动查找/创建概念
    properties: str = Form("{}"),
    is_primary: bool = Form(False),
    source_snippet: str = Form("")
):
    """向指定本体添加实体。

    新接口用 instance_of 指向概念ID；为兼容旧前端，也可传 entity_type（类型名），
    系统会按类型名查找现有概念，找不到则自动创建一个。
    properties 兼容 Dict（旧）和 List（新）两种格式。
    """
    _get_ontology_or_404(ontology_id)

    # 兼容：若 instance_of 为空但 entity_type 有值，按类型名查找/创建概念
    if not instance_of and entity_type:
        concept = next((c for c in concepts_db.get(ontology_id, []) if c.name == entity_type), None)
        if concept:
            instance_of = concept.id
        else:
            now = datetime.now()
            ont = ontologies_db[ontology_id]
            color = next((t.color for t in ont.entity_types if t.name == entity_type), "#5470c6")
            concept = ConceptType(
                id=f"concept_{uuid.uuid4().hex[:8]}",
                ontology_id=ontology_id,
                name=entity_type,
                entity_type=entity_type,
                color=color,
                create_time=now, update_time=now,
            )
            concepts_db.setdefault(ontology_id, []).append(concept)
            instance_of = concept.id
    elif not instance_of and not entity_type:
        raise HTTPException(status_code=400, detail="必须提供 instance_of（概念ID）或 entity_type（类型名）")

    _validate_instance_of(ontology_id, instance_of)

    eid = f"ent_{uuid.uuid4().hex[:8]}"
    props = _parse_properties(_parse_json_arg(properties, []), eid)

    async with db_lock:
        ont = ontologies_db[ontology_id]
        entity = Entity(
            id=eid,
            ontology_id=ontology_id,
            name=name,
            instance_of=instance_of,
            is_primary=is_primary,
            properties=props,
            source_snippet=source_snippet,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )
        entities_db.setdefault(ontology_id, []).append(entity)
        ont.update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {
        "success": True,
        "message": "实体添加成功",
        "data": _entity_dict_with_type(entity, ontology_id)
    }


@app.get("/ontology/{ontology_id}/entity/list")
async def list_entities(
    ontology_id: str,
    entity_type: Optional[str] = None,      # 按概念名筛选（兼容旧前端）
    instance_of: Optional[str] = None,      # 按概念ID筛选（新接口）
    is_primary: Optional[bool] = None,      # 按主要实体筛选
    page: int = 1,
    page_size: int = 20
):
    """列出某本体的实体（支持按概念/主要实体过滤与分页）。"""
    _get_ontology_or_404(ontology_id)
    filtered = entities_db.get(ontology_id, [])

    # 按概念ID筛选
    if instance_of:
        filtered = [e for e in filtered if e.instance_of == instance_of]
    # 按概念名筛选（兼容旧前端 entity_type 参数）
    if entity_type:
        concept_ids = {c.id for c in concepts_db.get(ontology_id, []) if c.name == entity_type}
        filtered = [e for e in filtered if e.instance_of in concept_ids]
    # 按主要实体筛选
    if is_primary is not None:
        filtered = [e for e in filtered if e.is_primary == is_primary]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_entity_dict_with_type(e, ontology_id) for e in items]
    }


@app.get("/ontology/{ontology_id}/entity/{entity_id}")
async def get_entity(ontology_id: str, entity_id: str):
    """获取本体内某个实体。"""
    _get_ontology_or_404(ontology_id)
    entity = _find_entity(ontology_id, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    return {"success": True, "data": _entity_dict_with_type(entity, ontology_id)}


@app.put("/ontology/{ontology_id}/entity/{entity_id}")
async def update_entity(
    ontology_id: str,
    entity_id: str,
    name: str = Form(...),
    instance_of: str = Form(""),
    entity_type: str = Form(""),       # 兼容旧前端
    properties: str = Form("{}"),
    is_primary: bool = Form(False),
    source_snippet: str = Form("")
):
    """更新实体。

    instance_of/entity_type 兼容逻辑同 add_entity。
    properties 兼容 Dict（旧）和 List（新）。
    """
    _get_ontology_or_404(ontology_id)

    # 兼容：entity_type → instance_of
    if not instance_of and entity_type:
        concept = next((c for c in concepts_db.get(ontology_id, []) if c.name == entity_type), None)
        if concept:
            instance_of = concept.id
        else:
            now = datetime.now()
            ont = ontologies_db[ontology_id]
            color = next((t.color for t in ont.entity_types if t.name == entity_type), "#5470c6")
            concept = ConceptType(
                id=f"concept_{uuid.uuid4().hex[:8]}",
                ontology_id=ontology_id,
                name=entity_type,
                entity_type=entity_type,
                color=color,
                create_time=now, update_time=now,
            )
            concepts_db.setdefault(ontology_id, []).append(concept)
            instance_of = concept.id

    if instance_of:
        _validate_instance_of(ontology_id, instance_of)

    props = _parse_properties(_parse_json_arg(properties, []), entity_id)

    async with db_lock:
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")
        entity.name = name
        if instance_of:
            entity.instance_of = instance_of
        entity.is_primary = is_primary
        entity.properties = props
        entity.source_snippet = source_snippet
        entity.update_time = datetime.now()
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "实体更新成功"}


@app.delete("/ontology/{ontology_id}/entity/{entity_id}")
async def delete_entity(ontology_id: str, entity_id: str):
    """删除实体，同时删除该本体内指向它的关系。"""
    async with db_lock:
        _get_ontology_or_404(ontology_id)
        ents = entities_db.get(ontology_id, [])
        target = None
        for i, e in enumerate(ents):
            if e.id == entity_id:
                target = ents.pop(i)
                break
        if not target:
            raise HTTPException(status_code=404, detail="实体不存在")
        # 级联删除相关关系
        relations_db[ontology_id] = [
            r for r in relations_db.get(ontology_id, [])
            if r.source_id != entity_id and r.target_id != entity_id
        ]
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "实体删除成功"}


# ---------- 概念 CRUD ----------
@app.get("/ontology/{ontology_id}/concept/list")
async def list_concepts(
    ontology_id: str,
    entity_type: Optional[str] = None
):
    """列出某本体的所有概念（类型定义），支持按元模型 entity_type 筛选。"""
    _get_ontology_or_404(ontology_id)
    conps = concepts_db.get(ontology_id, [])
    if entity_type:
        conps = [c for c in conps if c.entity_type == entity_type]
    return {"success": True, "total": len(conps), "items": [c.dict() for c in conps]}


@app.post("/ontology/{ontology_id}/concept")
async def add_concept(
    ontology_id: str,
    name: str = Form(...),
    entity_type: str = Form(""),
    description: str = Form(""),
    color: str = Form(""),
    property_schema: str = Form("[]"),    # JSON 数组
    source_snippet: str = Form("")
):
    """新增概念（类型定义节点）。

    property_schema 为 PropertySchema 列表的 JSON，定义该类实体的属性骨架。
    """
    _get_ontology_or_404(ontology_id)

    # 解析 property_schema
    raw_schema = _parse_json_arg(property_schema, [])
    pschema = []
    if isinstance(raw_schema, list):
        for item in raw_schema:
            if isinstance(item, dict):
                pschema.append(PropertySchema(
                    name=item.get("name", ""),
                    category=item.get("category", "descriptive"),
                    data_type=item.get("data_type", "string"),
                    unit=item.get("unit", ""),
                    required=item.get("required", False),
                    description=item.get("description", ""),
                ))

    # 若 color 为空，从元模型 entity_type 继承
    if not color:
        ont = ontologies_db[ontology_id]
        color = next((t.color for t in ont.entity_types if t.name == entity_type), "#5470c6")

    now = datetime.now()
    concept = ConceptType(
        id=f"concept_{uuid.uuid4().hex[:8]}",
        ontology_id=ontology_id,
        name=name,
        entity_type=entity_type,
        description=description,
        color=color,
        property_schema=pschema,
        source_snippet=source_snippet,
        create_time=now,
        update_time=now,
    )

    async with db_lock:
        concepts_db.setdefault(ontology_id, []).append(concept)
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "概念添加成功", "data": concept.dict()}


@app.get("/ontology/{ontology_id}/concept/{concept_id}")
async def get_concept(ontology_id: str, concept_id: str):
    """获取某个概念。"""
    _get_ontology_or_404(ontology_id)
    concept = _find_concept(ontology_id, concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="概念不存在")
    return {"success": True, "data": concept.dict()}


@app.put("/ontology/{ontology_id}/concept/{concept_id}")
async def update_concept(
    ontology_id: str,
    concept_id: str,
    name: str = Form(None),
    entity_type: str = Form(None),
    description: str = Form(None),
    color: str = Form(None),
    property_schema: str = Form(None)
):
    """更新概念（仅更新非 None 字段）。"""
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        concept = _find_concept(ontology_id, concept_id)
        if not concept:
            raise HTTPException(status_code=404, detail="概念不存在")
        if name is not None:
            concept.name = name
        if entity_type is not None:
            concept.entity_type = entity_type
        if description is not None:
            concept.description = description
        if color is not None:
            concept.color = color
        if property_schema is not None:
            raw_schema = _parse_json_arg(property_schema, [])
            pschema = []
            if isinstance(raw_schema, list):
                for item in raw_schema:
                    if isinstance(item, dict):
                        pschema.append(PropertySchema(
                            name=item.get("name", ""),
                            category=item.get("category", "descriptive"),
                            data_type=item.get("data_type", "string"),
                            unit=item.get("unit", ""),
                            required=item.get("required", False),
                            description=item.get("description", ""),
                        ))
            concept.property_schema = pschema
        concept.update_time = datetime.now()
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "概念更新成功", "data": concept.dict()}


@app.delete("/ontology/{ontology_id}/concept/{concept_id}")
async def delete_concept(ontology_id: str, concept_id: str):
    """删除概念。

    若有实体 instance_of 指向该概念，拒绝删除（提示先迁移实体）。
    """
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        concept = _find_concept(ontology_id, concept_id)
        if not concept:
            raise HTTPException(status_code=404, detail="概念不存在")
        # 检查是否有实体引用
        refs = [e for e in entities_db.get(ontology_id, []) if e.instance_of == concept_id]
        if refs:
            raise HTTPException(
                status_code=400,
                detail=f"有 {len(refs)} 个实体引用此概念，请先迁移或删除这些实体"
            )
        concepts_db[ontology_id] = [c for c in concepts_db.get(ontology_id, []) if c.id != concept_id]
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "概念删除成功"}


# ---------- 属性 CRUD ----------
@app.get("/ontology/{ontology_id}/entity/{entity_id}/property/list")
async def list_properties(
    ontology_id: str,
    entity_id: str,
    category: Optional[str] = None       # descriptive | metric
):
    """列出实体的所有属性，支持按分类筛选。"""
    _get_ontology_or_404(ontology_id)
    entity = _find_entity(ontology_id, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    props = entity.properties
    if category:
        props = [p for p in props if p.category == category]
    return {"success": True, "total": len(props), "items": [p.dict() for p in props]}


@app.post("/ontology/{ontology_id}/entity/{entity_id}/property")
async def add_property(
    ontology_id: str,
    entity_id: str,
    name: str = Form(...),
    value: str = Form(""),               # 允许任意类型，前端传字符串由 data_type 区分
    category: str = Form("descriptive"),
    data_type: str = Form("string"),
    unit: str = Form(""),
    source_snippet: str = Form(""),
    bindings: str = Form("{}")
):
    """为实体新增属性。"""
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")

        # 值类型转换
        parsed_value = value
        if data_type == "number":
            try:
                parsed_value = float(value) if "." in value else int(value)
            except Exception:
                parsed_value = value

        now = datetime.now()
        prop = Property(
            id=f"prop_{uuid.uuid4().hex[:8]}",
            entity_id=entity_id,
            name=name,
            value=parsed_value,
            category=category,
            data_type=data_type,
            unit=unit,
            source_snippet=source_snippet,
            bindings=_parse_json_arg(bindings, {}),
            create_time=now,
            update_time=now,
        )
        entity.properties.append(prop)
        entity.update_time = now
        ontologies_db[ontology_id].update_time = now
        save_ontology(ontology_id)

    return {"success": True, "message": "属性添加成功", "data": prop.dict()}


@app.get("/ontology/{ontology_id}/entity/{entity_id}/property/{property_id}")
async def get_property(ontology_id: str, entity_id: str, property_id: str):
    """获取某个属性。"""
    _get_ontology_or_404(ontology_id)
    entity = _find_entity(ontology_id, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    prop = _find_property(entity, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="属性不存在")
    return {"success": True, "data": prop.dict()}


@app.put("/ontology/{ontology_id}/entity/{entity_id}/property/{property_id}")
async def update_property(
    ontology_id: str,
    entity_id: str,
    property_id: str,
    name: str = Form(None),
    value: str = Form(None),
    category: str = Form(None),
    data_type: str = Form(None),
    unit: str = Form(None),
    source_snippet: str = Form(None),
    bindings: str = Form(None)
):
    """更新属性（仅更新非 None 字段）。

    指标型属性（category=metric）的 value 被更新时，旧值自动追加到 history。
    """
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")
        prop = _find_property(entity, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="属性不存在")

        now = datetime.now()
        # 指标型属性值变更时，旧值写入 history
        if value is not None and prop.category == "metric" and str(prop.value) != str(value):
            prop.history.append(PropertyHistoryEntry(
                value=prop.value,
                recorded_at=prop.update_time,
                source_snippet=prop.source_snippet,
            ))

        if name is not None:
            prop.name = name
        if value is not None:
            # 值类型转换
            effective_type = data_type or prop.data_type
            parsed_value = value
            if effective_type == "number":
                try:
                    parsed_value = float(value) if "." in value else int(value)
                except Exception:
                    parsed_value = value
            prop.value = parsed_value
        if category is not None:
            prop.category = category
        if data_type is not None:
            prop.data_type = data_type
        if unit is not None:
            prop.unit = unit
        if source_snippet is not None:
            prop.source_snippet = source_snippet
        if bindings is not None:
            prop.bindings = _parse_json_arg(bindings, {})
        prop.update_time = now
        entity.update_time = now
        ontologies_db[ontology_id].update_time = now
        save_ontology(ontology_id)

    return {"success": True, "message": "属性更新成功", "data": prop.dict()}


@app.delete("/ontology/{ontology_id}/entity/{entity_id}/property/{property_id}")
async def delete_property(ontology_id: str, entity_id: str, property_id: str):
    """删除属性。"""
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")
        before = len(entity.properties)
        entity.properties = [p for p in entity.properties if p.id != property_id]
        if len(entity.properties) == before:
            raise HTTPException(status_code=404, detail="属性不存在")
        entity.update_time = datetime.now()
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)

    return {"success": True, "message": "属性删除成功"}


@app.get("/ontology/{ontology_id}/entity/{entity_id}/property/{property_id}/history")
async def get_property_history(ontology_id: str, entity_id: str, property_id: str):
    """获取指标型属性的历史版本。"""
    _get_ontology_or_404(ontology_id)
    entity = _find_entity(ontology_id, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    prop = _find_property(entity, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="属性不存在")
    return {"success": True, "total": len(prop.history), "items": [h.dict() for h in prop.history]}


@app.post("/ontology/{ontology_id}/entity/{entity_id}/property/{property_id}/history")
async def add_property_history(
    ontology_id: str,
    entity_id: str,
    property_id: str,
    value: str = Form(...),
    recorded_at: str = Form(""),         # ISO 格式时间，空则用当前时间
    source_snippet: str = Form(""),
    note: str = Form("")
):
    """手动为指标型属性追加历史值。"""
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")
        prop = _find_property(entity, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="属性不存在")

        # 解析时间
        from datetime import datetime as _dt
        parsed_time = None
        if recorded_at:
            try:
                parsed_time = _dt.fromisoformat(recorded_at)
            except Exception:
                parsed_time = None

        # 值类型转换
        parsed_value = value
        if prop.data_type == "number":
            try:
                parsed_value = float(value) if "." in value else int(value)
            except Exception:
                parsed_value = value

        entry = PropertyHistoryEntry(
            value=parsed_value,
            recorded_at=parsed_time,
            source_snippet=source_snippet,
            note=note,
        )
        prop.history.append(entry)
        prop.update_time = datetime.now()
        entity.update_time = datetime.now()
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)

    return {"success": True, "message": "历史值追加成功", "data": entry.dict()}


@app.post("/ontology/{ontology_id}/entity/{entity_id}/property/{property_id}/bind")
async def bind_property_field(
    ontology_id: str,
    entity_id: str,
    property_id: str,
    field_id: str = Form(...),
    dataset_id: str = Form(""),
    table_name: str = Form(""),
    column_name: str = Form("")
):
    """将指标型属性绑定到数据字段（ass_field_annotation）。"""
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")
        prop = _find_property(entity, property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="属性不存在")

        prop.bindings = {
            "field_id": field_id,
            "dataset_id": dataset_id,
            "table_name": table_name,
            "column_name": column_name,
        }
        prop.update_time = datetime.now()
        entity.update_time = datetime.now()
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)

    return {"success": True, "message": "属性数据字段绑定成功", "data": prop.bindings}


# ---------- 关系 CRUD ----------
@app.post("/ontology/{ontology_id}/relation")
async def add_relation(
    ontology_id: str,
    source_id: str = Form(...),
    target_id: str = Form(...),
    relation_type: str = Form(...),
    weight: float = Form(1.0),
    properties: str = Form("{}")
):
    """向指定本体添加关系。"""
    _get_ontology_or_404(ontology_id)
    _validate_relation_type(ontology_id, relation_type)
    rel_id = f"rel_{uuid.uuid4().hex[:8]}"
    props = _parse_properties(_parse_json_arg(properties, []), rel_id)

    async with db_lock:
        if not _find_entity(ontology_id, source_id):
            raise HTTPException(status_code=400, detail="源实体不存在")
        if not _find_entity(ontology_id, target_id):
            raise HTTPException(status_code=400, detail="目标实体不存在")

        relation = Relation(
            id=rel_id,
            ontology_id=ontology_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            properties=props,
            weight=weight,
            create_time=datetime.now(),
        )
        relations_db.setdefault(ontology_id, []).append(relation)
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {
        "success": True,
        "message": "关系添加成功",
        "data": relation.dict()
    }


@app.get("/ontology/{ontology_id}/relation/list")
async def list_relations(
    ontology_id: str,
    relation_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """列出某本体的关系（带源/目标实体名）。"""
    _get_ontology_or_404(ontology_id)
    filtered = relations_db.get(ontology_id, [])
    if relation_type:
        filtered = [r for r in filtered if r.relation_type == relation_type]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    ent_map = {e.id: e.name for e in entities_db.get(ontology_id, [])}
    enriched = []
    for r in items:
        d = r.dict()
        d["source_name"] = ent_map.get(r.source_id, "未知")
        d["target_name"] = ent_map.get(r.target_id, "未知")
        enriched.append(d)

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": enriched
    }


@app.delete("/ontology/{ontology_id}/relation/{relation_id}")
async def delete_relation(ontology_id: str, relation_id: str):
    """删除关系。"""
    async with db_lock:
        _get_ontology_or_404(ontology_id)
        rels = relations_db.get(ontology_id, [])
        for i, r in enumerate(rels):
            if r.id == relation_id:
                rels.pop(i)
                ontologies_db[ontology_id].update_time = datetime.now()
                save_ontology(ontology_id)
                save_index()
                return {"success": True, "message": "关系删除成功"}
        raise HTTPException(status_code=404, detail="关系不存在")


# ---------- 图谱与查询 ----------
@app.get("/ontology/{ontology_id}/graph")
async def get_graph(ontology_id: str):
    """获取某本体的图谱数据（仅该本体的 nodes/links）。"""
    _get_ontology_or_404(ontology_id)
    return {"success": True, "data": _graph_data(ontology_id)}


@app.get("/ontology/{ontology_id}/path")
async def get_path(
    ontology_id: str,
    source_id: str = ...,
    target_id: str = ...
):
    """查询本体内两个实体间的最短路径（无向 BFS）。"""
    _get_ontology_or_404(ontology_id)
    result = _bfs_path(ontology_id, source_id, target_id)
    if result is None:
        return {
            "success": True,
            "message": "两实体间不存在可达路径",
            "data": {"entities": [], "relations": []}
        }
    return {"success": True, "data": result}


# ---------- 绑定与默认本体（B 阶段数据联动）----------
@app.post("/ontology/{ontology_id}/entity/{entity_id}/bind")
async def bind_entity_field(
    ontology_id: str,
    entity_id: str,
    field_id: str = Form(""),
    dataset_id: str = Form(""),
    table_name: str = Form(""),
    column_name: str = Form("")
):
    """将实体绑定到具体数据字段（ass_field_annotation）。

    绑定信息存入 entity.bindings，整体覆盖旧绑定。
    结构: {"field_id":"...", "dataset_id":"...", "table_name":"...", "column_name":"..."}
    """
    async with db_lock:
        _get_ontology_or_404(ontology_id)
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")
        entity.bindings = {
            "field_id": field_id,
            "dataset_id": dataset_id,
            "table_name": table_name,
            "column_name": column_name,
        }
        entity.update_time = datetime.now()
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "实体字段绑定成功", "data": entity.bindings}


@app.delete("/ontology/{ontology_id}/entity/{entity_id}/bind")
async def unbind_entity_field(ontology_id: str, entity_id: str):
    """清除实体的数据字段绑定。"""
    async with db_lock:
        _get_ontology_or_404(ontology_id)
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")
        entity.bindings = {}
        entity.update_time = datetime.now()
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "实体字段绑定已解除"}


@app.post("/ontology/{ontology_id}/relation/{relation_id}/bind")
async def bind_relation_indicator(
    ontology_id: str,
    relation_id: str,
    indicator_id: str = Form(...)
):
    """将关系绑定到具体指标（ass_indicator）。

    绑定信息存入 relation.bindings，整体覆盖旧绑定。
    结构: {"indicator_id":"..."}
    """
    async with db_lock:
        _get_ontology_or_404(ontology_id)
        relation = _find_relation(ontology_id, relation_id)
        if not relation:
            raise HTTPException(status_code=404, detail="关系不存在")
        relation.bindings = {"indicator_id": indicator_id}
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "关系指标绑定成功", "data": relation.bindings}


@app.delete("/ontology/{ontology_id}/relation/{relation_id}/bind")
async def unbind_relation_indicator(ontology_id: str, relation_id: str):
    """清除关系的指标绑定。"""
    async with db_lock:
        _get_ontology_or_404(ontology_id)
        relation = _find_relation(ontology_id, relation_id)
        if not relation:
            raise HTTPException(status_code=404, detail="关系不存在")
        relation.bindings = {}
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "关系指标绑定已解除"}


@app.post("/ontology/{ontology_id}/set-default")
async def set_default_ontology(ontology_id: str):
    """将指定本体设为默认（其余本体取消默认标志）。

    同一时刻仅一个本体 is_default=True。仅持久化实际发生变更的本体。
    """
    async with db_lock:
        ont = _get_ontology_or_404(ontology_id)
        changed_ids = []
        for oid, o in ontologies_db.items():
            new_val = (oid == ontology_id)
            if o.is_default != new_val:
                o.is_default = new_val
                o.update_time = datetime.now()
                changed_ids.append(oid)
        save_index()
        for oid in changed_ids:
            save_ontology(oid)

    return {"success": True, "message": f"已将「{ont.name}」设为默认本体"}


@app.post("/ontology/{ontology_id}/archive")
async def archive_ontology(ontology_id: str):
    """将指定本体归档（status 置为「归档」），归档后不再作为默认本体。

    归档仅改变状态标记，不影响实体/关系数据；前端列表可通过「归档」筛选查看。
    """
    async with db_lock:
        ont = _get_ontology_or_404(ontology_id)
        ont.status = "归档"
        ont.update_time = datetime.now()
        # 归档本体不应继续作为其他服务默认取用的默认本体
        ont.is_default = False
        save_index()
        save_ontology(ontology_id)

    return {"success": True, "message": f"已将「{ont.name}」归档"}


@app.get("/ontology/{ontology_id}/bindings")
async def get_bindings(ontology_id: str):
    """返回该本体所有绑定的紧凑结构（仅含已绑定的实体/关系）。

    供前端 badge 展示与 B2 prompt 注入消费。
    """
    _get_ontology_or_404(ontology_id)
    _concept_name_map = {c.id: c.name for c in concepts_db.get(ontology_id, [])}
    bound_entities = [
        {"id": e.id, "name": e.name,
         "type": _concept_name_map.get(e.instance_of, e.type or ""),
         "bindings": e.bindings}
        for e in entities_db.get(ontology_id, []) if e.bindings
    ]
    bound_relations = [
        {
            "id": r.id,
            "source_id": r.source_id,
            "target_id": r.target_id,
            "relation_type": r.relation_type,
            "bindings": r.bindings,
        }
        for r in relations_db.get(ontology_id, []) if r.bindings
    ]
    return {
        "success": True,
        "data": {
            "ontology_id": ontology_id,
            "entities": bound_entities,
            "relations": bound_relations,
        }
    }


# ---------- 本体上下文接口（供 B2 三服务消费）----------
@app.get("/ontology/default/context")
async def get_default_context(question: str = "", top_k: int = 20):
    """默认本体的上下文快捷接口（三服务最常用）。

    注意：此静态路由必须声明在 /ontology/{ontology_id}/context 之前，
    否则 "default" 会被捕获为路径参数。
    """
    if not ontologies_db:
        raise HTTPException(status_code=404, detail="尚无本体模型")
    # 取默认本体（优先 is_default=True，否则第一个）
    target_id = None
    for oid, o in ontologies_db.items():
        if o.is_default:
            target_id = oid
            break
    if not target_id:
        target_id = next(iter(ontologies_db.keys()))
    ctx = _build_ontology_context(target_id, question, top_k)
    return {"success": True, "data": ctx}


@app.get("/ontology/{ontology_id}/context")
async def get_ontology_context(
    ontology_id: str,
    question: str = "",
    top_k: int = 20
):
    """指定本体的上下文接口（请求携带 ontology_id 时使用）。"""
    _get_ontology_or_404(ontology_id)
    ctx = _build_ontology_context(ontology_id, question, top_k)
    return {"success": True, "data": ctx}


# ---------- 导入导出 ----------
@app.post("/ontology/import")
async def import_ontology(file: UploadFile = File(...)):
    """导入本体文件，建立旧id->新id映射，重定向关系，避免断链。

    兼容旧格式（Dict 属性）和新格式（List[Property]）：导入时自动迁移。
    兼容两种导出结构：
    - {name, description, entity_types, entities, relations}（export 接口格式）
    - {ontology: {...}, entities, relations}（save_ontology 格式）
    """
    try:
        content = await file.read()
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")

    now = datetime.now()
    new_oid = f"ont_{uuid.uuid4().hex[:8]}"

    # 兼容两种导出结构
    if "ontology" in data:
        ont_data = data.get("ontology", {})
        et_list = ont_data.get("entity_types") or DEFAULT_ENTITY_TYPES
        rt_list = ont_data.get("relation_types") or DEFAULT_RELATION_TYPES
        name_val = ont_data.get("name", "导入本体")
        desc_val = ont_data.get("description", "")
        ver_val = ont_data.get("version", "1.0.0")
    else:
        et_list = data.get("entity_types") or DEFAULT_ENTITY_TYPES
        rt_list = data.get("relation_types") or DEFAULT_RELATION_TYPES
        name_val = data.get("name", "导入本体")
        desc_val = data.get("description", "")
        ver_val = data.get("version", "1.0.0")

    ont = OntologyModel(
        id=new_oid,
        name=name_val,
        description=desc_val,
        version=ver_val,
        entity_types=[EntityType(**t) for t in et_list],
        relation_types=[RelationType(**t) for t in rt_list],
        create_time=now,
        update_time=now,
        status="活跃",
        schema_version=SCHEMA_VERSION,
    )

    # 用迁移函数统一格式（兼容 Dict/List 属性 + 自动生成概念）
    raw_data = {
        "ontology": {
            "id": new_oid, "name": name_val, "description": desc_val,
            "version": ver_val, "entity_types": et_list, "relation_types": rt_list,
            "create_time": now.isoformat(), "update_time": now.isoformat(),
            "status": "活跃",
        },
        "entities": data.get("entities", []),
        "relations": data.get("relations", []),
    }
    migrated = migrate_ontology_dict(raw_data, new_oid)

    # 旧实体id -> 新实体id 映射，防止关系断链
    id_map = {}
    new_entities = []
    for ed in migrated.get("entities", []):
        old_id = ed.get("id") or f"ent_{uuid.uuid4().hex[:8]}"
        new_id = f"ent_{uuid.uuid4().hex[:8]}"
        id_map[old_id] = new_id
        ed["id"] = new_id
        ed["ontology_id"] = new_oid
        try:
            new_entities.append(Entity(**ed))
        except Exception as e:
            logger.warning(f"导入实体失败: {e}")

    # 概念重写 id 和 ontology_id
    new_concepts = []
    concept_id_map = {}
    for cd in migrated.get("concepts", []):
        old_cid = cd.get("id") or f"concept_{uuid.uuid4().hex[:8]}"
        new_cid = f"concept_{uuid.uuid4().hex[:8]}"
        concept_id_map[old_cid] = new_cid
        cd["id"] = new_cid
        cd["ontology_id"] = new_oid
        try:
            new_concepts.append(ConceptType(**cd))
        except Exception as e:
            logger.warning(f"导入概念失败: {e}")

    # 重写实体的 instance_of 指向新概念 id
    for ent in new_entities:
        if ent.instance_of and ent.instance_of in concept_id_map:
            ent.instance_of = concept_id_map[ent.instance_of]

    new_relations = []
    for rd in migrated.get("relations", []):
        src = id_map.get(rd.get("source_id"))
        tgt = id_map.get(rd.get("target_id"))
        if not src or not tgt:
            continue
        rd["source_id"] = src
        rd["target_id"] = tgt
        rd["ontology_id"] = new_oid
        rd["id"] = f"rel_{uuid.uuid4().hex[:8]}"
        try:
            new_relations.append(Relation(**rd))
        except Exception as e:
            logger.warning(f"导入关系失败: {e}")

    async with db_lock:
        ontologies_db[new_oid] = ont
        concepts_db[new_oid] = new_concepts
        entities_db[new_oid] = new_entities
        relations_db[new_oid] = new_relations
        save_ontology(new_oid)
        save_index()

    return {
        "success": True,
        "message": "本体模型导入成功",
        "data": {
            "ontology_id": new_oid,
            "concepts_imported": len(new_concepts),
            "entities_imported": len(new_entities),
            "relations_imported": len(new_relations)
        }
    }


@app.get("/ontology/export/{ontology_id}")
async def export_ontology(ontology_id: str):
    """导出本体为 JSON（含元模型 + 概念 + 实体 + 关系）。"""
    ont = _get_ontology_or_404(ontology_id)
    data = {
        "name": ont.name,
        "description": ont.description,
        "version": ont.version,
        "entity_types": [t.dict() for t in ont.entity_types],
        "relation_types": [t.dict() for t in ont.relation_types],
        "concepts": [c.dict() for c in concepts_db.get(ontology_id, [])],
        "entities": [e.dict() for e in entities_db.get(ontology_id, [])],
        "relations": [r.dict() for r in relations_db.get(ontology_id, [])],
        "schema_version": SCHEMA_VERSION,
    }
    return {"success": True, "data": data}


@app.post("/ontology/search")
async def search_ontology(
    query: str = Form(...),
    ontology_id: str = Form(...)
):
    """在某本体内搜索实体与关系（匹配名称、概念名、关系类型、属性名/值）。"""
    _get_ontology_or_404(ontology_id)
    query_lower = query.lower()

    # 概念ID→概念名映射
    concept_name_map = {c.id: c.name for c in concepts_db.get(ontology_id, [])}

    matched_entities = []
    for e in entities_db.get(ontology_id, []):
        concept_name = concept_name_map.get(e.instance_of, "")
        if (query_lower in e.name.lower()
                or query_lower in concept_name.lower()
                or query_lower in (e.type or "").lower()):
            matched_entities.append(_entity_dict_with_type(e, ontology_id))
            continue
        # 搜索结构化属性名/值
        hit = any(query_lower in str(p.name).lower() or query_lower in str(p.value).lower()
                  for p in e.properties)
        if hit:
            matched_entities.append(_entity_dict_with_type(e, ontology_id))

    matched_relations = []
    for r in relations_db.get(ontology_id, []):
        if query_lower in r.relation_type.lower():
            matched_relations.append(r.dict())
            continue
        hit = any(query_lower in str(p.name).lower() or query_lower in str(p.value).lower()
                  for p in r.properties)
        if hit:
            matched_relations.append(r.dict())

    return {
        "success": True,
        "query": query,
        "total": len(matched_entities) + len(matched_relations),
        "data": {
            "entities": matched_entities,
            "relations": matched_relations
        }
    }


# ---------- 分步构建：辅助函数 ----------
async def _llm_json_async(messages: list, temperature: float = 0.3, max_tokens: int = 4000):
    """异步调用 LLM 并解析 JSON（在线程池中执行同步 urllib 调用，避免阻塞事件循环）。"""
    loop = __import__('asyncio').get_event_loop()
    return await loop.run_in_executor(
        None, lambda: call_llm_json(messages, temperature, max_tokens)
    )


def _gen_job_id() -> str:
    """生成构建任务 ID。"""
    return f"job_{uuid.uuid4().hex[:8]}"


# ---------- 分步构建：接口 ----------
@app.post("/ontology/build/upload")
async def build_upload(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    granularity: str = Form("medium"),
    stage_hints: str = Form("")
):
    """上传文档创建构建任务，并同步调用 LLM 推荐元模型。

    流程：
    1. 解析文档为纯文本
    2. 创建 BuildJob（step=0，携带 granularity + stage_hints）
    3. 调用 LLM 推荐元模型（失败则用默认元模型兜底）
    4. 持久化任务，返回 job_id + 推荐的元模型

    用户后续可通过 PUT /ontology/build/{job_id}/meta 确认或编辑元模型 + 粒度 + 阶段提示词。

    Args:
        granularity: 粒度预设 coarse|medium|fine，控制 step1/step2 提取数量
        stage_hints: JSON 字符串，形如 {"1":"重点关注财务指标","2":"..."}，注入各阶段 prompt
    """
    # 1. 读取并解析文档
    content = await file.read()
    filename = file.filename or "unknown.txt"
    # 写入临时文件供解析器读取
    tmp_path = os.path.join(BUILD_JOBS_DIR, f'_tmp_{uuid.uuid4().hex[:8]}')
    try:
        with open(tmp_path, 'wb') as f:
            f.write(content)
        doc_text = extract_text(tmp_path, filename)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    if not doc_text or len(doc_text.strip()) < 20:
        raise HTTPException(status_code=400, detail="文档内容为空或过短，无法提取概念")

    # 解析粒度预设（非法值回退 medium）
    if granularity not in config.GRANULARITY_RANGES:
        granularity = "medium"
    # 解析阶段提示词（JSON 字符串 → dict）
    hints_dict: Dict[int, str] = {}
    if stage_hints:
        try:
            parsed = json.loads(stage_hints) if isinstance(stage_hints, str) else stage_hints
            if isinstance(parsed, dict):
                hints_dict = {int(k): str(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"stage_hints 解析失败，忽略: {e}")

    # 截断文本以适应 LLM 上下文
    doc_text_truncated = truncate_for_llm(doc_text)

    # 2. 创建构建任务
    now = datetime.now()
    job_id = _gen_job_id()
    job = BuildJob(
        id=job_id,
        name=name,
        description=description,
        step=0,
        status="draft",
        source_filename=filename,
        source_text=doc_text,
        char_count=len(doc_text),
        granularity=granularity,
        stage_hints=hints_dict,
        create_time=now,
        update_time=now,
    )

    # 3. 调用 LLM 推荐元模型（失败用默认元模型兜底，不阻塞上传）
    try:
        messages = build_prompts.build_meta_messages(doc_text_truncated, name)
        meta = await _llm_json_async(messages, temperature=0.3, max_tokens=config.LLM_MAX_TOKENS)
        job.meta_entity_types = meta.get("entity_types", [])
        job.meta_relation_types = meta.get("relation_types", [])
        if not job.meta_entity_types:
            job.meta_entity_types = [{"name": t["name"], "color": t.get("color", "#5470c6")}
                                     for t in DEFAULT_ENTITY_TYPES]
        if not job.meta_relation_types:
            job.meta_relation_types = [{"name": t["name"]} for t in DEFAULT_RELATION_TYPES]
        meta_source = "llm"
    except Exception as e:
        logger.warning(f"LLM 推荐元模型失败，使用默认元模型: {e}")
        job.meta_entity_types = [{"name": t["name"], "color": t.get("color", "#5470c6")}
                                 for t in DEFAULT_ENTITY_TYPES]
        job.meta_relation_types = [{"name": t["name"]} for t in DEFAULT_RELATION_TYPES]
        meta_source = "default（LLM 调用失败）"

    # 4. 持久化
    async with build_lock:
        build_jobs_db[job_id] = job
        save_build_job(job_id)
        save_build_jobs_index()

    return {
        "success": True,
        "message": "文档上传成功，已推荐元模型",
        "data": {
            "job_id": job_id,
            "meta_source": meta_source,
            "meta_entity_types": job.meta_entity_types,
            "meta_relation_types": job.meta_relation_types,
            "granularity": job.granularity,
            "stage_hints": job.stage_hints,
            "char_count": job.char_count,
        }
    }


@app.get("/ontology/build/list")
async def build_list():
    """列出所有构建任务。"""
    jobs = sorted(build_jobs_db.values(), key=lambda j: j.create_time, reverse=True)
    return {
        "success": True,
        "data": [
            {
                "id": j.id,
                "name": j.name,
                "description": j.description,
                "step": j.step,
                "status": j.status,
                "source_filename": j.source_filename,
                "granularity": j.granularity,
                "meta_confirmed": j.meta_confirmed,
                "step1_confirmed": j.step1_confirmed,
                "step2_confirmed": j.step2_confirmed,
                "step3_confirmed": j.step3_confirmed,
                "step4_confirmed": j.step4_confirmed,
                "running_step": j.running_step,
                "progress": j.progress,
                "progress_message": j.progress_message,
                "error_message": j.error_message,
                "char_count": j.char_count,
                "ontology_id": j.ontology_id,
                "create_time": j.create_time.isoformat(),
                "update_time": j.update_time.isoformat(),
            }
            for j in jobs
        ]
    }


@app.get("/ontology/build/{job_id}/progress")
async def build_progress(job_id: str):
    """查询构建任务进度（轻量级，供前端轮询）。

    返回五阶段全量状态：confirmed 标记 + 各阶段分批/分组进度 + 阶段时间线（progress_stages）。
    """
    job = _get_job_or_404(job_id)
    return {
        "success": True,
        "data": {
            "job_id": job.id,
            "step": job.step,
            "status": job.status,
            "running_step": job.running_step,
            "progress": job.progress,
            "progress_message": job.progress_message,
            "error_message": job.error_message,
            "granularity": job.granularity,
            "stage_hints": job.stage_hints,
            "meta_confirmed": job.meta_confirmed,
            "step1_confirmed": job.step1_confirmed,
            "step2_confirmed": job.step2_confirmed,
            "step3_confirmed": job.step3_confirmed,
            "step4_confirmed": job.step4_confirmed,
            "ontology_id": job.ontology_id,
            # Step 1 概念提取分批状态
            "step1_batches_total": job.step1_batches_total,
            "step1_batches_done": job.step1_batches_done,
            "step1_failed_batch": job.step1_failed_batch,
            # Step 2 实体提取分批状态
            "step2_batches_total": job.step2_batches_total,
            "step2_batches_done": job.step2_batches_done,
            "step2_failed_batch": job.step2_failed_batch,
            # Step 3 关系建模分组状态
            "step3_groups_total": job.step3_groups_total,
            "step3_groups_done": job.step3_groups_done,
            "step3_failed_group": job.step3_failed_group,
            # Step 3 跨组关系补充状态
            "step3_cross_group_done": job.step3_cross_group_done,
            "step3_cross_group_failed": job.step3_cross_group_failed,
            # Step 4 验证结果
            "step4_verification": job.step4_verification,
            "step4_report": job.step4_report,
            # 主要实体候选（step2 完成后）
            "primary_entity_candidates": job.primary_entity_candidates,
            "primary_entity_selected": job.primary_entity_selected,
            # 真实进度时间线
            "progress_stages": job.progress_stages,
        }
    }


@app.get("/ontology/build/{job_id}/stream")
async def build_stream(job_id: str):
    """SSE 端点：实时推送 Step1/Step2/Step3 的批次/分组增量结果。

    连接建立时：
    1. 先回放该 job 已完成的批次/分组结果（断线重连不丢数据，事件带 replayed=True）
    2. 若任务已结束（running_step=-1）补发终态事件（step_done/error）后关闭
    3. 否则订阅 queue 等待后续事件，15 秒无事件发心跳保活

    前端用 fetch + ReadableStream 订阅（复用 Authorization header，不用 EventSource）。
    """
    job = _get_job_or_404(job_id)

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue(maxsize=_SSE_QUEUE_MAXSIZE)
        _stream_subscribers[job_id].add(queue)
        try:
            # ── 1. 回放已完成批次/分组（断线重连续传，前端按名称去重天然幂等）──
            # Step1 回放：step1 未确认且有分批结果
            if not job.step1_confirmed and job.step1_batches_total > 0:
                for idx, batch in enumerate(job.step1_batch_results):
                    if batch:
                        yield _sse_format("batch_done", {
                            "batch_idx": idx,
                            "batches_done": idx + 1,
                            "batches_total": job.step1_batches_total,
                            "concepts": batch,
                            "replayed": True
                        })
            # Step2 回放：step2 未确认、有分批结果
            if job.step1_confirmed and not job.step2_confirmed and job.step2_batches_total > 0:
                for idx, batch in enumerate(job.step2_batch_results):
                    if batch:
                        yield _sse_format("batch_done", {
                            "batch_idx": idx,
                            "batches_done": idx + 1,
                            "batches_total": job.step2_batches_total,
                            "entities": batch,
                            "replayed": True
                        })
            # Step3 回放：step3 未确认、有分组结果
            if job.step2_confirmed and not job.step3_confirmed and job.step3_groups_total > 0:
                for idx, grp in enumerate(job.step3_group_results):
                    if grp and grp.get("relations"):
                        yield _sse_format("group_done", {
                            "group_idx": idx,
                            "groups_done": idx + 1,
                            "groups_total": job.step3_groups_total,
                            "relations": grp.get("relations", []),
                            "replayed": True
                        })
                if job.step3_cross_group_done and job.step3_cross_group_relations:
                    yield _sse_format("cross_group_done", {
                        "relations": job.step3_cross_group_relations,
                        "replayed": True
                    })

            # ── 2. 终态判断：任务已结束则补发终态事件并关闭 ──
            if job.running_step == -1:
                if job.error_message:
                    # 判断错误归属步骤：按 step1→2→3→4 失败标记优先级
                    # step4 无独立失败标记，step3 已确认且有错误 → 归属 step4
                    err_step = (1 if job.step1_failed_batch >= 0
                                else 2 if job.step2_failed_batch >= 0
                                else 3 if (job.step3_failed_group >= 0 or job.step3_cross_group_failed)
                                else 4 if (job.step3_confirmed or job.step4_verification is not None)
                                else 0)
                    yield _sse_format("error", {"step": err_step, "message": job.error_message})
                    return
                # step1 已完成（有 concepts）未确认 → 补发 step1 完成事件
                if job.step1_concepts and not job.step1_confirmed:
                    yield _sse_format("step_done", {
                        "step": 1,
                        "concepts": job.step1_concepts,
                        "total": len(job.step1_concepts)
                    })
                    return
                # step2 已完成（有 entities）未确认 → 补发 step2 完成事件
                if job.step2_entities and not job.step2_confirmed:
                    yield _sse_format("step_done", {
                        "step": 2,
                        "entities": job.step2_entities,
                        "primary_entity_candidates": job.primary_entity_candidates,
                        "total": len(job.step2_entities)
                    })
                    return
                # step3 已完成（有 relations）未确认 → 补发 step3 完成事件
                if job.step3_relations and not job.step3_confirmed:
                    yield _sse_format("step_done", {
                        "step": 3,
                        "relations": job.step3_relations,
                        "total": len(job.step3_relations)
                    })
                    return
                # step4 已完成（有 verification）未确认 → 补发 step4 完成事件
                if job.step4_verification and not job.step4_confirmed:
                    yield _sse_format("step_done", {
                        "step": 4,
                        "verification": job.step4_verification,
                        "report": job.step4_report
                    })
                    return
                # 任务未开始或已确认等下一阶段：不发终态，继续订阅等新事件

            # ── 3. 订阅 queue 等新事件（任务运行中）──
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_SSE_HEARTBEAT_TIMEOUT)
                except asyncio.TimeoutError:
                    # 发心跳（SSE 注释行），防止 nginx/浏览器因空闲超时掐断连接
                    yield ": heartbeat\n\n"
                    continue
                yield _sse_format(event["type"], event["data"])
                # 终态事件后关闭连接
                if event["type"] in ("step_done", "error"):
                    break
        finally:
            _stream_subscribers[job_id].discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # 禁用 nginx 缓冲，保证事件实时推送（非缓冲累积后批量发）
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/ontology/build/{job_id}")
async def build_get(job_id: str):
    """查询构建任务详情（断点续作用）。"""
    job = _get_job_or_404(job_id)
    return {"success": True, "data": job.dict()}


def _build_stage_graph(job: "BuildJob", stage: int) -> Dict[str, Any]:
    """构建某阶段的图谱预览数据（只读，nodes + links）。

    各阶段图谱内容：
    - stage=1: 概念节点（按 entity_type 着色），无边
    - stage=2: 概念节点 + 实体节点 + instance_of 边（实体颜色继承概念）
    - stage=3: 实体节点 + 本体内关系边
    - stage=4: 同 stage=3，存疑项节点/边标记 suspect=True（基于 step4_verification）

    Args:
        job: 构建任务
        stage: 阶段号 1-4

    Returns:
        {nodes: [...], links: [...]}
    """
    nodes = []
    links = []
    # 存疑项集合（step4 验证结果），用于 stage=4 标红
    suspect_names = set()
    if stage >= 4 and job.step4_verification:
        for s in (job.step4_verification.get("suspects") or []):
            if isinstance(s, dict):
                suspect_names.add(_normalize_name(s.get("item_name", "")))

    if stage >= 1:
        # 概念节点
        for c in (job.step1_concepts or []):
            nodes.append({
                "id": f"concept_{_normalize_name(c.get('name', ''))}",
                "name": c.get("name", ""),
                "node_type": "concept",
                "entity_type": c.get("entity_type", ""),
                "color": c.get("color") or _derive_concept_color(c.get("entity_type", ""), job.meta_entity_types),
                "description": c.get("description", ""),
            })

    if stage >= 2:
        # 实体节点 + instance_of 边
        # 概念名 → 颜色（实体颜色继承概念）
        concept_color_map = {
            _normalize_name(c.get("name", "")): c.get("color") or _derive_concept_color(c.get("entity_type", ""), job.meta_entity_types)
            for c in (job.step1_concepts or [])
        }
        for e in (job.step2_entities or []):
            ename = e.get("name", "")
            ename_norm = _normalize_name(ename)
            inst = e.get("instance_of", "")
            color = concept_color_map.get(_normalize_name(inst), "#5470c6")
            nodes.append({
                "id": f"entity_{ename_norm}",
                "name": ename,
                "node_type": "entity",
                "instance_of": inst,
                "color": color,
                "is_primary_candidate": bool(e.get("is_primary_candidate")),
                "suspect": ename_norm in suspect_names,
                "properties_count": len(e.get("properties") or []),
            })
            # instance_of 边（概念 → 实体）
            if inst:
                links.append({
                    "source": f"concept_{_normalize_name(inst)}",
                    "target": f"entity_{ename_norm}",
                    "relation_type": "instance_of",
                    "weight": 1.0,
                })

    if stage >= 3:
        # 本体内关系边
        for r in (job.step3_relations or []):
            src = _normalize_name(r.get("source", ""))
            tgt = _normalize_name(r.get("target", ""))
            if not src or not tgt:
                continue
            rname = r.get("relation_type", "关联")
            is_suspect = (stage >= 4
                          and (_normalize_name(r.get("source", "")) in suspect_names
                               or _normalize_name(r.get("target", "")) in suspect_names))
            links.append({
                "source": f"entity_{src}",
                "target": f"entity_{tgt}",
                "relation_type": rname,
                "weight": r.get("weight", 1.0),
                "suspect": is_suspect,
            })

    # stage=1 时去掉实体节点和边（只保留概念节点）
    if stage == 1:
        nodes = [n for n in nodes if n.get("node_type") == "concept"]
        links = []

    return {"nodes": nodes, "links": links}


@app.get("/ontology/build/{job_id}/graph")
async def build_get_graph(job_id: str, stage: int = 1):
    """获取构建任务某阶段的图谱预览数据（只读）。

    前端在每阶段确认前用此接口渲染图谱，直观查看中间产物分布。
    stage 范围 1-4，超出按最近阶段处理。

    Args:
        job_id: 构建任务 ID
        stage: 阶段号 1=概念 / 2=实体属性 / 3=关系 / 4=验证
    """
    job = _get_job_or_404(job_id)
    # stage 越界保护：限制在 1-4
    if stage < 1:
        stage = 1
    elif stage > 4:
        stage = 4
    graph = _build_stage_graph(job, stage)
    return {
        "success": True,
        "data": {
            "job_id": job_id,
            "stage": stage,
            "nodes": graph["nodes"],
            "links": graph["links"],
            "node_count": len(graph["nodes"]),
            "link_count": len(graph["links"]),
        }
    }


@app.put("/ontology/build/{job_id}/meta")
async def build_confirm_meta(
    job_id: str,
    entity_types: str = Form(...),
    relation_types: str = Form(...),
    granularity: str = Form("medium"),
    stage_hints: str = Form("")
):
    """用户确认或编辑元模型 + 粒度 + 阶段提示词。

    确认后元模型、粒度、阶段提示词固定，后续 step1/step2/step3/step4 的 LLM 调用遵守此约束。
    """
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成，不可修改")

    try:
        et_list = json.loads(entity_types) if isinstance(entity_types, str) else entity_types
        rt_list = json.loads(relation_types) if isinstance(relation_types, str) else relation_types
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"元模型 JSON 解析失败: {e}")

    if not isinstance(et_list, list) or not et_list:
        raise HTTPException(status_code=400, detail="entity_types 不能为空")
    if not isinstance(rt_list, list) or not rt_list:
        raise HTTPException(status_code=400, detail="relation_types 不能为空")

    # 解析粒度（非法值回退 medium）
    if granularity not in config.GRANULARITY_RANGES:
        granularity = "medium"
    # 解析阶段提示词
    hints_dict: Dict[int, str] = {}
    if stage_hints:
        try:
            parsed = json.loads(stage_hints) if isinstance(stage_hints, str) else stage_hints
            if isinstance(parsed, dict):
                hints_dict = {int(k): str(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"stage_hints 解析失败，忽略: {e}")

    async with build_lock:
        job.meta_entity_types = et_list
        job.meta_relation_types = rt_list
        job.granularity = granularity
        job.stage_hints = hints_dict
        job.meta_confirmed = True
        job.step = max(job.step, 1)  # 确认元模型后进入 step 1
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
        save_build_jobs_index()

    return {
        "success": True,
        "message": "元模型已确认，可执行概念提取",
        "data": {
            "job_id": job_id,
            "meta_entity_types": job.meta_entity_types,
            "meta_relation_types": job.meta_relation_types,
            "granularity": job.granularity,
            "stage_hints": job.stage_hints,
        }
    }


@app.post("/ontology/build/{job_id}/step1")
async def build_step1(job_id: str):
    """Step 1: LLM 从文档提取概念清单（类型层，后台异步执行）。

    前置条件：元模型已确认（meta_confirmed=True）。
    立即返回，LLM 调用在后台进行，前端通过 GET /progress 或 GET /build/{job_id} 轮询结果。
    用户可在后台执行期间离开页面，稍后回来查看。
    """
    job = _get_job_or_404(job_id)
    if not job.meta_confirmed:
        raise HTTPException(status_code=400, detail="请先确认元模型（PUT /ontology/build/{job_id}/meta）")
    if job.step1_confirmed:
        raise HTTPException(status_code=400, detail="概念清单已确认，如需重新提取请先撤销确认")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    # 判断是续跑（断点续作）还是首次提取
    is_resume = (job.step1_batches_total > 0
                 and job.step1_batches_done < job.step1_batches_total
                 and job.step1_failed_batch >= 0)

    # 启动后台任务，立即返回（清空陈旧错误，避免前端显示旧报错）
    async with build_lock:
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
    _set_job_progress(
        job_id, 1, 5,
        "继续提取概念..." if is_resume else "正在准备提取概念..."
    )
    task = asyncio.create_task(_background_extract_concepts(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "概念提取继续运行，从失败批次续跑..." if is_resume else "概念提取已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 1, "is_resume": is_resume}
    }


@app.put("/ontology/build/{job_id}/step1")
async def build_confirm_step1(job_id: str, concepts: str = Form(...)):
    """用户确认概念清单（可编辑后提交）。

    确认后才能执行 step2（实体+属性提取）。
    """
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")

    try:
        concepts_list = json.loads(concepts) if isinstance(concepts, str) else concepts
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"概念清单 JSON 解析失败: {e}")

    if not isinstance(concepts_list, list) or not concepts_list:
        raise HTTPException(status_code=400, detail="概念清单不能为空")

    async with build_lock:
        job.step1_concepts = concepts_list
        job.step1_confirmed = True
        job.error_message = None
        job.step = max(job.step, 2)
        job.update_time = datetime.now()
        save_build_job(job_id)

    return {
        "success": True,
        "message": "概念清单已确认，可执行实体+属性提取",
        "data": {"job_id": job_id, "step": job.step}
    }


@app.post("/ontology/build/{job_id}/step2")
async def build_step2(job_id: str):
    """Step 2: LLM 从文档提取实体+属性（实例层，后台异步执行）。

    前置条件：step1 已确认。
    立即返回，LLM 调用在后台进行，前端轮询结果。
    """
    job = _get_job_or_404(job_id)
    if not job.step1_confirmed:
        raise HTTPException(status_code=400, detail="请先确认概念清单（PUT /ontology/build/{job_id}/step1）")
    if job.step2_confirmed:
        raise HTTPException(status_code=400, detail="实体清单已确认，如需重新提取请先撤销确认")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    # 判断是续跑（断点续作）还是首次提取
    is_resume = (job.step2_batches_total > 0
                 and job.step2_batches_done < job.step2_batches_total
                 and job.step2_failed_batch >= 0)

    async with build_lock:
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
    _set_job_progress(
        job_id, 2, 5,
        "继续提取实体..." if is_resume else "正在准备提取实体..."
    )
    task = asyncio.create_task(_background_extract_entities(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "实体提取继续运行，从失败批次续跑..." if is_resume else "实体提取已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 2, "is_resume": is_resume}
    }


@app.put("/ontology/build/{job_id}/step2")
async def build_confirm_step2(
    job_id: str,
    entities: str = Form(...),
    primary_entity_selected: str = Form("")
):
    """用户确认实体清单（可编辑后提交）+ 勾选主要实体。

    确认后才能执行 step3（关系建模）。

    Args:
        entities: 实体清单 JSON（含 instance_of + properties）
        primary_entity_selected: 用户勾选的主要实体名 JSON 数组（Phase 3 多本体拆分用，Phase 2 仅标记）
    """
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")

    try:
        entities_list = json.loads(entities) if isinstance(entities, str) else entities
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"实体清单 JSON 解析失败: {e}")

    if not isinstance(entities_list, list) or not entities_list:
        raise HTTPException(status_code=400, detail="实体列表不能为空")

    # 解析主要实体勾选
    primary_selected: List[str] = []
    if primary_entity_selected:
        try:
            parsed = json.loads(primary_entity_selected) if isinstance(primary_entity_selected, str) else primary_entity_selected
            if isinstance(parsed, list):
                primary_selected = [str(n) for n in parsed]
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"primary_entity_selected 解析失败，忽略: {e}")

    async with build_lock:
        job.step2_entities = entities_list
        job.primary_entity_selected = primary_selected
        job.step2_confirmed = True
        job.error_message = None
        job.step = max(job.step, 3)
        job.update_time = datetime.now()
        save_build_job(job_id)

    return {
        "success": True,
        "message": "实体清单已确认，可执行关系建模",
        "data": {"job_id": job_id, "step": job.step, "primary_entity_selected": primary_selected}
    }


@app.post("/ontology/build/{job_id}/step3")
async def build_step3(job_id: str):
    """Step 3: LLM 关系建模（后台异步执行）。

    前置条件：step2 已确认。
    立即返回，LLM 调用在后台进行，前端轮询结果。
    """
    job = _get_job_or_404(job_id)
    if not job.step2_confirmed:
        raise HTTPException(status_code=400, detail="请先确认实体清单（PUT /ontology/build/{job_id}/step2）")
    if job.step3_confirmed:
        raise HTTPException(status_code=400, detail="关系清单已确认，如需重新建模请先撤销确认")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    # 判断是续跑（分组或跨组关系补充断点续作）还是首次构建
    is_resume = ((job.step3_groups_total > 0
                  and job.step3_groups_done < job.step3_groups_total
                  and job.step3_failed_group >= 0)
                 or (job.step3_groups_total > 0
                     and job.step3_groups_done == job.step3_groups_total
                     and not job.step3_cross_group_done
                     and job.step3_cross_group_failed))

    async with build_lock:
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
    _set_job_progress(
        job_id, 3, 5,
        "继续关系建模..." if is_resume else "正在准备关系建模..."
    )
    task = asyncio.create_task(_background_build_relations(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "关系建模继续运行，从断点续跑..." if is_resume else "关系建模已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 3, "is_resume": is_resume}
    }


@app.put("/ontology/build/{job_id}/step3")
async def build_confirm_step3(job_id: str, relations: str = Form(...)):
    """用户确认关系清单（可编辑后提交）。

    确认后才能执行 step4（验证+报告）。
    """
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")

    try:
        relations_list = json.loads(relations) if isinstance(relations, str) else relations
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"关系清单 JSON 解析失败: {e}")

    if not isinstance(relations_list, list):
        raise HTTPException(status_code=400, detail="关系清单必须为数组")

    async with build_lock:
        job.step3_relations = relations_list
        job.step3_confirmed = True
        job.error_message = None
        job.step = max(job.step, 4)
        job.update_time = datetime.now()
        save_build_job(job_id)

    return {
        "success": True,
        "message": "关系清单已确认，可执行验证+报告",
        "data": {"job_id": job_id, "step": job.step}
    }


@app.post("/ontology/build/{job_id}/step4")
async def build_step4(job_id: str):
    """Step 4: LLM 自检验证 + 报告生成（后台异步执行）。

    前置条件：step3 已确认。
    立即返回，LLM 调用在后台进行，前端轮询结果。
    """
    job = _get_job_or_404(job_id)
    if not job.step3_confirmed:
        raise HTTPException(status_code=400, detail="请先确认关系清单（PUT /ontology/build/{job_id}/step3）")
    if job.step4_confirmed:
        raise HTTPException(status_code=400, detail="验证结果已确认，如需重新验证请先撤销确认")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    async with build_lock:
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
    _set_job_progress(job_id, 4, 5, "正在准备验证...")
    task = asyncio.create_task(_background_verify_and_report(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "验证+报告生成已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 4}
    }


@app.put("/ontology/build/{job_id}/step4")
async def build_confirm_step4(job_id: str):
    """用户确认验证结果，触发正式本体生成。

    前置条件：step4 验证已完成（step4_verification 非空）。
    Phase 2 生成单本体（多本体实例化留待 Phase 3）。
    """
    job = _get_job_or_404(job_id)
    if not job.step4_verification:
        raise HTTPException(status_code=400, detail="请先执行验证（POST /ontology/build/{job_id}/step4）")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")

    # 生成正式本体（同步执行，无 LLM 调用，快速完成）
    try:
        new_oid = _generate_formal_ontology(job_id)
    except Exception as e:
        logger.error(f"[{job_id}] 正式本体生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"本体生成失败: {str(e)[:150]}")

    async with build_lock:
        job.ontology_id = new_oid
        job.step4_confirmed = True
        job.step = 5
        job.status = "completed"
        job.running_step = -1
        job.progress = 100
        job.progress_message = f"本体生成成功！共 {len(job.step2_entities or [])} 个实体，{len(job.step3_relations or [])} 条关系"
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
        save_build_jobs_index()

    logger.info(f"[{job_id}] 五阶段构建完成，生成本体: {new_oid}")
    return {
        "success": True,
        "message": "验证结果已确认，正式本体已生成",
        "data": {"job_id": job_id, "ontology_id": new_oid, "step": job.step}
    }


@app.delete("/ontology/build/{job_id}")
async def build_delete(job_id: str):
    """删除构建任务（不影响已生成的正式本体）。"""
    _get_job_or_404(job_id)  # 不存在则 404
    async with build_lock:
        del build_jobs_db[job_id]
        # 删除任务文件
        job_file = _build_job_file(job_id)
        if os.path.exists(job_file):
            os.remove(job_file)
        save_build_jobs_index()
    return {"success": True, "message": "构建任务已删除"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10256, log_config=None)
