"""本体服务（ontology-service）。

负责本体的构建与管理，建立实体类型之间的语义关系，提供知识图谱可视化数据。
A 阶段实现：多本体隔离、本体模型类型约束、JSON 属性、持久化加固、路径查询、示例数据。

数据持久化策略：
- 每个本体独立一个 JSON 文件 data/ontology_{id}.json（含本体元信息 + 实体 + 关系）
- data/ontologies_index.json 存本体列表索引
- 原子写入（临时文件 + rename + .bak 备份）+ filelock 跨进程锁 + asyncio.Lock 协程锁
"""

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

from fastapi import FastAPI, HTTPException, Form, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
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
from llm_client import call_llm, call_llm_json
import build_prompts
import config
from text_batcher import split_into_batches, extract_headings, split_by_headings
from migration import migrate_ontology_dict, backup_data_dir

# ---------- AI 构建聊天 Agent ----------
from agent import orchestrator as agent_orchestrator
from agent import prompts as agent_prompts

# ---------- 数据模型（从 models.py 导入，Phase 1 抽离）----------
from models import (
    SCHEMA_VERSION, EntityType, RelationType, PropertySchema,
    PropertyHistoryEntry, PropertyVerification, Property,
    ConceptType, Entity, Relation, OntologyModel,
    EntityTypeRelation, TemplateEntityTypeSchema, TemplateEntityTypeRelation,
    TemplateConceptSchema, OntologyTemplateModel, BuildJob,
    get_inherited_property_schema,
)
# 向后兼容别名：旧代码引用 TemplateModel 时仍可工作
TemplateModel = OntologyTemplateModel

# ---------- Repository 抽象层（Phase 1：薄包装现有 JSON 存储）----------
from repository import get_repository
repo = get_repository()

# ---------- 统一日志 ----------
from logging_config import setup_logging
setup_logging("ontology-service")
logger = logging.getLogger("ontology-service")

# ---------- OWL 2 导出（Phase 2：Pydantic → OWL/RDF）----------
# 懒加载：owlready2 较重，仅在首次导出时初始化
try:
    from owl_builder import export_ontology_to_owl
    _owl_available = True
except Exception as _owl_import_err:  # owlready2 未安装或损坏时降级
    logger.warning(f"OWL 导出模块加载失败，相关接口将不可用: {_owl_import_err}")
    _owl_available = False
    export_ontology_to_owl = None  # type: ignore

app = FastAPI(
    title="本体服务",
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

# ---------- 默认本体模型 ----------
# 创建本体时若未指定类型，使用以下默认类型集
# 本体模型定义粗粒度类型分类（实体类型/实体/属性/事件），实体类型在此基础上做细粒度类型定义
DEFAULT_ENTITY_TYPES = [
    {"name": "实体类型", "color": "#5470c6"},
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
# SCHEMA_VERSION 已从 models.py 导入


def _entity_type_from_dict(d: dict, ontology_id: str = "",
                           now: Optional[datetime] = None) -> EntityType:
    """从 dict 构造 EntityType，自动填充缺失的必填字段（id/create_time/update_time）。

    v3 EntityType 合并了原 ConceptType，需要 id/create_time/update_time，
    但 DEFAULT_ENTITY_TYPES 和导入数据可能只有 name/color。
    此辅助函数统一处理，避免各调用点重复填充逻辑。
    """
    now = now or datetime.now()
    pschema = []
    for p in d.get("property_schema", []) or []:
        if isinstance(p, PropertySchema):
            pschema.append(p)
        elif isinstance(p, dict):
            pschema.append(PropertySchema(
                name=p.get("name", ""),
                category=p.get("category", "descriptive"),
                data_type=p.get("data_type", "string"),
                unit=p.get("unit", ""),
                required=p.get("required", False),
                description=p.get("description", ""),
            ))
    return EntityType(
        id=d.get("id") or f"et_{uuid.uuid4().hex[:8]}",
        ontology_id=ontology_id or d.get("ontology_id", ""),
        name=d.get("name", ""),
        description=d.get("description", ""),
        color=d.get("color"),
        property_schema=pschema,
        source_snippet=d.get("source_snippet", ""),
        parent_entity_type_id=d.get("parent_entity_type_id"),
        parent_entity_type_name=d.get("parent_entity_type_name"),
        create_time=d.get("create_time") or now,
        update_time=d.get("update_time") or now,
    )


# ---------- 数据模型已抽离至 models.py ----------
# EntityType / RelationType / PropertySchema / PropertyHistoryEntry /
# PropertyVerification / Property / ConceptType / Entity / Relation /
# OntologyModel / TemplateConceptSchema / OntologyTemplateModel / BuildJob
# 均在顶部通过 `from models import ...` 导入


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
        event_type: 事件类型（parse_done / batch_done / group_done / cross_group_done / step_done / error / progress）
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

    防止"命中率（%）"与"命中率(%)"被误判为不同实体类型。
    """
    if not name:
        return ""
    s = name.strip()
    # 全角括号转半角
    s = s.replace("（", "(").replace("）", ")")
    # 全角空格转半角
    s = s.replace("\u3000", " ")
    return s


def _merge_property_schemas(existing: list, incoming: list) -> list:
    """合并两个 property_schema 列表，按属性名去重（并集）。

    跨批提取同一实体类型时，不同批次可能补充不同的属性骨架。
    合并策略：按归一化属性名去重，首次出现的属性保留；后续同名属性补充缺失字段。
    """
    merged = list(existing or [])
    seen = {_normalize_name(p.get("name", "")) for p in merged if isinstance(p, dict)}
    for p in (incoming or []):
        if not isinstance(p, dict):
            continue
        pname = _normalize_name(p.get("name", ""))
        if not pname:
            continue
        if pname not in seen:
            merged.append(p)
            seen.add(pname)
        else:
            # 同名属性：补充缺失字段（description/unit 等取首个非空）
            for ex in merged:
                if _normalize_name(ex.get("name", "")) == pname:
                    for k in ("description", "unit", "data_type", "category"):
                        if not ex.get(k) and p.get(k):
                            ex[k] = p[k]
                    break
    return merged


def _merge_entity_types(all_concepts: list) -> list:
    """合并多批提取的实体类型，按 name 去重 + property_schema 并集 + 父类型解析（v3）。

    跨批冗余消除策略：
    - 同名实体类型（归一化后）合并为一条
    - property_schema 取并集（不同批次可能补充不同属性骨架）
    - parent_entity_type_name 取首个非空（兼容旧 parent_concept_name）
    - description / source_snippet 取首个非空

    Args:
        all_concepts: 所有批次的实体类型列表（已展开为一维）

    Returns:
        去重合并后的实体类型列表，保持首次出现顺序
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
            # description / source_snippet 取首个非空
            if not existing.get("description") and c.get("description"):
                existing["description"] = c["description"]
            if not existing.get("source_snippet") and c.get("source_snippet"):
                existing["source_snippet"] = c["source_snippet"]
            # v3：parent_entity_type_name 取首个非空（兼容旧 parent_concept_name）
            parent_v3 = c.get("parent_entity_type_name") or c.get("parent_concept_name")
            if parent_v3 and not (existing.get("parent_entity_type_name")
                                  or existing.get("parent_concept_name")):
                existing["parent_entity_type_name"] = parent_v3
            # property_schema 取并集
            existing["property_schema"] = _merge_property_schemas(
                existing.get("property_schema", []), c.get("property_schema", [])
            )
    return [merged[k] for k in order]


def _merge_entity_type_relations(all_relations: list) -> list:
    """合并多批提取的实体类型间关系，按 (source, target, relation_type) 去重（v3 新增）。

    跨批冗余消除策略：
    - 相同 (source_entity_type_name, target_entity_type_name, relation_type) 的关系合并为一条
    - description / source_snippet 取首个非空

    Args:
        all_relations: 所有批次的实体类型关系列表（已展开为一维）

    Returns:
        去重合并后的实体类型关系列表
    """
    merged = {}
    order = []
    for r in all_relations:
        if not isinstance(r, dict):
            continue
        src = _normalize_name(r.get("source_entity_type_name", ""))
        tgt = _normalize_name(r.get("target_entity_type_name", ""))
        rt = (r.get("relation_type") or "").strip()
        if not src or not tgt or not rt:
            continue
        key = f"{src}|{tgt}|{rt}"
        if key not in merged:
            merged[key] = dict(r)
            order.append(key)
        else:
            existing = merged[key]
            if not existing.get("description") and r.get("description"):
                existing["description"] = r["description"]
            if not existing.get("source_snippet") and r.get("source_snippet"):
                existing["source_snippet"] = r["source_snippet"]
    return [merged[k] for k in order]


def _parse_step1_llm_response(resp: Any) -> tuple:
    """解析 step1 LLM 响应，兼容 v2（数组）和 v3（对象）格式。

    v3 格式：{"entity_types": [...], "entity_type_relations": [...]}
    v2 格式：[concept1, concept2, ...]（无类型间关系）

    Returns:
        (entity_types_list, entity_type_relations_list)
    """
    if isinstance(resp, dict):
        # v3 格式
        et_list = resp.get("entity_types") or resp.get("concepts") or []
        etr_list = resp.get("entity_type_relations") or []
        return et_list, etr_list
    elif isinstance(resp, list):
        # v2 格式（无类型间关系）
        return resp, []
    else:
        return [], []


def _parse_step2_llm_response(resp: Any) -> tuple:
    """解析 step2 LLM 响应，兼容 v2（数组）和 v3（对象）格式。

    v3 格式：{"entities": [...], "relations": [...]}
    v2 格式：[entity1, entity2, ...]（无实例间关系，关系由旧 step3 单独提取）

    Returns:
        (entities_list, relations_list)
    """
    if isinstance(resp, dict):
        ent_list = resp.get("entities") or []
        rel_list = resp.get("relations") or []
        return ent_list, rel_list
    elif isinstance(resp, list):
        # v2 格式（无实例间关系）
        return resp, []
    else:
        return [], []


def _group_entity_types(concepts: list, group_size: int) -> list:
    """按 type 聚类后再按 group_size 切分，同分类（entity_type）实体类型尽量同组。
    同分类实体类型之间关系最密集，同组内能让 LLM 建立更完整的关系网。
    某分类实体类型过多仍切多组；某分类实体类型极少单独成组。

    Args:
        concepts: 已确认的实体类型清单
        group_size: 每组实体类型数上限

    Returns:
        实体类型分组列表，每个元素是该组的实体类型子集
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
    """合并多批/多组构建的实体，按 name 去重 + 属性矛盾消除。

    跨批冗余/矛盾消除策略：
    - 同名实体（归一化后）合并为一条
    - instance_of 不覆盖（首次出现的已受实体类型清单约束）
    - properties（List[Dict] 格式）按属性 name 去重并集：
      · 同名属性值矛盾时，优先取有 source_snippet 的值；都有则保留首次（记日志）
      · 现有值为空时用新值补充
    - source_snippet 取首个非空

    兼容旧 Dict[str,str] 格式（浅合并）。

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
            # instance_of 不覆盖（首次出现的已受实体类型清单约束）
            if not existing.get("instance_of") and e.get("instance_of"):
                existing["instance_of"] = e["instance_of"]
            # source_snippet 取首个非空
            if not existing.get("source_snippet") and e.get("source_snippet"):
                existing["source_snippet"] = e["source_snippet"]
            # properties 合并：按格式分流
            ex_props = existing.get("properties")
            new_props = e.get("properties")
            if isinstance(ex_props, list) or isinstance(new_props, list):
                # 新格式 List[Dict]：按属性 name 去重并集 + 矛盾消除
                ex_list = ex_props if isinstance(ex_props, list) else []
                new_list = new_props if isinstance(new_props, list) else []
                ex_by_name = {}
                for p in ex_list:
                    if isinstance(p, dict):
                        ex_by_name[_normalize_name(p.get("name", ""))] = p
                for p in new_list:
                    if not isinstance(p, dict):
                        continue
                    pname = _normalize_name(p.get("name", ""))
                    if not pname:
                        continue
                    if pname not in ex_by_name:
                        # 新属性：追加
                        ex_list.append(p)
                        ex_by_name[pname] = p
                    else:
                        # 同名属性：矛盾消除
                        ex_p = ex_by_name[pname]
                        ex_val = ex_p.get("value")
                        new_val = p.get("value")
                        ex_has_src = bool(ex_p.get("source_snippet"))
                        new_has_src = bool(p.get("source_snippet"))
                        if ex_val in (None, "", []) and new_val not in (None, "", []):
                            # 现有值为空 → 用新值补充
                            ex_p["value"] = new_val
                            if new_has_src and not ex_has_src:
                                ex_p["source_snippet"] = p.get("source_snippet")
                        elif (ex_val not in (None, "", [])
                              and new_val not in (None, "", [])
                              and str(ex_val) != str(new_val)):
                            # 值矛盾：优先取有 source_snippet 的；都有则保留首次
                            if new_has_src and not ex_has_src:
                                ex_p["value"] = new_val
                                ex_p["source_snippet"] = p.get("source_snippet")
                            # 都有 source_snippet 时保留首次，仅记日志
                            logger.debug(
                                f"实体「{existing.get('name')}」属性「{pname}」跨批值矛盾: "
                                f"{ex_val} vs {new_val}，保留首次"
                            )
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


def _derive_type_color(entity_type: str, meta_entity_types: list, used_colors: Optional[set] = None) -> str:
    """根据实体类型的 entity_type 推导颜色。

    颜色来源优先级：
    1. 本体模型中该类型已配置的颜色（手动构建/本体模型场景保持用户选择）
    2. 调色板轮转兜底：从 DEFAULT_COLORS 中选取一个本批未用过的颜色，
       保证不同实体类型自动区分颜色；全部用过则从头循环

    Args:
        entity_type: 实体类型归属的本体模型类型名
        meta_entity_types: 已确认的本体模型实体类型 [{"name","color"}]
        used_colors: 本批已分配的颜色集合（None 表示无状态，仅走本体模型匹配）

    Returns:
        颜色 hex 值
    """
    for t in meta_entity_types:
        if t.get("name") == entity_type:
            return t.get("color", "#5470c6")
    if used_colors is None:
        return "#5470c6"
    for c in build_prompts.DEFAULT_COLORS:
        if c not in used_colors:
            return c
    # 调色板全部用过，从头循环（按已用数量取模，保持稳定）
    return build_prompts.DEFAULT_COLORS[len(used_colors) % len(build_prompts.DEFAULT_COLORS)]


def _adjust_hex_color(hex_color: str, ratio: float) -> str:
    """按比例调整 hex 颜色明度，返回 #rrggbb。

    ratio>0 向白色靠近（变浅），ratio<0 向黑色靠近（变深）。
    用于子类型继承父类型色系时派生深浅不同的颜色，使父子「同色系、不同颜色」。

    Args:
        hex_color: 形如 #rrggbb 的颜色（也兼容不带 # 的 6 位 hex）
        ratio: 明度调整比例，0 表示不变，取值范围建议 [-1, 1]

    Returns:
        调整后的 #rrggbb 颜色；非法输入回退默认蓝 #5470c6
    """
    hex_color = (hex_color or "").strip().lstrip("#")
    if len(hex_color) != 6:
        return "#5470c6"
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except ValueError:
        return "#5470c6"

    def _clamp(v: int) -> int:
        return max(0, min(255, v))

    if ratio >= 0:
        r = _clamp(int(r + (255 - r) * ratio))
        g = _clamp(int(g + (255 - g) * ratio))
        b = _clamp(int(b + (255 - b) * ratio))
    else:
        f = -ratio
        r = _clamp(int(r * (1 - f)))
        g = _clamp(int(g * (1 - f)))
        b = _clamp(int(b * (1 - f)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _enrich_types_with_color(concepts: list, meta_entity_types: list) -> list:
    """为合并后的实体类型列表填充 color 字段（v3 支持父子同色系）。

    颜色分配（两遍）：
    1. 顶层类型（无父类型，或父类型不在本批清单中）分配主色：优先本体模型匹配，
       否则调色板轮转兜底；
    2. 子类型继承父类型颜色，按层级深度 + 兄弟序号做明度梯度（同色系、深浅有别）。

    已带 color 的类型（LLM 旧格式）保留原色，但其子类型仍继承该色。

    Args:
        concepts: 合并去重后的实体类型列表（含 parent_entity_type_name）
        meta_entity_types: 已确认的本体模型实体类型

    Returns:
        填充 color 后的实体类型列表（原地修改并返回）
    """
    by_name = {}
    for c in concepts:
        n = _normalize_name(c.get("name", ""))
        if n:
            by_name[n] = c

    # 识别顶层 + 建立父名 → 子类型列表映射
    roots = []
    children_map = {}
    for c in concepts:
        cn = _normalize_name(c.get("name", ""))
        pname = _normalize_name(c.get("parent_entity_type_name")
                                or c.get("parent_concept_name") or "")
        if pname and pname in by_name and pname != cn:
            children_map.setdefault(pname, []).append(c)
        else:
            roots.append(c)

    # 顶层分配主色：按序号循环调色板，第 2+ 轮叠加明度偏移
    # （修复：旧实现用 len(used_colors) % 8 取模，set 饱和在 8 后永远取 0 号蓝色，
    #   导致 45 个顶层类型只有前 8 个有区分色、其余全蓝）
    used_colors = set()
    palette_size = len(build_prompts.DEFAULT_COLORS)
    for i, c in enumerate(roots):
        if not c.get("color"):
            # 优先本体模型已配置的颜色
            base = ""
            for t in meta_entity_types or []:
                if t.get("name") == c.get("entity_type", ""):
                    base = t.get("color") or ""
                    break
            if not base:
                base = build_prompts.DEFAULT_COLORS[i % palette_size]
                cycle = i // palette_size
                if cycle > 0:
                    # 每轮叠加明度偏移：第1轮 -0.16（加深），第2轮 +0.24（变浅），第3轮 -0.32...
                    # 保证跨轮颜色互异，轮内保持同色系渐变
                    offset = -0.16 * ((cycle + 1) // 2) if cycle % 2 == 1 else 0.24 * (cycle // 2)
                    base = _adjust_hex_color(base, offset)
            c["color"] = base
        used_colors.add(c["color"])

    # 迭代式为子类型派生同色系颜色（visited 防环）
    stack = [(c, 0) for c in roots]
    visited = {_normalize_name(c.get("name", "")) for c in roots}
    while stack:
        parent, depth = stack.pop()
        parent_color = parent.get("color") or "#5470c6"
        parent_name = _normalize_name(parent.get("name", ""))
        for i, child in enumerate(children_map.get(parent_name, [])):
            cname = _normalize_name(child.get("name", ""))
            if cname in visited:
                continue
            visited.add(cname)
            if not child.get("color"):
                # depth 主偏移 + 兄弟序号微调，确保同父的兄弟子类型颜色也略有区分
                ratio = min(0.18 + 0.12 * depth + 0.05 * i, 0.45)
                child["color"] = _adjust_hex_color(parent_color, ratio)
            stack.append((child, depth + 1))
    return concepts


# ---------- 阶段进度跟踪（真实进度条）----------
# progress_stages 记录每个阶段的开始/结束时间，前端按时间线展示真实进度
# v3 四阶段（已更名为）：0=文档解析, 1=本体提取, 2=实体提取, 3=分析验证, 4=保留兼容旧任务
_STAGE_NAMES = {
    0: "文档解析",
    1: "本体提取",
    2: "实体提取",
    3: "分析验证",
    4: "分析验证",  # 兼容旧 v2 任务（旧 step4 = 验证）
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


def _pack_heading_segments(text: str, headings: list, max_chars: int) -> list:
    """把一组章节标题按字符数连续打包成批，返回 [{"text", "titles"}]。

    用于「规划未覆盖的剩余章节」：相邻章节累积，超限切批，避免一章一批的碎片化。
    首段自动并入第一个标题前的文档开头内容（前言/目录）。
    """
    if not headings:
        return []
    segments = []
    if headings[0]["start"] > 0:
        segments.append((0, headings[0]["start"], ""))
    for h in headings:
        segments.append((h["start"], h["end"], h["title"]))
    batches = []
    buf, buf_titles, buf_len = "", [], 0
    for start, end, title in segments:
        seg = text[start:end]
        if buf_len and buf_len + len(seg) > max_chars:
            # 当前批已累积到下限（3000 字）则切批；否则并入（避免过碎）
            if buf_len >= 3000:
                batches.append({"text": buf, "titles": list(buf_titles)})
                buf, buf_titles, buf_len = "", [], 0
            else:
                buf += seg
                if title:
                    buf_titles.append(title)
                buf_len = len(buf)
                continue
        buf += seg
        if title:
            buf_titles.append(title)
        buf_len = len(buf)
    if buf.strip():
        batches.append({"text": buf, "titles": list(buf_titles)})
    return batches


def _split_oversize_batch(text: str, titles: list, max_chars: int) -> list:
    """超长批次内句级切分（保留原标题标注），返回 [{"text", "titles"}]。"""
    if len(text) <= max_chars * 1.3:
        return [{"text": text, "titles": titles}]
    subs = split_into_batches(text, max_chars=max_chars, overlap=config.STEP1_BATCH_OVERLAP)
    return [{"text": s, "titles": list(titles)} for s in subs]


def _build_step1_batches(job) -> tuple:
    """构建 step1 分批：章节感知 + LLM 构建规划辅助，保证「规划显示批数 = 实际批数」。

    规则：
    1. 提取文档章节标题（extract_headings）
    2. 若 LLM 规划覆盖 ≥50% 的章节 → 规划批优先（同域内容同批），
       未覆盖章节按大小打包为剩余批（不再一章一批）；规划批文本区间重叠时裁剪避免重复
    3. 规划无效/覆盖不足 → 纯章节打包（split_by_headings），超长章内切分
    4. 无章节结构 → 字符切分

    Returns:
        (batches, batch_titles)：批次文本列表 + 每批章节标题（进度条显示用）
    """
    headings = extract_headings(job.source_text)
    if headings:
        title2h = {h["title"]: h for h in headings}
        covered = set()
        plan_groups = []  # 每个元素: 章节 dict 列表（按位置升序）
        if job.step1_plan:
            for b in job.step1_plan:
                hs = sorted(
                    (title2h[t] for t in (b.get("titles") or [])
                     if t in title2h and t not in covered),
                    key=lambda h: h["start"],
                )
                if not hs:
                    continue
                covered.update(h["title"] for h in hs)
                plan_groups.append(hs)
        if len(covered) >= max(1, len(headings) // 2):
            # 规划覆盖过半：采用规划分组 + 未覆盖章节打包
            rest = [h for h in headings if h["title"] not in covered]
            rest_batches = _pack_heading_segments(job.source_text, rest, config.STEP1_BATCH_MAX_CHARS)
            # 规划批按位置裁剪重叠区间（如目录行同时被多个规划批引用时，后一批跳过重复部分）
            plan_groups.sort(key=lambda g: g[0]["start"])
            final = []
            prev_end = 0
            for g in plan_groups:
                start = max(g[0]["start"], prev_end)
                end = g[-1]["end"]
                if end <= start:
                    continue
                text = job.source_text[start:end]
                final.extend(_split_oversize_batch(text, [h["title"] for h in g], config.STEP1_BATCH_MAX_CHARS))
                prev_end = max(prev_end, end)
            final.extend(rest_batches)
            if final:
                return [f["text"] for f in final], [f["titles"] for f in final]
        # 规划不足/无效 → 纯章节打包
        packed = split_by_headings(
            job.source_text, headings, max_chars=config.STEP1_BATCH_MAX_CHARS
        )
        if packed:
            return [g["text"] for g in packed], [g["titles"] for g in packed]
    # 回退：无章节结构 → 字符切分
    if len(job.source_text) <= config.STEP1_BATCH_THRESHOLD_CHARS:
        return [job.source_text], [[]]
    batches = split_into_batches(
        job.source_text,
        max_chars=config.STEP1_BATCH_MAX_CHARS,
        overlap=config.STEP1_BATCH_OVERLAP,
    )
    return batches, [[] for _ in batches]


async def _background_extract_entity_types(job_id: str) -> None:
    """后台任务：Step 1 本体提取（v3 类型层，LLM调用，支持长文档分批 + 断点续作）。

    v3 重构：从文档提取本体（含层级 parent_entity_type_name + property_schema）
    + 类型间关系（EntityTypeRelation），注入粒度预设和阶段提示词。
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
        # 已有完整 step1_entity_types 且无失败 → 直接结束（防重复跑）
        # 兼容旧任务：step1_entity_types 为空时回退检查 step1_concepts
        if not is_resume and (job.step1_entity_types or job.step1_concepts) and job.step1_failed_batch < 0:
            _set_job_progress(job_id, -1, 100, "本体提取已完成")
            _mark_stage_finished(job_id, 1)
            # 补推 step_done：秒完成场景下前端收不到任何事件会导致
            # 顶部下拉不更新、确认流程不点亮、用户误以为任务卡住
            existing_types = job.step1_entity_types or job.step1_concepts
            _emit_event(job_id, "step_done", {
                "step": 1,
                "entity_types": existing_types,
                "entity_type_relations": job.step1_entity_type_relations or [],
                "concepts": existing_types,  # 兼容旧前端
                "total": len(existing_types)
            })
            return

        # ---- 2. 重建 batches（无论首次还是续跑都重新切分，纯函数结果稳定）----
        # 优先使用 LLM 构建规划的章节方案（同一领域父子类型同批），回退字符切分
        batches, batch_titles = _build_step1_batches(job)
        total = len(batches)

        # 首次运行：记录总批数
        if job.step1_batches_total == 0:
            async with build_lock:
                job.step1_batches_total = total
                # 扩容 step1_batch_results 和 step1_batch_relations_results 到 total 长度
                while len(job.step1_batch_results) < total:
                    job.step1_batch_results.append([])
                while len(job.step1_batch_relations_results) < total:
                    job.step1_batch_relations_results.append([])
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
                while len(job.step1_batch_relations_results) < total:
                    job.step1_batch_relations_results.append([])
                save_build_job(job_id)

        total = job.step1_batches_total
        # 待处理批次：batch_results 为空（[] 或不存在）的批次（兼容断点续作）
        pending_indices = [
            idx for idx in range(total)
            if idx >= len(job.step1_batch_results) or not job.step1_batch_results[idx]
        ]
        logger.info(
            f"[{job_id}] Step1 本体提取：共 {total} 批，"
            f"{'续跑 ' + str(len(pending_indices)) + ' 批待处理' if is_resume else '首次全部 ' + str(len(pending_indices)) + ' 批'}"
            f"，并发 {config.LLM_CONCURRENCY}"
        )

        # ---- 3. 并行跑所有待处理批次 ----
        stage_hint_1 = job.stage_hints.get(1, "") if job.stage_hints else ""
        # 注入解析阶段识别的层级提示（顶层父类建议），强化三级层级提取
        if job.step1_hierarchy_hint:
            stage_hint_1 = (
                (stage_hint_1 + "\n") if stage_hint_1 else ""
            ) + f"【层级提示】{job.step1_hierarchy_hint}"
        if pending_indices:
            sem = asyncio.Semaphore(config.LLM_CONCURRENCY)

            async def _run_type_batch(idx: int):
                """单批本体提取（并行任务单元）：调 LLM → 解析 v3 响应 → 持久化 → 推送 SSE。"""
                async with sem:
                    batch_text = batches[idx] if idx < len(batches) else ""
                    messages = build_prompts.build_step1_batch_messages(
                        batch_text, job.name, job.meta_entity_types,
                        batch_idx=idx, total_batches=total,
                        granularity=job.granularity, stage_hint=stage_hint_1,
                        template=job.ontology_model_snapshot, template_mode=job.ontology_model_mode
                    )
                    step1_max_tokens, step1_thinking = config.get_llm_params("step1")
                    raw_resp = await _llm_json_async(messages, temperature=0.3, max_tokens=step1_max_tokens, thinking_type=step1_thinking)
                    # v3：解析 LLM 响应（兼容 v2 数组和 v3 对象格式）
                    batch_entity_types, batch_et_relations = _parse_step1_llm_response(raw_resp)
                    if not isinstance(batch_entity_types, list):
                        raise ValueError(
                            f"第 {idx + 1}/{total} 批返回格式异常（entity_types 非数组），"
                            f"原始类型: {type(batch_entity_types).__name__}"
                        )
                    # 持久化本批结果（锁内，避免并发写冲突）
                    async with build_lock:
                        while len(job.step1_batch_results) <= idx:
                            job.step1_batch_results.append([])
                        while len(job.step1_batch_relations_results) <= idx:
                            job.step1_batch_relations_results.append([])
                        job.step1_batch_results[idx] = batch_entity_types
                        job.step1_batch_relations_results[idx] = batch_et_relations
                        job.step1_batches_done = sum(1 for r in job.step1_batch_results[:total] if r)
                        job.step1_failed_batch = -1
                        job.step1_failed_reason = None
                        job.update_time = datetime.now()
                        save_build_job(job_id)
                    done = job.step1_batches_done
                    # 进度条展示本批章节标题（有规划时），让用户知道 AI 正在处理哪部分
                    titles_now = (
                        batch_titles[idx] if idx < len(batch_titles) and batch_titles[idx] else []
                    )
                    titles_desc = f"（{'/'.join(titles_now[:2])}）" if titles_now else ""
                    logger.info(
                        f"[{job_id}] Step1 第 {idx + 1}/{total} 批完成{titles_desc}: "
                        f"{len(batch_entity_types)} 个类型, {len(batch_et_relations)} 条类型间关系（{done}/{total}）"
                    )
                    _set_job_progress(
                        job_id, 1,
                        10 + int(85 * done / max(total, 1)),
                        # 前端任务标签已显示「X/Y 批」批次进度，message 只补充剩余数与当前章节
                        f"剩余 {total - done} 批处理中{titles_desc}..."
                        if total > 1 and done < total else "本批提取完成，正在汇总..."
                    )
                    _emit_event(job_id, "batch_done", {
                        "batch_idx": idx,
                        "batches_done": done,
                        "batches_total": total,
                        "entity_types": batch_entity_types,
                        "entity_type_relations": batch_et_relations,
                        "concepts": batch_entity_types,  # 兼容旧前端
                    })
                    return idx

            _set_job_progress(
                job_id, 1, 10,
                f"正在并行提取本体（{len(pending_indices)} 批，并发 {config.LLM_CONCURRENCY}）..."
                if total > 1 else "正在调用AI提取本体..."
            )
            # 并行执行，return_exceptions=True 保证单批失败不影响其他批
            results = await asyncio.gather(
                *[_run_type_batch(idx) for idx in pending_indices],
                return_exceptions=True
            )
            # 检查失败批次
            failures = [(pending_indices[i], r) for i, r in enumerate(results) if isinstance(r, Exception)]
            if failures:
                failed_idx, failed_exc = failures[0]
                succeeded = len(pending_indices) - len(failures)
                logger.error(
                    f"[{job_id}] Step1 并行提取 {len(failures)}/{len(pending_indices)} 批失败，"
                    f"首个失败: 第 {failed_idx + 1} 批: {failed_exc}"
                )
                async with build_lock:
                    job.running_step = -1
                    job.progress = 0
                    job.step1_failed_batch = failed_idx
                    job.step1_failed_reason = str(failed_exc)[:500]
                    job.error_message = f"第 {failed_idx + 1}/{total} 批失败: {str(failed_exc)[:500]}"
                    job.progress_message = (
                        f"第 {failed_idx + 1}/{total} 批失败，可点击继续提取续跑"
                        f"（其余 {succeeded} 批已成功）" if succeeded else f"第 {failed_idx + 1}/{total} 批失败，可点击继续提取续跑"
                    )
                    job.update_time = datetime.now()
                    save_build_job(job_id)
                await _finalize_task_chat(job_id, 1, False, job.error_message or "实体类型提取失败")
                _emit_event(job_id, "error", {"step": 1, "message": job.error_message})
                return  # 不进入合并，等待用户续跑

        # ---- 4. 全部成功后合并去重 + 填充颜色 ----
        _set_job_progress(job_id, 1, 96, "正在合并实体类型...")
        all_entity_types = [et for batch in job.step1_batch_results for et in batch]
        all_et_relations = [etr for batch in job.step1_batch_relations_results for etr in batch]
        merged_types = _merge_entity_types(all_entity_types)
        batch_only_relations = _merge_entity_type_relations(all_et_relations)
        merged_et_relations = batch_only_relations

        # ---- 4.1 多批时补充跨批类型间关系（对标 step3 跨组关系补充）----
        # 长文档分批提取时，类型间关系只在本批内提取，跨批类型间的关系会整体丢失；
        # 这里在合并全量类型后额外调用一次 LLM 补齐跨批关系，避免 45 类型只有 21 关系的偏少现象。
        if total > 1 and not job.step1_cross_batch_done:
            _set_job_progress(job_id, 1, 98, "正在补充跨批类型间关系...")
            try:
                cross_messages = build_prompts.build_step1_cross_batch_messages(
                    merged_types, merged_et_relations, job.name
                )
                step1_cross_max_tokens, step1_cross_thinking = config.get_llm_params("step1")
                cross_result = await _llm_json_async(
                    cross_messages, temperature=0.3,
                    max_tokens=step1_cross_max_tokens, thinking_type=step1_cross_thinking
                )
                cross_relations = []
                if isinstance(cross_result, dict):
                    _cr = cross_result.get("entity_type_relations") or cross_result.get("relations") or []
                    if isinstance(_cr, list):
                        cross_relations = _cr
                async with build_lock:
                    job.step1_cross_batch_relations = cross_relations
                    job.step1_cross_batch_done = True
                    job.update_time = datetime.now()
                    save_build_job(job_id)
                logger.info(f"[{job_id}] Step1 跨批类型间关系补充: {len(cross_relations)} 条")
            except Exception as _e:
                logger.warning(f"[{job_id}] Step1 跨批类型间关系补充失败，降级为仅批内关系: {_e}")
                async with build_lock:
                    job.step1_cross_batch_done = True
                    job.step1_cross_batch_relations = []
                    job.update_time = datetime.now()
                    save_build_job(job_id)
        elif total <= 1:
            async with build_lock:
                job.step1_cross_batch_done = True
                job.step1_cross_batch_relations = []
                save_build_job(job_id)

        merged_et_relations = _merge_entity_type_relations(
            all_et_relations + job.step1_cross_batch_relations
        )
        cross_count = len(merged_et_relations) - len(batch_only_relations)

        # color 由后端按 entity_type 从本体模型推导（LLM 不输出 color，避免不一致）
        _enrich_types_with_color(merged_types, job.meta_entity_types)
        async with build_lock:
            job.step1_entity_types = merged_types
            job.step1_entity_type_relations = merged_et_relations
            job.step1_concepts = merged_types  # 兼容旧前端
            job.step = max(job.step, 1)
            job.running_step = -1
            job.progress = 100
            job.progress_message = (
                f"本体提取完成，共 {len(merged_types)} 个类型，"
                f"{len(merged_et_relations)} 条类型间关系"
                + (f"（{total} 批合并，含 {cross_count} 条跨批关系）" if total > 1 else "")
            )
            job.error_message = None
            job.update_time = datetime.now()
            save_build_job(job_id)
            save_build_jobs_index()
        _mark_stage_finished(job_id, 1)
        logger.info(
            f"[{job_id}] 后台本体提取完成: {len(merged_types)} 个类型，"
            f"{len(merged_et_relations)} 条类型间关系（{total} 批合并）"
        )
        # 联动聊天：翻任务标签为完成 + 推送「当前状态+下一步建议」回复
        # （必须在 step_done 之前：SSE 连接在终态事件后关闭，之后的 chat_message 会丢）
        await _finalize_task_chat(job_id, 1, True, job.progress_message)
        # 推送 Step1 完成事件，前端据此启用"确认实体类型清单"按钮
        _emit_event(job_id, "step_done", {
            "step": 1,
            "entity_types": merged_types,
            "entity_type_relations": merged_et_relations,
            "concepts": merged_types,  # 兼容旧前端
            "total": len(merged_types)
        })
    except Exception as e:
        logger.error(f"[{job_id}] 后台本体提取失败: {e}")
        _mark_stage_finished(job_id, 1, success=False)
        async with build_lock:
            # 并行模式下失败批次不明确，标记第一个未完成批次
            failed_idx = next(
                (i for i in range(job.step1_batches_total)
                 if i >= len(job.step1_batch_results) or not job.step1_batch_results[i]),
                job.step1_batches_done
            )
            job.running_step = -1
            job.progress = 0
            job.step1_failed_batch = failed_idx
            job.step1_failed_reason = str(e)[:500]
            job.error_message = f"本体提取异常: {str(e)[:500]}"
            job.progress_message = f"本体提取异常，可点击继续提取续跑"
            job.update_time = datetime.now()
            save_build_job(job_id)
        await _finalize_task_chat(job_id, 1, False, job.error_message or "实体类型提取异常")
        _emit_event(job_id, "error", {"step": 1, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


async def _background_extract_entities(job_id: str) -> None:
    """后台任务：Step 2 实体+关系提取（v3 实例层，LLM调用，支持长文档分批 + 断点续作）。

    v3 重构：合并原 step2 实体提取 + step3 关系建模。
    从文档提取具体实例（含属性赋值）+ 实例间关系（Relation），
    注入粒度预设（granularity）和阶段提示词（stage_hints[2]）。
    """
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        _mark_stage_started(job_id, 2)
        # v3：优先读 step1_entity_types，兼容旧任务 step1_concepts
        concepts = job.step1_entity_types or job.step1_concepts or []
        if not concepts:
            raise ValueError("实体类型清单为空，无法提取实体")

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
                while len(job.step2_batch_relations_results) < total:
                    job.step2_batch_relations_results.append([])
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
                while len(job.step2_batch_relations_results) < total:
                    job.step2_batch_relations_results.append([])
                save_build_job(job_id)

        total = job.step2_batches_total
        # 待处理批次：batch_results 为空的批次（兼容断点续作）
        pending_indices = [
            idx for idx in range(total)
            if idx >= len(job.step2_batch_results) or not job.step2_batch_results[idx]
        ]
        logger.info(
            f"[{job_id}] Step2 实体+关系提取：共 {total} 批，"
            f"{'续跑 ' + str(len(pending_indices)) + ' 批待处理' if is_resume else '首次全部 ' + str(len(pending_indices)) + ' 批'}"
            f"，并发 {config.LLM_CONCURRENCY}"
        )

        # ---- 3. 并行跑所有待处理批次 ----
        stage_hint_2 = job.stage_hints.get(2, "") if job.stage_hints else ""
        if pending_indices:
            sem = asyncio.Semaphore(config.LLM_CONCURRENCY)

            async def _run_entity_batch(idx: int):
                """单批实体+关系提取（并行任务单元）：调 LLM → 解析 v3 响应 → 持久化 → 推送 SSE。"""
                async with sem:
                    batch_text = batches[idx] if idx < len(batches) else ""
                    messages = build_prompts.build_step2_batch_messages(
                        batch_text, job.name, concepts, job.meta_entity_types,
                        batch_idx=idx, total_batches=total,
                        granularity=job.granularity, stage_hint=stage_hint_2,
                        template=job.ontology_model_snapshot, template_mode=job.ontology_model_mode
                    )
                    step2_max_tokens, step2_thinking = config.get_llm_params("step2")
                    raw_resp = await _llm_json_async(messages, temperature=0.3, max_tokens=step2_max_tokens, thinking_type=step2_thinking)
                    # v3：解析 LLM 响应（兼容 v2 数组和 v3 对象格式）
                    batch_entities, batch_relations = _parse_step2_llm_response(raw_resp)
                    if not isinstance(batch_entities, list):
                        raise ValueError(
                            f"第 {idx + 1}/{total} 批返回格式异常（entities 非数组），"
                            f"原始类型: {type(batch_entities).__name__}"
                        )
                    async with build_lock:
                        while len(job.step2_batch_results) <= idx:
                            job.step2_batch_results.append([])
                        while len(job.step2_batch_relations_results) <= idx:
                            job.step2_batch_relations_results.append([])
                        job.step2_batch_results[idx] = batch_entities
                        job.step2_batch_relations_results[idx] = batch_relations
                        job.step2_batches_done = sum(1 for r in job.step2_batch_results[:total] if r)
                        job.step2_failed_batch = -1
                        job.step2_failed_reason = None
                        job.update_time = datetime.now()
                        save_build_job(job_id)
                    done = job.step2_batches_done
                    logger.info(
                        f"[{job_id}] Step2 第 {idx + 1}/{total} 批完成: "
                        f"{len(batch_entities)} 个实体, {len(batch_relations)} 条关系（{done}/{total}）"
                    )
                    _set_job_progress(
                        job_id, 2,
                        10 + int(85 * done / max(total, 1)),
                        # 前端任务标签已显示「X/Y 批」批次进度，message 只补充剩余数
                        f"剩余 {total - done} 批处理中（并发 {config.LLM_CONCURRENCY}）..."
                        if total > 1 and done < total else "本批提取完成，正在汇总..."
                    )
                    _emit_event(job_id, "batch_done", {
                        "batch_idx": idx,
                        "batches_done": done,
                        "batches_total": total,
                        "entities": batch_entities,
                        "relations": batch_relations,
                    })
                    return idx

            _set_job_progress(
                job_id, 2, 10,
                f"正在并行提取实体+关系（{len(pending_indices)} 批，并发 {config.LLM_CONCURRENCY}）..."
                if total > 1 else "正在调用AI提取实体+关系..."
            )
            results = await asyncio.gather(
                *[_run_entity_batch(idx) for idx in pending_indices],
                return_exceptions=True
            )
            failures = [(pending_indices[i], r) for i, r in enumerate(results) if isinstance(r, Exception)]
            if failures:
                failed_idx, failed_exc = failures[0]
                succeeded = len(pending_indices) - len(failures)
                logger.error(
                    f"[{job_id}] Step2 并行提取 {len(failures)}/{len(pending_indices)} 批失败，"
                    f"首个失败: 第 {failed_idx + 1} 批: {failed_exc}"
                )
                async with build_lock:
                    job.running_step = -1
                    job.progress = 0
                    job.step2_failed_batch = failed_idx
                    job.step2_failed_reason = str(failed_exc)[:500]
                    job.error_message = f"第 {failed_idx + 1}/{total} 批失败: {str(failed_exc)[:500]}"
                    job.progress_message = (
                        f"第 {failed_idx + 1}/{total} 批失败，可点击继续提取续跑"
                        f"（其余 {succeeded} 批已成功）" if succeeded else f"第 {failed_idx + 1}/{total} 批失败，可点击继续提取续跑"
                    )
                    job.update_time = datetime.now()
                    save_build_job(job_id)
                await _finalize_task_chat(job_id, 2, False, job.error_message or "实体提取失败")
                _emit_event(job_id, "error", {"step": 2, "message": job.error_message})
                return  # 不进入合并

        # ---- 4. 全部成功后合并去重 ----
        _set_job_progress(job_id, 2, 96, "正在合并实体+关系...")
        all_entities = [e for batch in job.step2_batch_results for e in batch]
        all_relations = [r for batch in job.step2_batch_relations_results for r in batch]
        merged_entities = _merge_entities(all_entities)
        # v3：合并实例间关系（按 source/target/relation_type 去重）
        merged_relations = _deduplicate_relations(all_relations)
        async with build_lock:
            job.step2_entities = merged_entities
            job.step2_relations = merged_relations
            # 兼容旧字段：step3_relations（旧 step3 关系建模结果）
            job.step3_relations = merged_relations
            job.primary_entity_candidates = []  # 已弃用，恒为空
            job.step = max(job.step, 2)
            job.running_step = -1
            job.progress = 100
            job.progress_message = (
                f"实体+关系提取完成，共 {len(merged_entities)} 个实体，"
                f"{len(merged_relations)} 条关系"
                + (f"（{total} 批合并）" if total > 1 else "")
            )
            job.error_message = None
            job.update_time = datetime.now()
            save_build_job(job_id)
            save_build_jobs_index()
        _mark_stage_finished(job_id, 2)
        logger.info(
            f"[{job_id}] 后台实体+关系提取完成: {len(merged_entities)} 个实体，"
            f"{len(merged_relations)} 条关系（{total} 批合并）"
        )
        # 联动聊天：翻任务标签为完成 + 推送「当前状态+下一步建议」回复
        # （必须在 step_done 之前：SSE 连接在终态事件后关闭，之后的 chat_message 会丢）
        await _finalize_task_chat(job_id, 2, True, job.progress_message)
        _emit_event(job_id, "step_done", {
            "step": 2,
            "entities": merged_entities,
            "relations": merged_relations,
            "primary_entity_candidates": [],  # 已弃用，兼容旧前端
            "total": len(merged_entities)
        })
    except Exception as e:
        logger.error(f"[{job_id}] 后台实体+关系提取失败: {e}")
        _mark_stage_finished(job_id, 2, success=False)
        async with build_lock:
            # 并行模式下失败批次不明确，标记第一个未完成批次
            failed_idx = next(
                (i for i in range(job.step2_batches_total)
                 if i >= len(job.step2_batch_results) or not job.step2_batch_results[i]),
                job.step2_batches_done
            )
            job.running_step = -1
            job.progress = 0
            job.step2_failed_batch = failed_idx
            job.step2_failed_reason = str(e)[:500]
            job.error_message = f"实体+关系提取异常: {str(e)[:500]}"
            job.progress_message = f"实体+关系提取异常，可点击继续提取续跑"
            job.update_time = datetime.now()
            save_build_job(job_id)
        await _finalize_task_chat(job_id, 2, False, job.error_message or "实体提取异常")
        _emit_event(job_id, "error", {"step": 2, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


def _group_entities_by_type(entities: list, group_size: int) -> list:
    """按 instance_of 实体类型聚类后再按 group_size 切分，同类型实体尽量同组。

    同类型实体之间关系最密集，同组内能让 LLM 建立更完整的关系网。

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

    在已确认的实体间建立关系。实体过多时按 instance_of 实体类型分组，同组内关系完整后
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

        # ---- 2. 重建 groups（按 instance_of 实体类型分组）----
        if len(entities) <= config.STEP3_GROUP_THRESHOLD_ENTITIES:
            groups = [entities]
            total = 1
        else:
            groups = _group_entities_by_type(entities, config.STEP3_GROUP_SIZE)
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
                    # 前端任务标签已显示「X/Y 组」分组进度，message 只补充剩余数
                    f"剩余 {total - idx} 组待处理..." if total > 1 else "正在调用AI建立关系..."
                )
                group_entities = groups[idx] if idx < len(groups) else []
                messages = build_prompts.build_step3_group_messages(
                    group_entities, job.meta_relation_types,
                    group_idx=idx, total_groups=total, stage_hint=stage_hint_3,
                    template=job.ontology_model_snapshot, template_mode=job.ontology_model_mode
                )
                step3_group_max_tokens, step3_group_thinking = config.get_llm_params("step3_group")
                result = await _llm_json_async(messages, temperature=0.3, max_tokens=step3_group_max_tokens, thinking_type=step3_group_thinking)
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
                # 组完成即刷新批次进度（前端标签显示「X/Y 组」）
                _set_job_progress(
                    job_id, 3,
                    10 + int(70 * (idx + 1) / max(total, 1)),
                    f"剩余 {total - idx - 1} 组处理中..." if idx + 1 < total else "本组完成，正在合并关系..."
                )
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
                job.meta_relation_types, stage_hint=stage_hint_3,
                template=job.ontology_model_snapshot, template_mode=job.ontology_model_mode
            )
            try:
                step3_cross_max_tokens, step3_cross_thinking = config.get_llm_params("step3_cross")
                cross_result = await _llm_json_async(cross_messages, temperature=0.3, max_tokens=step3_cross_max_tokens, thinking_type=step3_cross_thinking)
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
        # 联动聊天：翻任务标签为完成 + 推送「当前状态+下一步建议」回复
        # （必须在 step_done 之前：SSE 连接在终态事件后关闭，之后的 chat_message 会丢）
        await _finalize_task_chat(job_id, 3, True, job.progress_message)
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
                job.step3_failed_reason = str(e)[:500]
                job.error_message = f"第 {failed_idx + 1}/{job.step3_groups_total} 组失败: {str(e)[:500]}"
                job.progress_message = f"第 {failed_idx + 1}/{job.step3_groups_total} 组失败，可点击继续从该组续跑"
            else:
                job.step3_cross_group_failed = True
                job.step3_cross_group_reason = str(e)[:500]
                job.error_message = f"跨组关系补充失败: {str(e)[:500]}"
                job.progress_message = "跨组关系补充失败，可点击继续重新补充跨组关系"
            job.update_time = datetime.now()
            save_build_job(job_id)
        await _finalize_task_chat(job_id, 3, False, job.error_message or "关系建模失败")
        _emit_event(job_id, "error", {"step": 3, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


async def _background_verify_and_report(job_id: str) -> None:
    """后台任务：Step 3 验证（v3 LLM 自检，已移除简报生成）。

    v3 重构：原 step4 验证 降为 step3。
    LLM 逐项检查实体/属性/关系是否可溯源，标记存疑项。
    验证结果存入 step3_verification（兼容旧 step4_verification）。
    本体生成在用户确认（build_confirm_step3）时触发，不在此任务内。
    """
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        _mark_stage_started(job_id, 3)
        # v3：优先读 step1_entity_types，兼容旧任务 step1_concepts
        concepts = job.step1_entity_types or job.step1_concepts or []
        entities = job.step2_entities or []
        # step3_relations 是关系建模的最终结果（step2 完成时两者相等，旧 step3 建模后更完整），优先读它
        relations = job.step3_relations or job.step2_relations or []
        if not entities:
            raise ValueError("实体清单为空，无法验证")

        _set_job_progress(job_id, 3, 20, "正在准备验证数据...")
        # 截断原文防止 prompt 过长
        doc_text = job.source_text[:config.VERIFICATION_MAX_DOC_CHARS]
        # v3：阶段提示词键改为 3，兼容旧任务键 4
        stage_hint = (job.stage_hints.get(3, "") or job.stage_hints.get(4, "")) if job.stage_hints else ""

        _set_job_progress(job_id, 3, 40, "正在调用AI做自检验证...")
        messages = build_prompts.build_step4_verification_messages(
            concepts, entities, relations, doc_text, stage_hint=stage_hint,
            template=job.ontology_model_snapshot, template_mode=job.ontology_model_mode
        )
        step4_max_tokens, step4_thinking = config.get_llm_params("step4")
        result = await _llm_json_async(messages, temperature=0.3, max_tokens=step4_max_tokens, thinking_type=step4_thinking)
        if not isinstance(result, dict):
            raise ValueError(f"验证返回格式异常（非对象），原始类型: {type(result).__name__}")

        # LLM 只负责输出存疑项列表；通过/存疑计数由后端计算，避免 LLM 自报计数
        # 出现「0 项通过、0 项存疑」等明显错误（LLM 统计几十上百个条目不可靠，
        # 且键名/结构稍有偏差 result.get 就会兜底成 0）。
        suspects = result.get("suspects")
        if not isinstance(suspects, list):
            suspects = []
        # 验证条目总数 = 实体类型 + 实体 + 全部属性 + 实例间关系（与 prompt 的 item_type 对齐）
        total_items = (
            len(concepts)
            + len(entities)
            + sum(len(e.get("properties") or []) for e in entities)
            + len(relations)
        )
        # 通过数 = 总数 - 存疑数；存疑列表仅覆盖部分漏检项时通过数偏大属保守可接受
        verified_count = max(total_items - len(suspects), 0)
        suspect_count = len(suspects)

        verification = {
            "verified_count": verified_count,
            "suspect_count": suspect_count,
            "suspects": suspects,
        }

        async with build_lock:
            # v3 字段
            job.step3_verification = verification
            # 兼容旧字段
            job.step4_verification = verification
            job.step = max(job.step, 3)
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
        _mark_stage_finished(job_id, 3)
        logger.info(
            f"[{job_id}] 后台验证完成: {verification['verified_count']} 通过, "
            f"{verification['suspect_count']} 存疑"
        )
        # 联动聊天：翻任务标签为完成 + 推送「当前状态+下一步建议」回复
        # （必须在 step_done 之前：SSE 连接在终态事件后关闭，之后的 chat_message 会丢）
        await _finalize_task_chat(job_id, 3, True, job.progress_message)
        _emit_event(job_id, "step_done", {
            "step": 3,
            "verification": verification
        })
    except Exception as e:
        logger.error(f"[{job_id}] 后台验证失败: {e}")
        _mark_stage_finished(job_id, 3, success=False)
        async with build_lock:
            job.running_step = -1
            job.progress = 0
            job.error_message = str(e)[:500]
            job.progress_message = f"验证失败: {str(e)[:150]}"
            job.update_time = datetime.now()
            save_build_job(job_id)
        await _finalize_task_chat(job_id, 3, False, job.error_message or "验证失败")
        _emit_event(job_id, "error", {"step": 3, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


def _generate_formal_ontology(job_id: str, target_ontology_id: str = None) -> str:
    """从已确认的 step1-3 数据生成正式本体（step3 确认时调用）。

    v3 四阶段数据 → 正式本体：
    - step1_entity_types → EntityType（含 parent_entity_type_id/property_schema/color）
    - step1_entity_type_relations → EntityTypeRelation（类型间关系）
    - step2_entities → Entity（instance_of = 类型名 → 类型ID）
    - step2_relations → Relation（source/target = 实体名 → 实体ID）
    - 兼容旧任务：step1_entity_types 为空时回退读 step1_concepts

    Args:
        job_id: 构建任务 ID
        target_ontology_id: 指定则覆盖更新该本体（再编辑场景），否则生成新本体

    Returns:
        生成/更新的本体 ID
    """
    job = build_jobs_db.get(job_id)
    if not job:
        raise ValueError("构建任务不存在")

    now = datetime.now()
    new_oid = target_ontology_id or f"ont_{uuid.uuid4().hex[:8]}"

    # ── step1_entity_types → EntityType（含层级解析）──
    # 两遍扫描：第一遍创建所有类型并建立 name→id 映射，第二遍解析 parent_entity_type_name → parent_entity_type_id
    # 兼容旧任务：优先读 step1_entity_types，为空则回退 step1_concepts（迁移脚本已拷贝，双保险）
    step1_data = job.step1_entity_types or job.step1_concepts or []
    type_map = {}  # type_name(normalized) -> type_id
    new_entity_types: List[EntityType] = []
    # 第一遍：创建 EntityType，parent_entity_type_id 暂留空
    for cd in step1_data:
        cname = cd.get("name", "")
        if not cname:
            continue
        cid = f"et_{uuid.uuid4().hex[:8]}"
        type_map[_normalize_name(cname)] = cid
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
        # v3：EntityType 不再有 entity_type 字段（自身 name 即类型名）
        # 颜色优先取 LLM 输出，否则按 entity_type 名（兼容旧数据）从本体模型推导
        et_name_for_color = cd.get("entity_type", "") or cd.get("name", "")
        color = cd.get("color") or _derive_type_color(et_name_for_color, job.meta_entity_types)
        new_entity_types.append(EntityType(
            id=cid, ontology_id=new_oid, name=cname,
            description=cd.get("description", ""),
            color=color,
            property_schema=ps_list,
            source_snippet=cd.get("source_snippet", ""),
            # parent_entity_type_id 在第二遍解析时填充
            parent_entity_type_id=None,
            # v3 字段：parent_entity_type_name（兼容旧数据 parent_concept_name）
            parent_entity_type_name=cd.get("parent_entity_type_name") or cd.get("parent_concept_name") or None,
            create_time=now, update_time=now,
        ))
    # 第二遍：解析 parent_entity_type_name → parent_entity_type_id
    for et in new_entity_types:
        if et.parent_entity_type_name:
            parent_id = type_map.get(_normalize_name(et.parent_entity_type_name))
            if parent_id and parent_id != et.id:  # 防自引用
                et.parent_entity_type_id = parent_id
            # 清除临时字段（不持久化 parent_entity_type_name）
            et.parent_entity_type_name = None

    # ── step1_entity_type_relations → EntityTypeRelation ──
    new_et_relations: List[EntityTypeRelation] = []
    for etr in (job.step1_entity_type_relations or []):
        src_name = etr.get("source_entity_type_name", "") or etr.get("source", "")
        tgt_name = etr.get("target_entity_type_name", "") or etr.get("target", "")
        src_id = type_map.get(_normalize_name(src_name))
        tgt_id = type_map.get(_normalize_name(tgt_name))
        if not src_id or not tgt_id:
            continue
        new_et_relations.append(EntityTypeRelation(
            id=f"etr_{uuid.uuid4().hex[:8]}",
            ontology_id=new_oid,
            source_entity_type_id=src_id,
            target_entity_type_id=tgt_id,
            relation_type=etr.get("relation_type", "关联"),
            description=etr.get("description", ""),
            source_snippet=etr.get("source_snippet", ""),
            weight=float(etr.get("weight", 1.0)),
            create_time=now, update_time=now,
        ))

    # ── 推导 relation_types（去重的类型名集合，供本体展示）──
    rt_names = set()
    for etr in new_et_relations:
        if etr.relation_type:
            rt_names.add(etr.relation_type)
    # 合并 step2 实例间关系类型名
    for rd in (job.step2_relations or []):
        rt_name = rd.get("relation_type", "")
        if rt_name:
            rt_names.add(rt_name)
    # 合并旧任务 meta_relation_types（兼容）
    for rt in (job.meta_relation_types or []):
        if rt.get("name"):
            rt_names.add(rt["name"])
    relation_types = [RelationType(name=n) for n in sorted(rt_names)]

    ont = OntologyModel(
        id=new_oid, name=job.name, description=job.description, version="1.0.0",
        entity_types=new_entity_types,       # v3：entity_types 即类型层（不再是本体模型粗分类）
        relation_types=relation_types,
        create_time=now, update_time=now, status="活跃",
        schema_version=SCHEMA_VERSION,
    )

    # ── step2_entities → Entity（instance_of = 类型名 → 类型ID）──
    ent_map = {}  # entity_name -> entity_id
    new_entities: List[Entity] = []
    for ed in (job.step2_entities or []):
        ename = ed.get("name", "")
        if not ename:
            continue
        new_eid = f"ent_{uuid.uuid4().hex[:8]}"
        ent_map[_normalize_name(ename)] = new_eid
        # instance_of: 类型名 → 类型ID
        inst_name = ed.get("instance_of", "")
        instance_of = type_map.get(_normalize_name(inst_name), "") if inst_name else ""
        props = _parse_properties(ed.get("properties", []), new_eid)
        new_entities.append(Entity(
            id=new_eid, ontology_id=new_oid, name=ename,
            instance_of=instance_of,
            is_primary=False,  # 已弃用，恒为 False
            properties=props,
            source_snippet=ed.get("source_snippet", ""),
            create_time=now, update_time=now,
        ))

    # ── step2_relations → Relation（实例间关系）──
    # step3_relations 是关系建模最终结果，优先读它；兼容仅 step2_relations 的旧任务
    step2_rel_data = job.step3_relations or job.step2_relations or []
    new_relations: List[Relation] = []
    for rd in step2_rel_data:
        src = ent_map.get(_normalize_name(rd.get("source", "") or rd.get("source_name", "")))
        tgt = ent_map.get(_normalize_name(rd.get("target", "") or rd.get("target_name", "")))
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
    entity_types_db[new_oid] = new_entity_types                  # 历史命名，存 EntityType
    entity_type_relations_db[new_oid] = new_et_relations     # v3 新增
    entities_db[new_oid] = new_entities
    relations_db[new_oid] = new_relations
    save_ontology(new_oid)
    save_index()

    # ── OWL 2 导出（v3：含 EntityType 层级 + 类型间关系）──
    # 可选步骤：导出失败仅记录警告，不阻塞本体生成
    # 文件路径：data/ontologies/ontology_{id}.owl（Protégé 可直接打开）
    if _owl_available and export_ontology_to_owl is not None:
        try:
            owl_path = export_ontology_to_owl(
                ont, new_entity_types, new_entities, new_relations,
                entity_type_relations=new_et_relations,
            )
            logger.info(f"[{job_id}] OWL 导出成功: {owl_path}")
        except Exception as owl_err:
            # OWL 导出失败不阻塞主流程，仅记录警告供排查
            logger.warning(f"[{job_id}] OWL 导出失败（不影响本体生成）: {owl_err}")

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
# entity_types_db: ontology_id -> List[EntityType]  （v3：变量名保留历史，实际存储 EntityType 实例）
# entity_type_relations_db: ontology_id -> List[EntityTypeRelation]  （v3 新增：类型间关系）
# entities_db: ontology_id -> List[Entity]
# relations_db: ontology_id -> List[Relation]
ontologies_db: Dict[str, OntologyModel] = {}
entity_types_db: Dict[str, List[EntityType]] = {}                       # 历史命名，存 EntityType
entity_type_relations_db: Dict[str, List[EntityTypeRelation]] = {}  # v3 新增
entities_db: Dict[str, List[Entity]] = {}
relations_db: Dict[str, List[Relation]] = {}

# 协程锁：保护内存全局变量，防 FastAPI 异步并发竞态
db_lock = __import__('asyncio').Lock()


def save_ontology(ontology_id: str) -> None:
    """持久化单个本体（元信息 + 实体类型 + 类型间关系 + 实体 + 关系）到独立文件。

    v3：存储字段名从 `concepts` 改为 `entity_types`，新增 `entity_type_relations`。
    旧 `concepts` 字段不再写入（读取时兼容）。
    同步策略：entity_types_db 是 EntityType 的单一数据源，保存前同步到 ont.entity_types。
    """
    ont = ontologies_db.get(ontology_id)
    if not ont:
        return
    # v3 同步：entity_types_db → ont.entity_types（保持单一数据源一致性）
    ont.entity_types = list(entity_types_db.get(ontology_id, []))
    ont.update_time = datetime.now()
    data = {
        'ontology': ont.dict(),
        'entity_types': [c.dict() for c in entity_types_db.get(ontology_id, [])],
        'entity_type_relations': [
            r.dict() for r in entity_type_relations_db.get(ontology_id, [])
        ],
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


# ---------- 本体模型持久化 ----------
# 本体模型：从已有本体抽取的 schema 层（本体模型 + 实体类型类 + 属性骨架），不含实例
# 复刻 ontologies_db 的双层存储模式（独立文件 + 索引 + .bak 备份 + 文件锁）
ONTOLOGY_MODELS_DIR = os.path.join(DATA_DIR, 'ontology_template_models')
ONTOLOGY_MODELS_INDEX = os.path.join(ONTOLOGY_MODELS_DIR, 'index.json')
os.makedirs(ONTOLOGY_MODELS_DIR, exist_ok=True)

# 内存字典：ontology_model_id -> OntologyTemplateModel
ontology_models_db: Dict[str, OntologyTemplateModel] = {}
# 协程锁：保护 ontology_models_db 并发写
ontology_models_lock = __import__('asyncio').Lock()


def _ontology_model_file(ontology_model_id: str) -> str:
    """本体模型数据文件路径。ontology_model_id 已含 tpl_ 前缀。"""
    return os.path.join(ONTOLOGY_MODELS_DIR, f'ontology_model_{ontology_model_id}.json')


def save_ontology_model(ontology_model_id: str) -> None:
    """持久化单个本体模型。"""
    tpl = ontology_models_db.get(ontology_model_id)
    if not tpl:
        return
    with FileLock(_lock_path(f'ontology_model_{ontology_model_id}')):
        atomic_write_json(_ontology_model_file(ontology_model_id), tpl.dict())


def save_ontology_models_index() -> None:
    """持久化本体模型列表索引。"""
    data = [t.dict() for t in ontology_models_db.values()]
    with FileLock(_lock_path('ontology_models_index')):
        atomic_write_json(ONTOLOGY_MODELS_INDEX, data)


def load_ontology_models() -> None:
    """启动时加载所有本体模型到内存（v3 兼容：旧 concepts 字段迁移到 entity_types）。"""
    global ontology_models_db
    ontology_models_db = {}
    index = load_json_with_backup(ONTOLOGY_MODELS_INDEX, [])
    if not isinstance(index, list):
        index = []
    for item in index:
        # v3 运行时迁移：旧本体模型有 concepts 字段而无 entity_types，迁移到 entity_types
        if "concepts" in item and not item.get("entity_types"):
            item["entity_types"] = item.pop("concepts")
        try:
            tpl = OntologyTemplateModel(**item)
            ontology_models_db[tpl.id] = tpl
        except Exception as e:
            logger.warning(f"本体模型解析失败，跳过: {e}")
    logger.info(f"加载完成: {len(ontology_models_db)} 个本体模型")


def _get_ontology_model_or_404(ontology_model_id: str) -> OntologyTemplateModel:
    """获取本体模型，不存在则抛 404。"""
    tpl = ontology_models_db.get(ontology_model_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="本体模型不存在")
    return tpl


def _ontology_model_summary(tpl: OntologyTemplateModel) -> Dict[str, Any]:
    """返回本体模型摘要（v3：含实体类型数和类型间关系数，不含完整 property_schema 以减小体积）。"""
    return {
        "id": tpl.id,
        "name": tpl.name,
        "description": tpl.description,
        "version": tpl.version,
        # v3：entity_types 即类型层（原 concepts 已合并），concepts_count 保留兼容旧前端
        "entity_types_count": len(tpl.entity_types),
        "relation_types_count": len(tpl.relation_types),
        "entity_type_relations_count": len(tpl.entity_type_relations),
        "concepts_count": len(tpl.entity_types),  # 兼容旧前端字段名
        "source_ontology_id": tpl.source_ontology_id,
        "is_builtin": tpl.is_builtin,
        "create_time": tpl.create_time,
        "update_time": tpl.update_time,
    }


def _extract_ontology_model_from_ontology(ontology_id: str, name: str, description: str) -> OntologyTemplateModel:
    """从已有本体抽取 schema 层生成本体模型（丢弃实例）。

    v3：
    - entity_types：从 entity_types_db（EntityType 列表）抽取为 TemplateEntityTypeSchema
      （含 parent_entity_type_name 层级 + property_schema）
    - entity_type_relations：从 entity_type_relations_db 抽取为 TemplateEntityTypeRelation
    - relation_types：直接复用本体 relation_types
    - entities/relations：完全丢弃
    """
    ont = _get_ontology_or_404(ontology_id)
    now = datetime.now()
    # 构建 id→name 映射，用于将 parent_entity_type_id 解析为 name
    et_id_to_name = {et.id: et.name for et in entity_types_db.get(ontology_id, [])}
    # EntityType → TemplateEntityTypeSchema
    tpl_entity_types = []
    for et in entity_types_db.get(ontology_id, []):
        parent_name = None
        if et.parent_entity_type_id:
            parent_name = et_id_to_name.get(et.parent_entity_type_id)
        tpl_entity_types.append(TemplateEntityTypeSchema(
            name=et.name,
            description=et.description,
            color=et.color,
            property_schema=list(et.property_schema),
            parent_entity_type_name=parent_name,
        ))
    # EntityTypeRelation → TemplateEntityTypeRelation
    tpl_et_relations = []
    for etr in entity_type_relations_db.get(ontology_id, []):
        src_name = et_id_to_name.get(etr.source_entity_type_id, "")
        tgt_name = et_id_to_name.get(etr.target_entity_type_id, "")
        if not src_name or not tgt_name:
            continue
        tpl_et_relations.append(TemplateEntityTypeRelation(
            source_entity_type_name=src_name,
            target_entity_type_name=tgt_name,
            relation_type=etr.relation_type,
            description=etr.description,
        ))
    return OntologyTemplateModel(
        id=f"tpl_{uuid.uuid4().hex[:8]}",
        name=name or f"{ont.name} 的本体模型",
        description=description or f"从本体「{ont.name}」抽取的 schema 本体模型",
        version="1.0.0",
        entity_types=tpl_entity_types,
        relation_types=list(ont.relation_types),
        entity_type_relations=tpl_et_relations,
        # 兼容旧代码读取 template.concepts：OntologyTemplateModel 已无 concepts 字段，
        # 但旧代码（如 build_prompts._template_hint_text）仍读 template.get("concepts")。
        # _ontology_model_summary 会处理这个兼容。
        source_ontology_id=ontology_id,
        create_time=now,
        update_time=now,
        is_builtin=False,
    )


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
    """持久化构建任务索引（轻量：仅元数据，全量数据存 job_{id}.json）。

    历史版本曾将每个 job 的全量 dict（含 source_text / chat_history / 分批结果）
    直接写入 index.json，导致 index.json 膨胀到数 MB，且此函数被高频调用
    （每次进度更新），全量序列化 + 大文件写盘会同步阻塞事件循环，
    进而拖垮同进程内所有请求（表现为 30s 超时）。改为只存元数据，
    全量数据由 save_build_job 单独落盘。
    """
    data = [
        {
            "id": j.id,
            "name": j.name,
            "status": j.status,
            "step": j.step,
            "build_type": j.build_type,
            "create_time": j.create_time.isoformat(),
            "update_time": j.update_time.isoformat(),
        }
        for j in build_jobs_db.values()
    ]
    with FileLock(_lock_path('build_jobs_index')):
        atomic_write_json(BUILD_JOBS_INDEX, data)


def load_build_jobs() -> None:
    """启动时加载所有构建任务到内存，并重试卡死的后台任务。

    索引仅存轻量元数据（见 save_build_jobs_index），全量数据从
    data/build_jobs/job_{id}.json 逐个加载；兼容旧版全量索引
    （job 文件缺失时回退用索引内嵌数据，不丢历史任务）。
    """
    global build_jobs_db
    build_jobs_db = {}
    index = load_json_with_backup(BUILD_JOBS_INDEX, [])
    if not isinstance(index, list):
        index = []
    for item in index:
        try:
            if not isinstance(item, dict):
                continue
            job_id = item.get("id")
            if not job_id:
                continue
            full = load_json_with_backup(_build_job_file(job_id), None)
            if isinstance(full, dict) and full.get("id"):
                job = BuildJob(**full)
            elif "running_step" in item:
                # 旧版全量索引兜底：job 文件丢失但索引仍内嵌全量数据
                job = BuildJob(**item)
            else:
                logger.warning(f"构建任务文件缺失且索引无全量数据，跳过: {job_id}")
                continue
            build_jobs_db[job.id] = job
        except Exception as e:
            logger.warning(f"构建任务解析失败，跳过: {e}")
    logger.info(f"加载完成: {len(build_jobs_db)} 个构建任务")
    # 加载后立即重写一次索引：将旧版 4.5MB 全量索引收敛为轻量元数据格式
    save_build_jobs_index()

    # 清理残留的 running 阶段状态：服务刚启动时不存在任何后台任务，
    # progress_stages 中 status=running 的条目必为上次运行中断的残留，
    # 不清理会导致前端时间线与标签对账永远认为该阶段在跑
    # （若该阶段随后被自动重试，_mark_stage_started 会重新置为 running）
    for job in build_jobs_db.values():
        stale = [s.get("stage") for s in job.progress_stages if s.get("status") == "running"]
        if not stale:
            continue
        for s in job.progress_stages:
            if s.get("status") == "running":
                s["status"] = "failed"
                s["finished_at"] = datetime.now().isoformat()
        job.update_time = datetime.now()
        save_build_job(job.id)
        logger.info(f"[{job.id}] 清理残留 running 阶段状态（服务重启中断）: 阶段 {stale}")

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


async def _parse_form_field(request: Request, field: str, default: str = "") -> str:
    """容错解析表单字段：空请求体或非法 multipart 时返回默认值。

    前端空 FormData 序列化出的请求体只有结束 boundary、没有任何 part，
    FastAPI 的 Form(...) 参数绑定会在解析阶段直接失败返回 400
    "There was an error parsing the body"。此函数手动解析并吞掉解析异常，
    保证空表单请求也能按"未填字段"正常处理。
    """
    try:
        form = await request.form()
        value = form.get(field)
        return str(value) if value is not None else default
    except Exception:
        # 请求体为空 / multipart 解析失败：按未填字段处理
        return default


def load_db() -> None:
    """启动时加载所有本体数据到内存。

    加载前检测 schema_version，若存在 v1 数据则自动迁移：
    1. 备份整个 data 目录（仅首次迁移时备份一次）
    2. 逐个本体调用 migrate_ontology_dict 迁移
    3. 迁移后回写文件
    4. 加载到内存
    """
    global ontologies_db, entity_types_db, entities_db, relations_db
    ontologies_db = {}
    entity_types_db = {}
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
                # v3 迁移补充：migrate_ontology_dict 只迁移到 v2（SCHEMA_VERSION=2），
                # 需要额外执行 v2→v3 迁移（concepts → entity_types + schema_version 更新）
                v3_meta = data.get('ontology', {}) if isinstance(data, dict) else {}
                v3_sv = v3_meta.get('schema_version', 1) if isinstance(v3_meta, dict) else 1
                if v3_sv < SCHEMA_VERSION:
                    # concepts 字段重命名为 entity_types（如果 entity_types 不存在）
                    if isinstance(data, dict) and 'entity_types' not in data and 'concepts' in data:
                        data['entity_types'] = data.pop('concepts')
                    # 新增 entity_type_relations 空数组（v3 字段，旧数据没有）
                    if isinstance(data, dict) and 'entity_type_relations' not in data:
                        data['entity_type_relations'] = []
                    # 更新 schema_version
                    if not isinstance(v3_meta, dict):
                        v3_meta = {}
                        data['ontology'] = v3_meta
                    v3_meta['schema_version'] = SCHEMA_VERSION
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

        # 加载实体类型（v3：优先读 entity_types 字段，回退到旧 concepts 字段）
        # ConceptType 已是 EntityType 别名，统一用 EntityType 解析
        types = []
        et_data_list = data.get('entity_types')
        if et_data_list is None:
            # 旧 v2 数据：从 concepts 字段读取（ConceptType dict）
            et_data_list = data.get('concepts', [])
        for c in et_data_list:
            try:
                types.append(EntityType(**c))
            except Exception as e2:
                logger.warning(f"实体类型解析失败，跳过: {e2}")
        entity_types_db[ont.id] = types

        # 加载实体类型间关系（v3 新增）
        et_rels = []
        for r in data.get('entity_type_relations', []):
            try:
                et_rels.append(EntityTypeRelation(**r))
            except Exception as e2:
                logger.warning(f"实体类型关系解析失败，跳过: {e2}")
        entity_type_relations_db[ont.id] = et_rels

        # v3 同步：entity_types_db 是 EntityType 单一数据源，同步到 ont.entity_types
        # 这确保手动创建的本体（ont.entity_types 有值但 entity_types_db 空）也能正确展示图谱
        if types:
            ont.entity_types = list(types)

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
                f"{sum(len(v) for v in entity_types_db.values())} 个实体类型, "
                f"{sum(len(v) for v in entity_type_relations_db.values())} 条类型关系, "
                f"{sum(len(v) for v in entities_db.values())} 个实体, "
                f"{sum(len(v) for v in relations_db.values())} 条关系")


def _count_entities(ontology_id: str) -> int:
    """统计某本体的实体数。"""
    return len(entities_db.get(ontology_id, []))


def _count_concepts(ontology_id: str) -> int:
    """统计某本体的实体类型数（v3：原概念数，变量名保留历史）。"""
    return len(entity_types_db.get(ontology_id, []))


def _count_entity_type_relations(ontology_id: str) -> int:
    """统计某本体的实体类型间关系数（v3 新增）。"""
    return len(entity_type_relations_db.get(ontology_id, []))


def _count_relations(ontology_id: str) -> int:
    """统计某本体的实例间关系数。"""
    return len(relations_db.get(ontology_id, []))


def _ontology_summary(ont: OntologyModel) -> Dict[str, Any]:
    """返回本体摘要（含实时计数）。"""
    d = ont.dict()
    # v3：concepts_count 字段名保留（前端兼容），实际为实体类型数
    d['concepts_count'] = _count_concepts(ont.id)
    d['entity_type_relations_count'] = _count_entity_type_relations(ont.id)
    d['entities_count'] = _count_entities(ont.id)
    d['relations_count'] = _count_relations(ont.id)
    return d


def _get_ontology_or_404(ontology_id: str) -> OntologyModel:
    """获取本体，不存在则抛 404。"""
    ont = ontologies_db.get(ontology_id)
    if not ont:
        raise HTTPException(status_code=404, detail="本体不存在")
    return ont


def _find_entity_type(ontology_id: str, concept_id: str) -> Optional[ConceptType]:
    """在本体内查找实体类型。"""
    for c in entity_types_db.get(ontology_id, []):
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
        concept = _find_entity_type(ontology_id, entity.instance_of)
        if concept:
            d["type"] = concept.entity_type or concept.name
        else:
            d["type"] = "未分类"
    return d


def _validate_instance_of(ontology_id: str, instance_of: str) -> None:
    """校验 instance_of 指向本体内存在的 ConceptType。

    迁移后的旧数据可能 instance_of 为空（防御性放行）；
    新建实体必须指向有效实体类型。
    """
    if not instance_of:
        return  # 空值放行（兼容旧数据）
    if _find_entity_type(ontology_id, instance_of):
        return
    raise HTTPException(
        status_code=400,
        detail=f"实体类型ID '{instance_of}' 在本体内不存在"
    )


def _validate_entity_type(ontology_id: str, entity_type: str) -> None:
    """校验实体类型在本体的本体模型定义内（向后兼容，保留给旧 API 使用）。

    新 API 应使用 instance_of 指向 ConceptType，此函数仅用于本体模型类型校验。
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
    """校验关系类型在本体的本体模型定义内。"""
    ont = ontologies_db.get(ontology_id)
    if not ont:
        return
    allowed = {t.name for t in ont.relation_types}
    if allowed and relation_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"关系类型 '{relation_type}' 不在本体允许类型内: {sorted(allowed)}"
        )


# 启动时加载数据
load_db()
load_build_jobs()
load_ontology_models()


@app.on_event("startup")
async def _retry_pending_build_jobs():
    """服务启动时重试卡死的构建任务（事件循环就绪后执行）。

    根据各阶段 confirmed 状态判断该重试哪一步：
    - step3 已确认 + step4 未完成 → 重试 step4（验证+报告）
    - step2 已确认 + step3 未完成 → 重试 step3（关系建模）
    - step1 已确认 + step2 未完成 → 重试 step2（实体提取）
    - meta 已确认 + step1 未完成 → 重试 step1（本体提取）
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
        if not job.meta_confirmed and not job.meta_entity_types:
            # 阶段 0「文档解析」无任何解析产出（meta 候选为空）即视为未完成：重试解析。
            # 不再看 source_text：重解析中途被中断时 source_text 已落盘但 meta 为空，
            # 旧条件会漏掉这种任务，导致阶段 0 永远无人重试、状态悬挂
            logger.info(f"[{job_id}] 自动重试阶段0（文档解析）")
            _set_job_progress(job_id, 0, 5, "服务重启后自动重试文档解析...")
            task = asyncio.create_task(_background_parse_document(job_id))
            _background_tasks[job_id] = task
        elif job.step3_confirmed and not job.step4_confirmed:
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
            logger.info(f"[{job_id}] 自动重试 step1（本体提取）")
            _set_job_progress(job_id, 1, 5, "服务重启后自动重试...")
            task = asyncio.create_task(_background_extract_entity_types(job_id))
            _background_tasks[job_id] = task
    _pending_retries.clear()


# ---------- 图谱与路径辅助 ----------
def _graph_data(ontology_id: str) -> Dict[str, Any]:
    """聚合某本体的图谱数据（nodes/links）。

    v3 包含：
    - 实体类型节点（node_type="concept"，历史命名保留以兼容前端）
    - 实体节点（node_type="entity"，带 concept_type/concept_id）
    - SUB_CONCEPT_OF 边（父实体类型→子实体类型，层级关系；名称保留兼容前端）
    - EntityTypeRelation 边（实体类型间关系，step1 提取）
    - instance_of 边（实体类型→实体实例）
    - Relation 边（实体实例间关系，step2 提取）

    重要：`type` 字段保持为类型名（v3 中即 EntityType.name），供前端按 entity_types
    颜色匹配（前端 OntologyDetail.vue 用 n.type 查 catIndex）。`node_type`
    字段区分类型节点与实体节点，供前端折叠/展开使用。
    """
    nodes = []
    links = []
    # 实体类型映射（et_id -> EntityType）；变量名 concept_map 保留历史
    concept_map = {c.id: c for c in entity_types_db.get(ontology_id, [])}

    # 实体类型节点（v3：原概念节点，node_type="concept" 保留兼容前端）
    for c in entity_types_db.get(ontology_id, []):
        nodes.append({
            "id": c.id,
            "name": c.name,
            # v3：entity_type 是 @property 返回 self.name，等价于 c.name
            "type": c.entity_type or c.name or "实体类型",   # 类型名，供前端颜色匹配
            "node_type": "concept",                        # 节点类型：类型/实体（历史命名）
            "entity_type": c.entity_type,
            "color": c.color,
            # v3 新增：父类型 ID，供前端构建层级树
            "parent_entity_type_id": c.parent_entity_type_id,
        })
        # 实体类型层级边：父→子（SUB_CONCEPT_OF 名称保留，前端已适配）
        if c.parent_entity_type_id:
            links.append({
                "source": c.parent_entity_type_id,
                "target": c.id,
                "relation": "SUB_CONCEPT_OF",
                "weight": 1.0,
            })

    # 实体类型间关系边（v3 新增：EntityTypeRelation，step1 提取的类型层关系）
    for etr in entity_type_relations_db.get(ontology_id, []):
        links.append({
            "source": etr.source_entity_type_id,
            "target": etr.target_entity_type_id,
            "relation": etr.relation_type,
            "weight": etr.weight,
        })

    # 实体节点
    for e in entities_db.get(ontology_id, []):
        concept = concept_map.get(e.instance_of)
        concept_name = concept.name if concept else ""
        # v3：concept.entity_type 是 @property 返回 concept.name，等价于 concept_name
        # 兼容旧数据：无 instance_of 时回退到 e.type
        type_name = concept.entity_type if concept else (e.type or "未分类")
        nodes.append({
            "id": e.id,
            "name": e.name,
            "type": type_name,                             # 类型名，供前端颜色匹配
            "node_type": "entity",                         # 节点类型：类型/实体
            "concept_type": concept_name,
            "concept_id": e.instance_of,
            "is_primary": e.is_primary,
        })
        # instance_of 边（实体类型→实体实例）
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
    # 实体类型ID→实体类型名映射，用于 summary 中展示实体类型
    concept_name_map = {c.id: c.name for c in entity_types_db.get(ontology_id, [])}

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
        "service": "本体服务",
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
    relation_types: str = Form(""),
    status: str = Form("活跃")
):
    """创建本体。

    Args:
        name: 本体名称
        description: 描述
        entity_types: 实体类型定义 JSON 字符串，如 [{"name":"实体类型","color":"#xxx"}]
        relation_types: 关系类型定义 JSON 字符串，如 [{"name":"包含"}]
    """
    et_list = _parse_json_arg(entity_types, None)
    rt_list = _parse_json_arg(relation_types, None)
    if et_list is None:
        # 实体类型不预填：创建本体后由用户逐个添加（手动构建空白启动）
        et_list = []
    if rt_list is None:
        rt_list = DEFAULT_RELATION_TYPES

    now = datetime.now()
    # v3：entity_types 参数即类型层（EntityType 列表），不再有独立本体模型层
    # 前端传 [{name, color, description, property_schema, parent_entity_type_name, ...}]
    new_entity_types = []
    for t in et_list:
        try:
            new_entity_types.append(EntityType(
                id=f"et_{uuid.uuid4().hex[:8]}",
                name=t.get("name", ""),
                description=t.get("description", ""),
                color=t.get("color"),
                property_schema=[PropertySchema(**p) for p in t.get("property_schema", [])],
                parent_entity_type_name=t.get("parent_entity_type_name"),
                create_time=now,
                update_time=now,
            ))
        except Exception as e:
            logger.warning(f"实体类型解析失败，跳过: {e}")

    # 第二遍：解析 parent_entity_type_name → parent_entity_type_id
    name_to_id = {et.name: et.id for et in new_entity_types}
    for et in new_entity_types:
        if et.parent_entity_type_name:
            parent_id = name_to_id.get(et.parent_entity_type_name)
            if parent_id and parent_id != et.id:
                et.parent_entity_type_id = parent_id
            et.parent_entity_type_name = None

    ontology = OntologyModel(
        id=f"ont_{uuid.uuid4().hex[:8]}",
        name=name,
        description=description,
        version="1.0.0",
        entity_types=new_entity_types,
        relation_types=[RelationType(**t) for t in rt_list],
        create_time=now,
        update_time=now,
        status=status,
        schema_version=SCHEMA_VERSION,
    )

    async with db_lock:
        ontologies_db[ontology.id] = ontology
        # v3：entity_types_db 是 EntityType 单一数据源，手动创建时也要初始化
        entity_types_db[ontology.id] = list(new_entity_types)
        entity_type_relations_db[ontology.id] = []
        entities_db[ontology.id] = []
        relations_db[ontology.id] = []
        save_ontology(ontology.id)
        save_index()

    return {
        "success": True,
        "message": "本体创建成功",
        "data": _ontology_summary(ontology)
    }


@app.get("/ontology/list")
async def list_ontologies():
    """列出所有本体。"""
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
        # 实体类型ID→实体类型名映射，用于按实体类型名统计
        concept_name_map = {c.id: c.name for c in entity_types_db.get(oid, [])}
        for e in ents:
            type_name = concept_name_map.get(e.instance_of, e.type or "未分类")
            entity_types[type_name] += 1
    for oid, rels in relations_db.items():
        total_relations += len(rels)
        for r in rels:
            relation_types[r.relation_type] += 1
    total_concepts = sum(len(v) for v in entity_types_db.values())
    return {
        "success": True,
        "data": {
            "total_entities": total_entities,
            "total_relations": total_relations,
            "total_concepts": total_concepts,
            "total_ontologies": len(ontologies_db),
            "total_ontology_models": len(ontology_models_db),
            "entity_types": dict(entity_types),
            "relation_types": dict(relation_types),
            "avg_relations_per_entity": total_relations / total_entities if total_entities else 0
        }
    }


# ---------- 本体模型 CRUD ----------
# 路由顺序：所有 /ontology/ontology-model/* 静态路由必须声明在 /ontology/{ontology_id} 之前，
# 否则 "ontology-model" 会被捕获为 ontology_id 路径参数。
# 子顺序：/ontology/ontology-model/list 必须在 /ontology/ontology-model/{ontology_model_id} 之前，
# 否则 "list" 会被捕获为 ontology_model_id。


@app.get("/ontology/ontology-model/list")
async def list_ontology_models():
    """列出所有本体模型（summary）。"""
    items = [_ontology_model_summary(t) for t in ontology_models_db.values()]
    items.sort(key=lambda x: x["update_time"], reverse=True)
    return {
        "success": True,
        "total": len(items),
        "items": items,
    }


@app.post("/ontology/ontology-model")
async def create_ontology_model(
    name: str = Form(...),
    description: str = Form(""),
    entity_types: str = Form(""),
    relation_types: str = Form(""),
    concepts: str = Form(""),
    entity_type_relations: str = Form("")
):
    """手动向导独立创建本体模型（v3）。

    Args:
        name: 本体模型名称
        description: 描述
        entity_types: v3 实体类型 schema JSON，如 [{"name":"企业","color":"#xxx",
                      "property_schema":[...], "parent_entity_type_name":"..."}]
        relation_types: 关系类型 JSON 字符串，如 [{"name":"包含"}]
        concepts: v2 兼容字段，等同 entity_types（旧前端仍传此参数）
        entity_type_relations: v3 实体类型间关系 JSON，如 [{"source_entity_type_name":"企业",
                               "target_entity_type_name":"财务指标","relation_type":"关联"}]
    """
    # v3：entity_types 和 concepts 都是类型层 schema，合并去重（按 name）
    et_list = _parse_json_arg(entity_types, []) or []
    cs_list = _parse_json_arg(concepts, []) or []
    rt_list = _parse_json_arg(relation_types, []) or []
    etr_list = _parse_json_arg(entity_type_relations, []) or []

    # 合并 et_list + cs_list（兼容旧前端传 concepts 参数）
    seen_names = set()
    merged_et = []
    for c in (et_list + cs_list):
        n = c.get("name", "")
        if n and n not in seen_names:
            seen_names.add(n)
            merged_et.append(c)

    now = datetime.now()
    tpl_entity_types = []
    for c in merged_et:
        ps = [PropertySchema(**p) for p in c.get("property_schema", [])]
        tpl_entity_types.append(TemplateEntityTypeSchema(
            name=c.get("name", ""),
            description=c.get("description", ""),
            color=c.get("color"),
            property_schema=ps,
            parent_entity_type_name=c.get("parent_entity_type_name"),
        ))
    tpl_et_relations = []
    for etr in etr_list:
        tpl_et_relations.append(TemplateEntityTypeRelation(
            source_entity_type_name=etr.get("source_entity_type_name", ""),
            target_entity_type_name=etr.get("target_entity_type_name", ""),
            relation_type=etr.get("relation_type", "关联"),
            description=etr.get("description", ""),
        ))

    template = OntologyTemplateModel(
        id=f"tpl_{uuid.uuid4().hex[:8]}",
        name=name,
        description=description,
        version="1.0.0",
        entity_types=tpl_entity_types,
        relation_types=[RelationType(**t) for t in rt_list],
        entity_type_relations=tpl_et_relations,
        source_ontology_id=None,
        create_time=now,
        update_time=now,
        is_builtin=False,
    )

    async with ontology_models_lock:
        ontology_models_db[template.id] = template
        save_ontology_model(template.id)
        save_ontology_models_index()

    return {
        "success": True,
        "message": "本体模型创建成功",
        "data": _ontology_model_summary(template),
    }


@app.post("/ontology/ontology-model/save-from-ontology/{ontology_id}")
async def save_ontology_model_from_ontology(
    ontology_id: str,
    name: str = Form(""),
    description: str = Form("")
):
    """从已有本体另存为本体模型（抽取 schema 层，丢弃实例）。"""
    template = _extract_ontology_model_from_ontology(ontology_id, name, description)
    async with ontology_models_lock:
        ontology_models_db[template.id] = template
        save_ontology_model(template.id)
        save_ontology_models_index()
    return {
        "success": True,
        "message": "本体模型创建成功",
        "data": _ontology_model_summary(template),
    }


@app.get("/ontology/ontology-model/{ontology_model_id}")
async def get_ontology_model(ontology_model_id: str):
    """本体模型详情（含完整 concepts 与 property_schema）。"""
    tpl = _get_ontology_model_or_404(ontology_model_id)
    return {"success": True, "data": tpl.dict()}


@app.put("/ontology/ontology-model/{ontology_model_id}")
async def update_ontology_model(
    ontology_model_id: str,
    name: str = Form(""),
    description: str = Form(""),
    entity_types: str = Form(""),
    relation_types: str = Form(""),
    concepts: str = Form(""),
    entity_type_relations: str = Form("")
):
    """更新本体模型字段（传空字符串的字段保持原值，v3）。"""
    tpl = _get_ontology_model_or_404(ontology_model_id)
    if name:
        tpl.name = name
    if description:
        tpl.description = description
    # v3：entity_types 和 concepts 合并作为类型层 schema
    et_list = _parse_json_arg(entity_types, None)
    cs_list = _parse_json_arg(concepts, None)
    # 任一非空则更新（None 表示未传，保持原值）
    if et_list is not None or cs_list is not None:
        merged = (et_list or []) + (cs_list or [])
        seen_names = set()
        tpl.entity_types = []
        for c in merged:
            n = c.get("name", "")
            if n and n not in seen_names:
                seen_names.add(n)
                ps = [PropertySchema(**p) for p in c.get("property_schema", [])]
                tpl.entity_types.append(TemplateEntityTypeSchema(
                    name=n,
                    description=c.get("description", ""),
                    color=c.get("color"),
                    property_schema=ps,
                    parent_entity_type_name=c.get("parent_entity_type_name"),
                ))
    rt_list = _parse_json_arg(relation_types, None)
    if rt_list is not None:
        tpl.relation_types = [RelationType(**t) for t in rt_list]
    etr_list = _parse_json_arg(entity_type_relations, None)
    if etr_list is not None:
        tpl.entity_type_relations = []
        for etr in etr_list:
            tpl.entity_type_relations.append(TemplateEntityTypeRelation(
                source_entity_type_name=etr.get("source_entity_type_name", ""),
                target_entity_type_name=etr.get("target_entity_type_name", ""),
                relation_type=etr.get("relation_type", "关联"),
                description=etr.get("description", ""),
            ))
    tpl.update_time = datetime.now()

    async with ontology_models_lock:
        ontology_models_db[tpl.id] = tpl
        save_ontology_model(tpl.id)
        save_ontology_models_index()

    return {
        "success": True,
        "message": "本体模型更新成功",
        "data": _ontology_model_summary(tpl),
    }


@app.delete("/ontology/ontology-model/{ontology_model_id}")
async def delete_ontology_model(ontology_model_id: str):
    """删除本体模型（不影响已基于该本体模型创建的本体/任务）。"""
    _get_ontology_model_or_404(ontology_model_id)
    async with ontology_models_lock:
        ontology_models_db.pop(ontology_model_id, None)
        save_ontology_models_index()
        # 删除独立文件（含 .bak）
        for suffix in ('', '.bak'):
            p = _ontology_model_file(ontology_model_id) + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception as e:
                    logger.warning(f"删除本体模型文件失败 {p}: {e}")
    return {"success": True, "message": "本体模型已删除"}


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
    """更新本体元信息与本体模型类型定义。"""
    async with db_lock:
        ont = _get_ontology_or_404(ontology_id)
        ont.name = name
        ont.description = description
        ont.update_time = datetime.now()
        et_list = _parse_json_arg(entity_types, None)
        rt_list = _parse_json_arg(relation_types, None)
        if et_list is not None:
            ont.entity_types = [_entity_type_from_dict(t, ontology_id) for t in et_list]
        if rt_list is not None:
            ont.relation_types = [RelationType(**t) for t in rt_list]
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "本体更新成功"}


@app.delete("/ontology/{ontology_id}")
async def delete_ontology(ontology_id: str):
    """删除本体及其下属的所有实体类型/实体/关系（仅删该本体，不影响其他本体）。"""
    async with db_lock:
        if ontology_id not in ontologies_db:
            raise HTTPException(status_code=404, detail="本体不存在")
        ontologies_db.pop(ontology_id)
        entity_types_db.pop(ontology_id, None)
        entity_type_relations_db.pop(ontology_id, None)   # v3：清理类型间关系
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

    return {"success": True, "message": "本体删除成功"}


@app.get("/ontology/{ontology_id}/meta")
async def get_ontology_meta(ontology_id: str):
    """获取本体的类型定义（实体类型/关系类型/类型间关系），供前端表单下拉使用。

    v3：返回 entity_type_relations 供手动构建页展示类型层关系。
    """
    ont = _get_ontology_or_404(ontology_id)
    return {
        "success": True,
        "data": {
            "entity_types": [t.dict() for t in ont.entity_types],
            "relation_types": [t.dict() for t in ont.relation_types],
            "entity_type_relations": [
                r.dict() for r in entity_type_relations_db.get(ontology_id, [])
            ],
        }
    }


# ---------- 实体 CRUD ----------
@app.post("/ontology/{ontology_id}/entity")
async def add_entity(
    ontology_id: str,
    name: str = Form(...),
    instance_of: str = Form(""),
    entity_type: str = Form(""),       # 兼容旧前端：传类型名时自动查找/创建实体类型
    properties: str = Form("{}"),
    is_primary: bool = Form(False),
    source_snippet: str = Form("")
):
    """向指定本体添加实体。

    新接口用 instance_of 指向实体类型ID；为兼容旧前端，也可传 entity_type（类型名），
    系统会按类型名查找现有实体类型，找不到则自动创建一个。
    properties 兼容 Dict（旧）和 List（新）两种格式。
    """
    _get_ontology_or_404(ontology_id)

    # 兼容：若 instance_of 为空但 entity_type 有值，按类型名查找/创建实体类型
    if not instance_of and entity_type:
        concept = next((c for c in entity_types_db.get(ontology_id, []) if c.name == entity_type), None)
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
            entity_types_db.setdefault(ontology_id, []).append(concept)
            instance_of = concept.id
    elif not instance_of and not entity_type:
        raise HTTPException(status_code=400, detail="必须提供 instance_of（实体类型ID）或 entity_type（类型名）")

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
    entity_type: Optional[str] = None,      # 按实体类型名筛选（兼容旧前端）
    instance_of: Optional[str] = None,      # 按实体类型ID筛选（新接口）
    is_primary: Optional[bool] = None,      # 按主要实体筛选
    page: int = 1,
    page_size: int = 20
):
    """列出某本体的实体（支持按实体类型/主要实体过滤与分页）。"""
    _get_ontology_or_404(ontology_id)
    filtered = entities_db.get(ontology_id, [])

    # 按实体类型ID筛选
    if instance_of:
        filtered = [e for e in filtered if e.instance_of == instance_of]
    # 按实体类型名筛选（兼容旧前端 entity_type 参数）
    if entity_type:
        concept_ids = {c.id for c in entity_types_db.get(ontology_id, []) if c.name == entity_type}
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
        concept = next((c for c in entity_types_db.get(ontology_id, []) if c.name == entity_type), None)
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
            entity_types_db.setdefault(ontology_id, []).append(concept)
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


# ---------- 实体类型 CRUD ----------
@app.get("/ontology/{ontology_id}/concept/list")
async def list_entity_types(
    ontology_id: str,
    entity_type: Optional[str] = None
):
    """列出某本体的所有实体类型（类型定义），支持按本体 entity_type 筛选。"""
    _get_ontology_or_404(ontology_id)
    types = entity_types_db.get(ontology_id, [])
    if entity_type:
        types = [c for c in types if c.entity_type == entity_type]
    return {"success": True, "total": len(types), "items": [c.dict() for c in types]}


@app.post("/ontology/{ontology_id}/concept")
async def add_entity_type(
    ontology_id: str,
    name: str = Form(...),
    entity_type: str = Form(""),                   # v2 兼容（本体类型名），v3 中 EntityType 自身即类型
    description: str = Form(""),
    color: str = Form(""),
    property_schema: str = Form("[]"),             # JSON 数组
    source_snippet: str = Form(""),
    parent_entity_type_id: str = Form(""),          # v3：父实体类型ID（层级关系）
    parent_entity_type_name: str = Form("")         # v3：父类型名（前端按名引用，后端解析为ID）
):
    """新增实体类型（v3：原概念，自带层级 + 属性骨架）。

    v3 重构：ConceptType = EntityType 别名，EntityType 自带 parent_entity_type_id
    形成树状层级。property_schema 为 PropertySchema 列表 JSON，定义属性骨架。
    子类型自动继承父类型 property_schema（运行时 get_inherited_property_schema 计算）。
    """
    ont = _get_ontology_or_404(ontology_id)

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

    # v3：父类型名 → 父类型ID 解析（前端传名时自动查找）
    resolved_parent_id = parent_entity_type_id or ""
    if not resolved_parent_id and parent_entity_type_name:
        for c in entity_types_db.get(ontology_id, []):
            if c.name == parent_entity_type_name:
                resolved_parent_id = c.id
                break

    # 防自环：父类型ID不能等于自身（创建时自身ID还未生成，仅校验非空且不等于未来ID前缀）
    # 若 color 为空，从父类型继承或用默认色
    if not color:
        if resolved_parent_id:
            parent_c = _find_entity_type(ontology_id, resolved_parent_id)
            if parent_c and parent_c.color:
                color = parent_c.color
            else:
                color = "#5470c6"
        else:
            color = "#5470c6"

    now = datetime.now()
    concept = ConceptType(   # ConceptType = EntityType 别名
        id=f"concept_{uuid.uuid4().hex[:8]}",
        ontology_id=ontology_id,
        name=name,
        description=description,
        color=color,
        property_schema=pschema,
        source_snippet=source_snippet,
        parent_entity_type_id=resolved_parent_id or None,
        parent_entity_type_name=parent_entity_type_name or None,
        create_time=now,
        update_time=now,
    )

    async with db_lock:
        entity_types_db.setdefault(ontology_id, []).append(concept)
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "实体类型添加成功", "data": concept.dict()}


@app.get("/ontology/{ontology_id}/concept/{concept_id}")
async def get_concept(ontology_id: str, concept_id: str):
    """获取某个实体类型。"""
    _get_ontology_or_404(ontology_id)
    concept = _find_entity_type(ontology_id, concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    return {"success": True, "data": concept.dict()}


@app.put("/ontology/{ontology_id}/concept/{concept_id}")
async def update_entity_type(
    ontology_id: str,
    concept_id: str,
    name: str = Form(None),
    entity_type: str = Form(None),                  # v2 兼容字段，v3 中忽略（EntityType 自身即类型）
    description: str = Form(None),
    color: str = Form(None),
    property_schema: str = Form(None),
    parent_entity_type_id: str = Form(None),         # v3：父实体类型ID（传空串清除层级）
    parent_entity_type_name: str = Form(None)        # v3：父类型名（优先级低于ID）
):
    """更新实体类型（仅更新非 None 字段）。

    v3 新增：parent_entity_type_id / parent_entity_type_name 支持层级调整。
    传空串 "" 表示清除父层级（变为顶层类型）；None 表示不修改。
    防自环：parent_entity_type_id 不能等于自身 concept_id。
    """
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        concept = _find_entity_type(ontology_id, concept_id)
        if not concept:
            raise HTTPException(status_code=404, detail="实体类型不存在")
        if name is not None:
            concept.name = name
        # v3：entity_type 是 @property（只读），不可设置；v2 兼容忽略
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

        # v3：层级字段更新
        if parent_entity_type_id is not None:
            resolved = parent_entity_type_id
            # 父类型名 → ID 解析（当 ID 为空但传了名时）
            if not resolved and parent_entity_type_name:
                for c in entity_types_db.get(ontology_id, []):
                    if c.name == parent_entity_type_name and c.id != concept_id:
                        resolved = c.id
                        break
            # 防自环
            if resolved and resolved == concept_id:
                raise HTTPException(status_code=400, detail="父实体类型不能是自身")
            concept.parent_entity_type_id = resolved or None
        if parent_entity_type_name is not None:
            concept.parent_entity_type_name = parent_entity_type_name or None

        concept.update_time = datetime.now()
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "实体类型更新成功", "data": concept.dict()}


@app.delete("/ontology/{ontology_id}/concept/{concept_id}")
async def delete_entity_type(ontology_id: str, concept_id: str):
    """删除实体类型。

    若有实体 instance_of 指向该实体类型，拒绝删除（提示先迁移实体）。
    """
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        concept = _find_entity_type(ontology_id, concept_id)
        if not concept:
            raise HTTPException(status_code=404, detail="实体类型不存在")
        # 检查是否有实体引用
        refs = [e for e in entities_db.get(ontology_id, []) if e.instance_of == concept_id]
        if refs:
            raise HTTPException(
                status_code=400,
                detail=f"有 {len(refs)} 个实体引用此实体类型，请先迁移或删除这些实体"
            )
        entity_types_db[ontology_id] = [c for c in entity_types_db.get(ontology_id, []) if c.id != concept_id]
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "实体类型删除成功"}


# ---------- 实体类型间关系 CRUD（v3 新增）----------
@app.get("/ontology/{ontology_id}/entity_type_relation/list")
async def list_entity_type_relations(ontology_id: str):
    """列出本体的所有实体类型间关系（类型层关系，step1 提取或手动添加）。"""
    _get_ontology_or_404(ontology_id)
    rels = entity_type_relations_db.get(ontology_id, [])
    return {"success": True, "total": len(rels), "items": [r.dict() for r in rels]}


@app.post("/ontology/{ontology_id}/entity_type_relation")
async def add_entity_type_relation(
    ontology_id: str,
    source_entity_type_id: str = Form(...),
    target_entity_type_id: str = Form(...),
    relation_type: str = Form(...),
    description: str = Form(""),
    source_snippet: str = Form(""),
    weight: float = Form(1.0)
):
    """新增实体类型间关系（类型层关系）。

    描述两个实体类型之间的语义关联（如「企业」关联「财务指标」），
    为图谱类型层展示和实例层关系建模提供参考。
    """
    _get_ontology_or_404(ontology_id)
    # 校验源/目标类型存在
    src = _find_entity_type(ontology_id, source_entity_type_id)
    tgt = _find_entity_type(ontology_id, target_entity_type_id)
    if not src:
        raise HTTPException(status_code=400, detail="源实体类型不存在")
    if not tgt:
        raise HTTPException(status_code=400, detail="目标实体类型不存在")
    if source_entity_type_id == target_entity_type_id:
        raise HTTPException(status_code=400, detail="源和目标实体类型不能相同")

    now = datetime.now()
    etr = EntityTypeRelation(
        id=f"etr_{uuid.uuid4().hex[:8]}",
        ontology_id=ontology_id,
        source_entity_type_id=source_entity_type_id,
        target_entity_type_id=target_entity_type_id,
        relation_type=relation_type,
        description=description,
        source_snippet=source_snippet,
        weight=weight,
        create_time=now,
        update_time=now,
    )
    async with db_lock:
        entity_type_relations_db.setdefault(ontology_id, []).append(etr)
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "类型间关系添加成功", "data": etr.dict()}


@app.delete("/ontology/{ontology_id}/entity_type_relation/{relation_id}")
async def delete_entity_type_relation(ontology_id: str, relation_id: str):
    """删除实体类型间关系。"""
    _get_ontology_or_404(ontology_id)
    async with db_lock:
        lst = entity_type_relations_db.get(ontology_id, [])
        new_lst = [r for r in lst if r.id != relation_id]
        if len(new_lst) == len(lst):
            raise HTTPException(status_code=404, detail="类型间关系不存在")
        entity_type_relations_db[ontology_id] = new_lst
        ontologies_db[ontology_id].update_time = datetime.now()
        save_ontology(ontology_id)
        save_index()

    return {"success": True, "message": "类型间关系删除成功"}


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


@app.post("/ontology/{ontology_id}/archive")
async def archive_ontology(ontology_id: str):
    """将指定本体归档（status 置为「归档」）。

    归档即标记为「参与下游数据联动」：归档本体会在 /ontology/archived/context
    中被合并返回给 qa/indicator 服务做 B 阶段数据联动。同一时刻允许多个本体归档。
    归档仅改变状态标记，不影响实体/关系数据；前端列表可通过「归档」筛选查看。
    """
    async with db_lock:
        ont = _get_ontology_or_404(ontology_id)
        ont.status = "归档"
        ont.update_time = datetime.now()
        save_index()
        save_ontology(ontology_id)

    return {"success": True, "message": f"已将「{ont.name}」归档，参与下游数据联动"}


@app.post("/ontology/{ontology_id}/unarchive")
async def unarchive_ontology(ontology_id: str):
    """将指定本体恢复为「活跃」（取消归档）。

    恢复后该本体不再参与下游数据联动。
    """
    async with db_lock:
        ont = _get_ontology_or_404(ontology_id)
        ont.status = "活跃"
        ont.update_time = datetime.now()
        save_index()
        save_ontology(ontology_id)

    return {"success": True, "message": f"已将「{ont.name}」恢复为活跃"}


@app.get("/ontology/{ontology_id}/bindings")
async def get_bindings(ontology_id: str):
    """返回该本体所有绑定的紧凑结构（仅含已绑定的实体/关系）。

    供前端 badge 展示与 B2 prompt 注入消费。
    """
    _get_ontology_or_404(ontology_id)
    _concept_name_map = {c.id: c.name for c in entity_types_db.get(ontology_id, [])}
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
@app.get("/ontology/archived/context")
async def get_archived_context(question: str = "", top_k: int = 20):
    """归档本体的合并上下文快捷接口（三服务最常用）。

    仅归档本体参与下游数据联动；未指定具体本体时，合并所有归档本体的上下文
    一次性返回（summary_text 拼接、entities/relations 聚合）。
    若无归档本体，返回空结构（消费方据此降级）。

    注意：此静态路由必须声明在 /ontology/{ontology_id}/context 之前，
    否则 "archived" 会被捕获为路径参数。
    """
    archived = [o for o in ontologies_db.values() if o.status == "归档"]
    if not archived:
        return {
            "success": True,
            "data": {"summary_text": "", "entities": [], "relations": [], "ontology": None},
        }
    # 合并各归档本体的上下文
    all_summary = []
    all_entities = []
    all_relations = []
    ontologies_meta = []
    for o in archived:
        ctx = _build_ontology_context(o.id, question, top_k)
        if ctx.get("summary_text"):
            all_summary.append(ctx["summary_text"])
        all_entities.extend(ctx.get("entities", []))
        all_relations.extend(ctx.get("relations", []))
        if ctx.get("ontology"):
            ontologies_meta.append(ctx["ontology"])
    return {
        "success": True,
        "data": {
            "summary_text": "\n\n".join(all_summary),
            "entities": all_entities,
            "relations": all_relations,
            "ontology": {"ontologies": ontologies_meta, "count": len(archived)},
        },
    }


@app.get("/ontology/{ontology_id}/context")
async def get_ontology_context(
    ontology_id: str,
    question: str = "",
    top_k: int = 20
):
    """指定本体的上下文接口（请求携带 ontology_id 时使用）。

    仅归档本体参与下游数据联动，未归档本体返回空结构（消费方据此降级）。
    """
    ont = _get_ontology_or_404(ontology_id)
    if ont.status != "归档":
        return {
            "success": True,
            "data": {"summary_text": "", "entities": [], "relations": [], "ontology": None},
        }
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
        et_list = data.get("entity_types") or []
        rt_list = data.get("relation_types") or DEFAULT_RELATION_TYPES
        name_val = data.get("name", "导入本体")
        desc_val = data.get("description", "")
        ver_val = data.get("version", "1.0.0")

    ont = OntologyModel(
        id=new_oid,
        name=name_val,
        description=desc_val,
        version=ver_val,
        entity_types=[_entity_type_from_dict(t, new_oid, now) for t in et_list],
        relation_types=[RelationType(**t) for t in rt_list],
        create_time=now,
        update_time=now,
        status="活跃",
        schema_version=SCHEMA_VERSION,
    )

    # 用迁移函数统一格式（兼容 Dict/List 属性 + 自动生成实体类型）
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

    # 实体类型重写 id 和 ontology_id（v3：优先 entity_types，回退 concepts）
    new_concepts = []
    concept_id_map = {}
    et_data_list = migrated.get("entity_types")
    if et_data_list is None:
        et_data_list = migrated.get("concepts", [])
    for cd in et_data_list:
        old_cid = cd.get("id") or f"et_{uuid.uuid4().hex[:8]}"
        new_cid = f"et_{uuid.uuid4().hex[:8]}"
        concept_id_map[old_cid] = new_cid
        cd["id"] = new_cid
        cd["ontology_id"] = new_oid
        try:
            new_concepts.append(EntityType(**cd))
        except Exception as e:
            logger.warning(f"导入实体类型失败: {e}")

    # 重写实体的 instance_of 指向新实体类型 id
    for ent in new_entities:
        if ent.instance_of and ent.instance_of in concept_id_map:
            ent.instance_of = concept_id_map[ent.instance_of]

    # v3：导入实体类型间关系
    new_et_relations = []
    for etr in migrated.get("entity_type_relations", []):
        etr["id"] = f"etr_{uuid.uuid4().hex[:8]}"
        etr["ontology_id"] = new_oid
        # 重写 source/target 实体类型 id
        etr["source_entity_type_id"] = concept_id_map.get(etr.get("source_entity_type_id"), etr.get("source_entity_type_id", ""))
        etr["target_entity_type_id"] = concept_id_map.get(etr.get("target_entity_type_id"), etr.get("target_entity_type_id", ""))
        try:
            new_et_relations.append(EntityTypeRelation(**etr))
        except Exception as e:
            logger.warning(f"导入实体类型关系失败: {e}")

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
        entity_types_db[new_oid] = new_concepts
        entity_type_relations_db[new_oid] = new_et_relations  # v3 新增
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
    """导出本体为 JSON（含本体元信息 + 实体类型 + 实体 + 关系）。"""
    ont = _get_ontology_or_404(ontology_id)
    data = {
        "name": ont.name,
        "description": ont.description,
        "version": ont.version,
        "entity_types": [t.dict() for t in ont.entity_types],
        "relation_types": [t.dict() for t in ont.relation_types],
        "concepts": [c.dict() for c in entity_types_db.get(ontology_id, [])],
        "entities": [e.dict() for e in entities_db.get(ontology_id, [])],
        "relations": [r.dict() for r in relations_db.get(ontology_id, [])],
        "entity_type_relations": [
            r.dict() for r in entity_type_relations_db.get(ontology_id, [])
        ],
        "schema_version": SCHEMA_VERSION,
    }
    return {"success": True, "data": data}


@app.get("/ontology/{ontology_id}/owl")
async def export_ontology_owl(ontology_id: str):
    """导出本体为 OWL 2 / RDF 文件（RDF/XML 格式，Protégé 可直接打开）。

    v3 集成：包含 EntityType 层级（subClassOf）+ 类型间关系（ObjectProperty domain/range）。
    若 owlready2 未安装则返回 503，导出异常返回 500。
    """
    if not _owl_available or export_ontology_to_owl is None:
        raise HTTPException(
            status_code=503,
            detail="OWL 导出模块不可用（owlready2 未安装或加载失败）"
        )
    ont = _get_ontology_or_404(ontology_id)
    concepts = entity_types_db.get(ontology_id, [])
    entities = entities_db.get(ontology_id, [])
    relations = relations_db.get(ontology_id, [])
    et_relations = entity_type_relations_db.get(ontology_id, [])
    try:
        owl_path = export_ontology_to_owl(
            ont, concepts, entities, relations,
            entity_type_relations=et_relations,
        )
    except Exception as e:
        logger.error(f"OWL 导出失败 ontology_id={ontology_id}: {e}")
        raise HTTPException(status_code=500, detail=f"OWL 导出失败: {str(e)[:150]}")

    # 返回文件供下载，使用安全的本体名作为下载文件名
    safe_name = ont.name or ontology_id
    download_name = f"{safe_name}_{ontology_id}.owl"
    return FileResponse(
        path=owl_path,
        media_type="application/rdf+xml",
        filename=download_name,
    )


@app.post("/ontology/search")
async def search_ontology(
    query: str = Form(...),
    ontology_id: str = Form(...)
):
    """在某本体内搜索实体与关系（匹配名称、实体类型名、关系类型、属性名/值）。"""
    _get_ontology_or_404(ontology_id)
    query_lower = query.lower()

    # 实体类型ID→实体类型名映射
    concept_name_map = {c.id: c.name for c in entity_types_db.get(ontology_id, [])}

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
async def _llm_json_async(messages: list, temperature: float = 0.3, max_tokens: int = 4000,
                          thinking_type: str = ""):
    """异步调用 LLM 并解析 JSON（在线程池中执行同步 urllib 调用，避免阻塞事件循环）。"""
    loop = __import__('asyncio').get_event_loop()
    return await loop.run_in_executor(
        None, lambda: call_llm_json(messages, temperature, max_tokens, thinking_type)
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
    stage_hints: str = Form(""),
    template_id: str = Form("")
):
    """上传文档创建构建任务（快速返回，不在此解析文档）。

    流程：
    1. 读取文件并持久化到构建任务目录（供后续「文档解析」阶段解析）
    2. 创建 BuildJob（step=0，source_text 为空，携带 granularity + stage_hints）
    3. 持久化任务，返回 job_id

    文档解析 + 本体模型推荐由「文档解析」阶段（POST /ontology/build/{job_id}/parse）
    在后台异步执行，上传接口只负责落盘与建任务，确保前端点「开始构建」后立即跳转。

    Args:
        granularity: 粒度预设 coarse|medium|fine，控制后续提取数量
        stage_hints: JSON 字符串，形如 {"1":"重点关注财务指标","2":"..."}，注入各阶段 prompt
        template_id: 兼容旧前端字段，等同 ontology_model_id（本体模型ID）
    """
    # 1. 读取原始文件内容
    content = await file.read()
    filename = file.filename or "unknown.txt"

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

    # 2. 创建构建任务（source_text 留空，待「文档解析」阶段填充）
    now = datetime.now()
    job_id = _gen_job_id()
    job = BuildJob(
        id=job_id,
        name=name,
        description=description,
        step=0,
        status="draft",
        source_filename=filename,
        source_text="",
        char_count=0,
        granularity=granularity,
        stage_hints=hints_dict,
        create_time=now,
        update_time=now,
    )

    # 2.5 载入本体模型：upload 时一次性快照（防本体模型后续被改/删影响进行中任务）
    # 兼容旧前端字段 template_id（等同 ontology_model_id）
    ontology_model_id = template_id
    if ontology_model_id:
        try:
            tpl = _get_ontology_model_or_404(ontology_model_id)
            job.ontology_model_id = tpl.id
            job.ontology_model_snapshot = tpl.dict()
            # 选择了本体模型即视为强制约束（后续可在构建配置阶段调整/清除）
            job.ontology_model_mode = "hard_constraint"
        except HTTPException as e:
            # 本体模型不存在不阻塞上传，仅告警
            logger.warning(f"build_upload: 本体模型 {ontology_model_id} 不存在，忽略: {e.detail}")

    # 3. 持久化源文件（供「文档解析」阶段读取）+ 持久化任务
    source_path = os.path.join(BUILD_JOBS_DIR, f'{job_id}_source')
    with open(source_path, 'wb') as f:
        f.write(content)

    async with build_lock:
        build_jobs_db[job_id] = job
        save_build_job(job_id)
        save_build_jobs_index()

    return {
        "success": True,
        "message": "文档上传成功，即将进入文档解析",
        "data": {
            "job_id": job_id,
            "granularity": job.granularity,
            "stage_hints": job.stage_hints,
            "template_id": job.ontology_model_id,        # 兼容旧前端字段名
            "ontology_model_id": job.ontology_model_id,
            "template_name": (job.ontology_model_snapshot or {}).get("name", ""),     # 兼容旧前端字段名
            "ontology_model_name": (job.ontology_model_snapshot or {}).get("name", ""),
        }
    }


@app.post("/ontology/build/create")
async def build_create(request: Request):
    """无文件创建构建任务（AI 构建入口）。

    AI 构建不再要求先上传文件，用户可在聊天中上传文档或直接描述需求。
    """
    body = await request.json()
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称为必填")

    now = datetime.now()
    job_id = _gen_job_id()
    job = BuildJob(
        id=job_id,
        name=name,
        description=description,
        build_type="ai_build",
        step=0,
        status="draft",
        source_filename="",
        source_text="",
        char_count=0,
        granularity="medium",
        stage_hints={},
        create_time=now,
        update_time=now,
    )

    async with build_lock:
        build_jobs_db[job_id] = job
        save_build_job(job_id)
        save_build_jobs_index()

    return {
        "success": True,
        "message": "AI 构建任务已创建",
        "data": {"job_id": job_id}
    }


@app.post("/ontology/build/{job_id}/upload-file")
async def build_upload_file(job_id: str, file: UploadFile = File(...)):
    """聊天中追加文档到构建任务。

    上传文件后解析文档内容写入 job.source_text，供后续提取阶段使用。
    """
    job = _get_job_or_404(job_id)
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    content = await file.read()
    filename = file.filename or "unknown.txt"

    # 持久化源文件
    source_path = os.path.join(BUILD_JOBS_DIR, f'{job_id}_source')
    with open(source_path, 'wb') as f:
        f.write(content)

    # 解析文本（传入文件路径，不是字节内容）
    text = extract_text(source_path, filename)

    # 换文档时级联重置已有产出：旧文档的解析候选/摘要/规划及 step1-3 提取结果
    # 对新文档全部失效。不清空会导致「已解析免重跑」用旧文档 meta 误判已解析、
    # 后续提取混入旧文档数据（与 rework 级联重置同一字段集）
    async with build_lock:
        had_outputs = bool(
            job.meta_entity_types or job.meta_relation_types
            or job.step0_summary or job.step0_suggestion or job.step1_plan
            or job.step1_entity_types or job.step1_concepts
            or job.step2_entities or job.step3_verification or job.step4_verification
        )
        if had_outputs:
            logger.info(f"[{job_id}] 上传新文档「{filename}」，级联重置旧文档的全部阶段产出")
            # 阶段 0：解析产出与自动摘要/规划
            job.meta_entity_types = []
            job.meta_relation_types = []
            job.meta_confirmed = False
            job.step0_summary = ""
            job.step0_suggestion = ""
            job.step1_plan = []
            job.step1_hierarchy_hint = ""
            # 阶段 1：实体类型 + 类型间关系 + 分批状态
            job.step1_entity_types = []
            job.step1_entity_type_relations = []
            job.step1_concepts = []
            job.step1_confirmed = False
            job.step1_batch_results = []
            job.step1_batch_relations_results = []
            job.step1_batches_total = 0
            job.step1_batches_done = 0
            job.step1_failed_batch = -1
            job.step1_failed_reason = None
            job.step1_cross_batch_done = False
            job.step1_cross_batch_relations = []
            # 阶段 2：实体 + 实例间关系 + 分批状态
            job.step2_entities = []
            job.step2_relations = []
            job.step3_relations = []  # 兼容旧字段
            job.step2_confirmed = False
            job.step2_batch_results = []
            job.step2_batch_relations_results = []
            job.step2_batches_total = 0
            job.step2_batches_done = 0
            job.step2_failed_batch = -1
            job.step2_failed_reason = None
            # 阶段 3：验证结果
            job.step3_verification = None
            job.step3_confirmed = False
            job.step4_verification = None  # 兼容旧字段
            job.step4_confirmed = False
            job.error_message = None
            job.step = 0
        # source_text 存完整原文（供分批提取/摘要规划使用）；
        # LLM 上下文所需的截断在各自调用点用 truncate_for_llm 处理
        job.source_text = text
        job.char_count = len(text)
        job.source_filename = filename
        job.update_time = datetime.now()
        save_build_job(job_id)

    return {
        "success": True,
        "message": f"文档已上传，共 {len(text)} 字符",
        "data": {
            "filename": filename,
            "char_count": len(text),
            "reset": had_outputs,  # 本次上传是否触发了旧产出的级联重置
        }
    }


async def _generate_doc_summary_and_plan(job_id: str) -> None:
    """解析完成后自动生成「文档摘要 + 构建规划」（阶段 0 收尾）。

    1. extract_headings 提取章节大纲 → LLM 生成 doc_summary / suggestion / 分批方案 / 层级提示
    2. 分批方案（章节标题组）持久化到 job.step1_plan，step1 提取时优先按此分批
    3. 摘要+建议以 assistant 消息写入 chat_history，并广播 chat_message 事件推送到前端聊天

    失败静默降级（摘要为空、step1_plan 回退字符切分），不影响解析本身。

    幂等性：首次解析与聊天触发的重新解析都会走到此函数，
    若已生成过（step0_summary 非空）则跳过，避免聊天里重复推送摘要。
    """
    job = build_jobs_db.get(job_id)
    if not job or not job.source_text:
        return
    # 幂等保护：摘要/规划已生成过则不再生成（重解析只更新元模型，不重复推送摘要）
    if job.step0_summary or job.step0_suggestion or job.step1_plan:
        return
    try:
        _set_job_progress(job_id, 0, 60, "正在生成文档摘要与构建规划...")
        headings = extract_headings(job.source_text)
        outline = [
            {"title": h["title"], "chars": h["end"] - h["start"]}
            for h in headings
        ][:60]  # 大纲截断，防止超长文档 prompt 爆炸
        messages = build_prompts.build_doc_summary_plan_messages(
            doc_preview=job.source_text[:6000],
            outline=outline,
            total_chars=len(job.source_text),
            meta_entity_types=job.meta_entity_types or [],
            name=job.name,
            suggested_batch_chars=config.STEP1_BATCH_MAX_CHARS,
        )
        plan_max_tokens, plan_thinking = config.get_chat_llm_params("plan")
        result = await _llm_json_async(
            messages, temperature=0.3, max_tokens=plan_max_tokens, thinking_type=plan_thinking
        )

        doc_summary = (result.get("doc_summary") or "").strip()
        suggestion = (result.get("suggestion") or "").strip()
        hierarchy_hint = (result.get("hierarchy_hint") or "").strip()
        batches = result.get("batches") or []

        # 校验分批方案：标题必须能匹配到大纲章节，非法批组丢弃
        valid_titles = {h["title"] for h in headings}
        plan_batches = []
        for b in batches:
            titles = [t for t in (b.get("titles") or []) if t in valid_titles]
            if titles:
                plan_batches.append({"titles": titles})
        if headings and not plan_batches:
            # LLM 方案全部非法：退化为按章节自动打包的方案（仍优于纯字符切批）
            auto = split_by_headings(
                job.source_text, headings, max_chars=config.STEP1_BATCH_MAX_CHARS
            )
            if auto:
                plan_batches = [{"titles": t["titles"]} for t in auto]

        async with build_lock:
            job.step0_summary = doc_summary
            job.step0_suggestion = suggestion
            job.step1_plan = plan_batches
            # 摘要消息与层级提示一并落库，step1 prompt 注入层级提示用
            job.step1_hierarchy_hint = hierarchy_hint
            job.update_time = datetime.now()
            save_build_job(job_id)
        save_build_jobs_index()

        # 计算实际生效的批次（与 step1 提取共用 _build_step1_batches，同一份 job 状态），
        # 摘要里展示的「共 N 批」与提取阶段真实批数一致，不再出现「规划 3 批、实际 5 批」。
        eff_batches, eff_titles = _build_step1_batches(job)
        parts = []
        if doc_summary:
            parts.append(f"**文档摘要**\n\n{doc_summary}")
        if suggestion:
            parts.append(f"**构建建议**\n\n{suggestion}")
        if eff_batches:
            batch_desc = "、".join(
                f"第{i + 1}批({'/'.join(t[:2])})"
                for i, t in enumerate(eff_titles[:8])
            )
            parts.append(
                f"**分批规划**（共 {len(eff_batches)} 批，按章节语义切分）\n\n{batch_desc}"
            )
        content = "\n\n---\n\n".join(parts) if parts else "文档解析完成。可回复「开始提取」构建实体类型。"

        async with build_lock:
            job.chat_history.append({
                "role": "assistant",
                "content": content,
                "intent": "doc_summary",
                "created_at": datetime.now().isoformat(),
            })
            job.update_time = datetime.now()
            save_build_job(job_id)
        save_build_jobs_index()

        _emit_event(job_id, "chat_message", {
            "message": {"role": "assistant", "content": content, "intent": "doc_summary"},
        })
        logger.info(f"[{job_id}] 文档摘要与构建规划已生成（{len(eff_batches)} 批）")
    except Exception as e:
        logger.warning(f"[{job_id}] 文档摘要/构建规划生成失败（不影响解析结果）: {e}")


async def _background_parse_document(job_id: str) -> None:
    """后台任务：阶段 0「文档解析」——解析文档 + 推荐本体模型。

    上传时只落盘了源文件与任务骨架，此任务在此真正解析文档：
    1. 读取持久化源文件 → extract_text → truncate_for_llm
    2. 写入 source_text / char_count
    3. 调用 LLM 推荐本体模型（失败用默认本体模型兜底）
    4. 标记阶段 0 完成，广播 parse_done 事件
    """
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        _mark_stage_started(job_id, 0)
        _set_job_progress(job_id, 0, 10, "正在解析文档...")

        # 1. 读取持久化源文件并解析
        source_path = os.path.join(BUILD_JOBS_DIR, f'{job_id}_source')
        if not os.path.exists(source_path):
            raise ValueError("源文件不存在，无法解析")
        doc_text = extract_text(source_path, job.source_filename)

        if not doc_text or len(doc_text.strip()) < 20:
            raise ValueError("文档内容为空或过短，无法提取本体")

        # 2. 截断供 LLM 使用（source_text 保留完整原文）
        doc_text_truncated = truncate_for_llm(doc_text)

        # 3. LLM 推荐本体模型（失败用默认兜底，不阻塞解析完成）
        meta_source = "llm"
        try:
            messages = build_prompts.build_meta_messages(doc_text_truncated, job.name, template=job.ontology_model_snapshot, template_mode=job.ontology_model_mode)
            meta_max_tokens, meta_thinking = config.get_llm_params("meta")
            meta = await _llm_json_async(messages, temperature=0.3, max_tokens=meta_max_tokens, thinking_type=meta_thinking)
            job.meta_entity_types = meta.get("entity_types", [])
            job.meta_relation_types = meta.get("relation_types", [])
            if not job.meta_entity_types:
                job.meta_entity_types = [{"name": t["name"], "color": t.get("color", "#5470c6")}
                                         for t in DEFAULT_ENTITY_TYPES]
            if not job.meta_relation_types:
                job.meta_relation_types = [{"name": t["name"]} for t in DEFAULT_RELATION_TYPES]
        except Exception as e:
            logger.warning(f"LLM 推荐本体模型失败，使用默认本体模型: {e}")
            job.meta_entity_types = [{"name": t["name"], "color": t.get("color", "#5470c6")}
                                     for t in DEFAULT_ENTITY_TYPES]
            job.meta_relation_types = [{"name": t["name"]} for t in DEFAULT_RELATION_TYPES]
            meta_source = "default（LLM 调用失败）"

        # 4. 落库解析结果 + 预估分批数
        # 预计算 step1/step2 分批数（与实际分批逻辑一致，用于前端在解析阶段即展示"将分 N 批"）
        if len(doc_text) <= config.STEP1_BATCH_THRESHOLD_CHARS:
            est_step1_batches = 1
        else:
            est_step1_batches = len(split_into_batches(
                doc_text, max_chars=config.STEP1_BATCH_MAX_CHARS, overlap=config.STEP1_BATCH_OVERLAP))
        if len(doc_text) <= config.STEP2_BATCH_THRESHOLD_CHARS:
            est_step2_batches = 1
        else:
            est_step2_batches = len(split_into_batches(
                doc_text, max_chars=config.STEP2_BATCH_MAX_CHARS, overlap=config.STEP2_BATCH_OVERLAP))

        async with build_lock:
            job.source_text = doc_text
            job.char_count = len(doc_text)
            job.estimated_step1_batches = est_step1_batches
            job.estimated_step2_batches = est_step2_batches
            job.error_message = ""  # 解析成功，清除历史错误（如服务重启中断标记）
            job.update_time = datetime.now()
            save_build_job(job_id)

        # 5. 自动生成文档摘要 + 构建规划（失败静默降级）
        await _generate_doc_summary_and_plan(job_id)
        # 联动聊天：翻任务标签为完成（摘要消息已由上方推送，不再追加完成回复）
        await _finalize_task_chat(
            job_id, 0, True,
            f"文档解析完成，识别到 {len(job.meta_entity_types)} 个实体类型候选",
            no_message=True,
        )

        _set_job_progress(job_id, -1, 100, "文档解析完成")
        _mark_stage_finished(job_id, 0)
        _emit_event(job_id, "parse_done", {
            "step": 0,
            "char_count": job.char_count,
            "source_filename": job.source_filename,
            "meta_source": meta_source,
            "meta_entity_types": job.meta_entity_types,
            "meta_relation_types": job.meta_relation_types,
            "estimated_step1_batches": est_step1_batches,
            "estimated_step2_batches": est_step2_batches,
            "planned_step1_batches": len(job.step1_plan) if job.step1_plan else est_step1_batches,
        })
    except Exception as e:
        logger.exception(f"[{job_id}] 文档解析失败: {e}")
        _mark_stage_finished(job_id, 0, success=False)
        async with build_lock:
            job.error_message = f"文档解析失败: {e}"
            job.update_time = datetime.now()
            save_build_job(job_id)
        _set_job_progress(job_id, -1, 100, "文档解析失败")
        await _finalize_task_chat(job_id, 0, False, job.error_message or "文档解析失败")
        _emit_event(job_id, "error", {"step": 0, "message": job.error_message})
    finally:
        _background_tasks.pop(job_id, None)


@app.post("/ontology/build/{job_id}/parse")
async def build_parse(job_id: str):
    """阶段 0「文档解析」：解析上传的文档 + 推荐本体模型（后台异步执行）。

    立即返回，前端通过 SSE 订阅 parse_done/error 事件。
    """
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")
    if job.meta_confirmed:
        raise HTTPException(status_code=400, detail="文档已解析并确认配置，无需重复解析")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")
    # 已解析完成但未确认配置（如刷新页面后重进）：直接返回，避免重复解析
    if job.source_text and job.char_count > 0:
        return {"success": True, "message": "文档已解析", "data": {"job_id": job_id, "char_count": job.char_count}}

    _set_job_progress(job_id, 0, 5, "正在准备解析文档...")
    task = asyncio.create_task(_background_parse_document(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "文档解析已在后台开始",
        "data": {"job_id": job_id, "running_step": 0}
    }


@app.post("/ontology/build/manual")
async def build_manual(
    name: str = Form(...),
    description: str = Form(""),
    ontology_id: str = Form(...),
):
    """创建手动构建任务（无文档，作为断点续作的「进行中任务」载体）。

    手动构建向导（/ontology/manual/{id}）将数据实时 CRUD 到本体，
    BuildJob 仅承担入口与完成标记：
    - status=draft 时出现在「进行中的构建任务」列表，可点击继续进入向导页
    - 用户点「完成构建」后通过 PUT /ontology/build/{job_id}/complete 标记完成
    """
    now = datetime.now()
    job_id = _gen_job_id()
    job = BuildJob(
        id=job_id,
        name=name,
        description=description,
        step=0,
        status="draft",
        build_type="manual",
        source_filename="手动构建",
        ontology_id=ontology_id,
        create_time=now,
        update_time=now,
    )
    async with build_lock:
        build_jobs_db[job_id] = job
        save_build_job(job_id)
        save_build_jobs_index()
    return {
        "success": True,
        "message": "手动构建任务已创建",
        "data": {"job_id": job_id},
    }


@app.put("/ontology/build/{job_id}/complete")
async def build_complete(job_id: str):
    """标记构建任务完成（手动构建「完成构建」时调用，从进行中列表移除）。"""
    job = build_jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="构建任务不存在")
    job.status = "completed"
    job.step = 4
    job.update_time = datetime.now()
    async with build_lock:
        save_build_job(job_id)
        save_build_jobs_index()
    # 手动构建完成：将对应本体从「构建中」置为「活跃」，使其出现在已完成本体列表
    if job.build_type == "manual" and job.ontology_id:
        ont = ontologies_db.get(job.ontology_id)
        if ont and ont.status == "构建中":
            ont.status = "活跃"
            ont.update_time = datetime.now()
            async with db_lock:
                save_ontology(ont.id)
    return {"success": True, "message": "构建任务已完成"}


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
                "build_type": j.build_type,
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
                "template_id": j.ontology_model_id,           # 兼容旧前端字段名
                "ontology_model_id": j.ontology_model_id,
                "template_name": (j.ontology_model_snapshot or {}).get("name", ""),  # 兼容旧前端字段名
                "ontology_model_name": (j.ontology_model_snapshot or {}).get("name", ""),
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
            "template_id": job.ontology_model_id,           # 兼容旧前端字段名
            "ontology_model_id": job.ontology_model_id,
            "template_name": (job.ontology_model_snapshot or {}).get("name", ""),  # 兼容旧前端字段名
            "ontology_model_name": (job.ontology_model_snapshot or {}).get("name", ""),
            # Step 1 本体提取分批状态
            "step1_batches_total": job.step1_batches_total,
            "step1_batches_done": job.step1_batches_done,
            "step1_failed_batch": job.step1_failed_batch,
            # Step 2 实体提取分批状态
            "step2_batches_total": job.step2_batches_total,
            "step2_batches_done": job.step2_batches_done,
            "step2_failed_batch": job.step2_failed_batch,
            # 预估分批数（step0 解析后预计算，step1/2 实际运行前供前端展示）
            "estimated_step1_batches": job.estimated_step1_batches,
            "estimated_step2_batches": job.estimated_step2_batches,
            # Step 3 关系建模分组状态
            "step3_groups_total": job.step3_groups_total,
            "step3_groups_done": job.step3_groups_done,
            "step3_failed_group": job.step3_failed_group,
            # Step 3 跨组关系补充状态
            "step3_cross_group_done": job.step3_cross_group_done,
            "step3_cross_group_failed": job.step3_cross_group_failed,
            # Step 4 验证结果
            "step4_verification": job.step4_verification,
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
                        "entity_types": job.step1_entity_types or job.step1_concepts,
                        "entity_type_relations": job.step1_entity_type_relations or [],
                        "concepts": job.step1_concepts,  # 兼容旧前端
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
                        "verification": job.step4_verification
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
    data = job.dict()
    # 剔除大字段，避免全量序列化阻塞事件循环 + 响应体过大导致 30s 超时：
    # source_text 为完整文档原文、chat_history 为全部对话，前端分别通过
    # getBuildProgress / getChatHistory 获取，此处全量返回既无用又拖慢接口
    data.pop("source_text", None)
    data.pop("chat_history", None)
    # 顶层补充 template_name / ontology_model_name 便于前端展示（ontology_model_snapshot 已含完整本体模型）
    data["template_name"] = (job.ontology_model_snapshot or {}).get("name", "")  # 兼容旧前端字段名
    data["ontology_model_name"] = (job.ontology_model_snapshot or {}).get("name", "")
    return {"success": True, "data": data}


def _build_stage_graph(job: "BuildJob", stage: int) -> Dict[str, Any]:
    """构建某阶段的图谱预览数据（只读，nodes + links）。

    各阶段图谱内容：
    - stage=1: 实体类型节点（按 entity_type 着色），无边
    - stage=2: 实体类型节点 + 实体节点 + instance_of 边（实体颜色继承实体类型）
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
        # 实体类型节点
        for c in (job.step1_concepts or []):
            nodes.append({
                "id": f"concept_{_normalize_name(c.get('name', ''))}",
                "name": c.get("name", ""),
                "node_type": "concept",
                "entity_type": c.get("entity_type", ""),
                "color": c.get("color") or _derive_type_color(c.get("entity_type", ""), job.meta_entity_types),
                "description": c.get("description", ""),
            })

    if stage >= 2:
        # 实体节点 + instance_of 边
        # 实体类型名 → 颜色（实体颜色继承实体类型）
        concept_color_map = {
            _normalize_name(c.get("name", "")): c.get("color") or _derive_type_color(c.get("entity_type", ""), job.meta_entity_types)
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
            # instance_of 边（实体类型 → 实体）
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

    # stage=1 时去掉实体节点和边（只保留实体类型节点）
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
        stage: 阶段号 1=实体类型 / 2=实体属性 / 3=关系 / 4=验证
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
    entity_types: str = Form(""),
    relation_types: str = Form(""),
    granularity: str = Form("medium"),
    stage_hints: str = Form(""),
    template_id: str = Form(""),
    template_mode: str = Form("")
):
    """用户确认或编辑本体模型 + 粒度 + 阶段提示词 + 本体模型。

    确认后本体模型、粒度、阶段提示词固定，后续 step1/step2/step3 的 LLM 调用遵守此约束。
    entity_types / relation_types 未传时沿用 upload 阶段已生成的本体模型（兼容前端不重新编辑本体模型的场景）。
    template_id / template_mode 兼容旧前端字段，等同 ontology_model_id / ontology_model_mode。
    """
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成，不可修改")

    # 本体模型可缺省：未传或为空时沿用 upload 阶段 LLM 推荐的本体模型
    et_list = _parse_json_arg(entity_types, None)
    rt_list = _parse_json_arg(relation_types, None)
    if not isinstance(et_list, list) or not et_list:
        et_list = job.meta_entity_types or []
    if not isinstance(rt_list, list) or not rt_list:
        rt_list = job.meta_relation_types or []
    if not et_list:
        raise HTTPException(status_code=400, detail="entity_types 不能为空")
    if not rt_list:
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

    # 本体模型配置：确认时允许修改/切换本体模型，未选择则清除本体模型约束（真实连接语义）
    # 兼容旧前端字段 template_id / template_mode（等同 ontology_model_id / ontology_model_mode）
    ontology_model_id = template_id
    ontology_model_mode = template_mode
    if ontology_model_id:
        try:
            tpl = _get_ontology_model_or_404(ontology_model_id)
            job.ontology_model_id = tpl.id
            job.ontology_model_snapshot = tpl.dict()
            # 载入本体模型：默认强制约束（hard_constraint），兼容旧 soft_constraint / skip_step1
            job.ontology_model_mode = ontology_model_mode if ontology_model_mode in ("skip_step1", "soft_constraint", "hard_constraint") else "hard_constraint"
        except HTTPException as e:
            logger.warning(f"build_confirm_meta: 本体模型 {ontology_model_id} 不存在，忽略: {e.detail}")
    else:
        # 用户未选择本体模型：清除本体模型约束，让 LLM 从零自由提取
        job.ontology_model_id = None
        job.ontology_model_snapshot = None
        job.ontology_model_mode = "soft_constraint"

    async with build_lock:
        job.meta_entity_types = et_list
        job.meta_relation_types = rt_list
        job.granularity = granularity
        job.stage_hints = hints_dict
        job.meta_confirmed = True
        job.step = max(job.step, 1)  # 确认本体模型后进入 step 1
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
        save_build_jobs_index()

    return {
        "success": True,
        "message": "配置已确认，可执行本体提取",
        "data": {
            "job_id": job_id,
            "meta_entity_types": job.meta_entity_types,
            "meta_relation_types": job.meta_relation_types,
            "granularity": job.granularity,
            "stage_hints": job.stage_hints,
        }
    }


@app.post("/ontology/build/{job_id}/step1")
async def build_step1(job_id: str, request: Request):
    """Step 1: LLM 从文档提取本体清单（类型层，后台异步执行）。

    前置条件：本体模型已确认（meta_confirmed=True）。
    stage_hint: 表单字段，用户在本阶段开始时补充的提示词（可选），会注入本次 LLM 提取并持久化。
    立即返回，LLM 调用在后台进行，前端通过 GET /progress 或 GET /build/{job_id} 轮询结果。
    用户可在后台执行期间离开页面，稍后回来查看。
    """
    # 容错解析 stage_hint：空 FormData 请求体也能正常处理，避免 FastAPI 400
    stage_hint = await _parse_form_field(request, "stage_hint")
    job = _get_job_or_404(job_id)
    if not job.meta_confirmed:
        raise HTTPException(status_code=400, detail="请先确认本体模型（PUT /ontology/build/{job_id}/meta）")
    if job.step1_confirmed:
        raise HTTPException(status_code=400, detail="实体类型清单已确认，如需重新提取请先撤销确认")
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
        if stage_hint and stage_hint.strip():
            if not job.stage_hints:
                job.stage_hints = {}
            job.stage_hints[1] = stage_hint.strip()
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
    _set_job_progress(
        job_id, 1, 5,
        "继续提取本体..." if is_resume else "正在准备提取本体..."
    )
    task = asyncio.create_task(_background_extract_entity_types(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "本体提取继续运行，从失败批次续跑..." if is_resume else "本体提取已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 1, "is_resume": is_resume}
    }


@app.put("/ontology/build/{job_id}/step1")
async def build_confirm_step1(
    job_id: str,
    entity_types: str = Form(""),
    entity_type_relations: str = Form(""),
    concepts: str = Form(""),  # 兼容旧前端（作为 entity_types 的别名）
):
    """用户确认实体类型清单（可编辑后提交）。

    v3：确认实体类型（含层级+属性骨架）+ 类型间关系。
    确认后才能执行 step2（实体+关系提取）。
    兼容旧前端：concepts 参数作为 entity_types 的别名。
    """
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")

    # v3：优先读 entity_types，兼容旧前端 concepts 参数
    raw_types = entity_types if entity_types else concepts
    if not raw_types:
        raise HTTPException(status_code=400, detail="实体类型清单不能为空（entity_types 或 concepts 参数缺失）")

    try:
        types_list = json.loads(raw_types) if isinstance(raw_types, str) else raw_types
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"实体类型清单 JSON 解析失败: {e}")

    if not isinstance(types_list, list) or not types_list:
        raise HTTPException(status_code=400, detail="实体类型清单不能为空")

    # v3：解析类型间关系（可选，旧前端不传则为空列表）
    et_relations_list = []
    if entity_type_relations:
        try:
            parsed = json.loads(entity_type_relations) if isinstance(entity_type_relations, str) else entity_type_relations
            if isinstance(parsed, list):
                et_relations_list = parsed
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"entity_type_relations 解析失败，忽略: {e}")

    async with build_lock:
        job.step1_entity_types = types_list
        job.step1_entity_type_relations = et_relations_list
        job.step1_concepts = types_list  # 兼容旧字段
        job.step1_confirmed = True
        job.error_message = None
        job.step = max(job.step, 2)
        job.update_time = datetime.now()
        save_build_job(job_id)

    return {
        "success": True,
        "message": "实体类型清单已确认，可执行实体+关系提取",
        "data": {"job_id": job_id, "step": job.step}
    }


@app.post("/ontology/build/{job_id}/step2")
async def build_step2(job_id: str, request: Request):
    """Step 2: LLM 从文档提取实体+属性（实例层，后台异步执行）。

    前置条件：step1 已确认。
    stage_hint: 表单字段，用户在本阶段开始时补充的提示词（可选），会注入本次 LLM 提取并持久化。
    立即返回，LLM 调用在后台进行，前端轮询结果。
    """
    # 容错解析 stage_hint：空 FormData 请求体也能正常处理，避免 FastAPI 400
    stage_hint = await _parse_form_field(request, "stage_hint")
    job = _get_job_or_404(job_id)
    if not job.step1_confirmed:
        raise HTTPException(status_code=400, detail="请先确认实体类型清单（PUT /ontology/build/{job_id}/step1）")
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
        if stage_hint and stage_hint.strip():
            if not job.stage_hints:
                job.stage_hints = {}
            job.stage_hints[2] = stage_hint.strip()
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
    relations: str = Form(""),
    primary_entity_selected: str = Form(""),  # 兼容旧前端（v3 已弃用）
):
    """用户确认实体清单+关系清单（可编辑后提交）。

    v3：合并原 step2 确认 + step3 确认。确认后才能执行 step3（验证+报告）。

    Args:
        entities: 实体清单 JSON（含 instance_of + properties）
        relations: 实例间关系清单 JSON（v3 新增，旧前端不传则为空）
        primary_entity_selected: 已弃用，兼容旧前端
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

    # v3：解析实例间关系（可选，旧前端不传则保留后台提取结果）
    relations_list = []
    if relations:
        try:
            parsed = json.loads(relations) if isinstance(relations, str) else relations
            if isinstance(parsed, list):
                relations_list = parsed
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"relations 解析失败，忽略: {e}")

    # 兼容旧字段：primary_entity_selected（v3 已弃用，仅解析不使用）
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
        # v3：关系清单优先使用用户提交的，否则保留后台提取结果
        if relations_list:
            job.step2_relations = relations_list
            job.step3_relations = relations_list  # 兼容旧字段
        job.primary_entity_selected = primary_selected  # 兼容旧字段
        job.step2_confirmed = True
        job.error_message = None
        job.step = max(job.step, 3)
        job.update_time = datetime.now()
        save_build_job(job_id)

    return {
        "success": True,
        "message": "实体+关系清单已确认，可执行验证+报告",
        "data": {"job_id": job_id, "step": job.step, "primary_entity_selected": primary_selected}
    }


@app.post("/ontology/build/{job_id}/step3")
async def build_step3(job_id: str, request: Request):
    """Step 3: LLM 自检验证 + 报告生成（v3 后台异步执行）。

    v3 重构：原 step4 验证+报告 降为 step3。
    前置条件：step2 已确认（实体+关系提取完成）。
    stage_hint: 表单字段，用户在本阶段开始时补充的提示词（可选），会注入本次验证并持久化。
    立即返回，LLM 调用在后台进行，前端轮询结果。
    """
    # 容错解析 stage_hint：空 FormData 请求体也能正常处理，避免 FastAPI 400
    stage_hint = await _parse_form_field(request, "stage_hint")
    job = _get_job_or_404(job_id)
    if not job.step2_confirmed:
        raise HTTPException(status_code=400, detail="请先确认实体+关系清单（PUT /ontology/build/{job_id}/step2）")
    if job.step3_confirmed:
        raise HTTPException(status_code=400, detail="验证结果已确认，如需重新验证请先撤销确认")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    # v3：验证步骤无分批续跑实体类型，已运行过则标记为重试验证
    is_resume = bool(job.step3_verification or job.step4_verification)

    async with build_lock:
        if stage_hint and stage_hint.strip():
            if not job.stage_hints:
                job.stage_hints = {}
            job.stage_hints[3] = stage_hint.strip()
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
    _set_job_progress(
        job_id, 3, 5,
        "继续验证..." if is_resume else "正在准备验证..."
    )
    task = asyncio.create_task(_background_verify_and_report(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "验证+报告生成已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 3, "is_resume": is_resume}
    }


@app.put("/ontology/build/{job_id}/step3")
async def build_confirm_step3(job_id: str):
    """用户确认验证结果，触发正式本体生成。

    v3 重构：原 step4 确认 降为 step3 确认。这是四阶段流程的最后一步。
    前置条件：step3 验证已完成（step3_verification 非空）。
    兼容旧任务：step3_verification 为空时回退检查 step4_verification。
    """
    job = _get_job_or_404(job_id)
    # v3：检查 step3_verification，兼容旧任务 step4_verification
    if not job.step3_verification and not job.step4_verification:
        raise HTTPException(status_code=400, detail="请先执行验证（POST /ontology/build/{job_id}/step3）")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")

    # 生成正式本体（同步执行，无 LLM 调用，快速完成）
    try:
        new_oid = _generate_formal_ontology(job_id)
    except Exception as e:
        logger.error(f"[{job_id}] 正式本体生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"本体生成失败: {str(e)[:150]}")

    # 统计实体和关系数量
    ent_count = len(job.step2_entities or [])
    rel_count = len(job.step3_relations or job.step2_relations or [])

    async with build_lock:
        job.ontology_id = new_oid
        job.step3_confirmed = True
        job.step4_confirmed = True  # 兼容旧字段
        job.step = 4
        job.status = "completed"
        job.running_step = -1
        job.progress = 100
        job.progress_message = f"本体生成成功！共 {ent_count} 个实体，{rel_count} 条关系"
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
        save_build_jobs_index()

    logger.info(f"[{job_id}] 四阶段构建完成，生成本体: {new_oid}")
    return {
        "success": True,
        "message": "验证结果已确认，正式本体已生成",
        "data": {"job_id": job_id, "ontology_id": new_oid, "step": job.step}
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
    # 删除持久化的源文件（阶段 0 文档解析前上传时落盘）
    source_path = os.path.join(BUILD_JOBS_DIR, f'{job_id}_source')
    if os.path.exists(source_path):
        os.remove(source_path)
    return {"success": True, "message": "构建任务已删除"}


@app.post("/ontology/build/{job_id}/rework/{step}")
async def build_rework(job_id: str, step: int, request: Request):
    """返工：重新执行指定步骤（用户可输入新提示词，重新调用 LLM）。

    v3 新增：支持每步返工，返工时重置该步骤及所有后续步骤的状态。
    返工记录追加到 rework_history，便于溯源。

    Args:
        job_id: 构建任务ID
        step: 返工步骤（1=本体提取, 2=实体+关系提取, 3=验证+报告）
        request: 表单字段 stage_hint/prompt（可选，空则沿用原提示词；二者互为别名）
    """
    # 容错解析表单字段：空 FormData 请求体也能正常处理，避免 FastAPI 400
    stage_hint = await _parse_form_field(request, "stage_hint")
    prompt = await _parse_form_field(request, "prompt")
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成，无法返工（如需修改请编辑正式本体）")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")
    if step not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="返工步骤必须为 1、2 或 3")

    # 兼容前端字段名：prompt 与 stage_hint 取非空者
    if prompt and prompt.strip() and not stage_hint:
        stage_hint = prompt

    # 前置条件检查：返工某步需要前序步骤已确认
    if step == 2 and not job.step1_confirmed:
        raise HTTPException(status_code=400, detail="请先完成步骤1（本体提取并确认）")
    if step == 3 and not job.step2_confirmed:
        raise HTTPException(status_code=400, detail="请先完成步骤2（实体+关系提取并确认）")

    async with build_lock:
        # 更新阶段提示词（空值则保留原提示词）
        if stage_hint:
            if not job.stage_hints:
                job.stage_hints = {}
            job.stage_hints[step] = stage_hint

        # 记录返工历史
        if not job.rework_history:
            job.rework_history = []
        job.rework_history.append({
            "step": step,
            "stage_hint": stage_hint,
            "time": datetime.now().isoformat(),
        })

        # 级联重置：该步骤及所有后续步骤的状态清空
        if step <= 1:
            job.step1_entity_types = []
            job.step1_entity_type_relations = []
            job.step1_concepts = []
            job.step1_confirmed = False
            job.step1_batch_results = []
            job.step1_batch_relations_results = []
            job.step1_batches_total = 0
            job.step1_batches_done = 0
            job.step1_failed_batch = -1
            job.step1_failed_reason = None
            # 跨批关系补充状态一并重置：否则新一轮提取会跳过跨批补充
            # （step1_cross_batch_done 仍为 True），且旧跨批关系被混入新类型的结果造成污染
            job.step1_cross_batch_done = False
            job.step1_cross_batch_relations = []
        if step <= 2:
            job.step2_entities = []
            job.step2_relations = []
            job.step3_relations = []  # 兼容旧字段
            job.step2_confirmed = False
            job.step2_batch_results = []
            job.step2_batch_relations_results = []
            job.step2_batches_total = 0
            job.step2_batches_done = 0
            job.step2_failed_batch = -1
            job.step2_failed_reason = None
        if step <= 3:
            job.step3_verification = None
            job.step3_confirmed = False
            job.step4_verification = None  # 兼容旧字段
            job.step4_confirmed = False

        job.step = step - 1
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)

    # 启动后台任务
    step_names = {1: "本体提取", 2: "实体+关系提取", 3: "验证"}
    if step == 1:
        _set_job_progress(job_id, 1, 5, f"正在重新{step_names[step]}...")
        task = asyncio.create_task(_background_extract_entity_types(job_id))
    elif step == 2:
        _set_job_progress(job_id, 2, 5, f"正在重新{step_names[step]}...")
        task = asyncio.create_task(_background_extract_entities(job_id))
    else:
        _set_job_progress(job_id, 3, 5, f"正在重新{step_names[step]}...")
        task = asyncio.create_task(_background_verify_and_report(job_id))
    _background_tasks[job_id] = task

    logger.info(f"[{job_id}] 步骤 {step}（{step_names[step]}）返工已启动")
    return {
        "success": True,
        "message": f"步骤 {step}（{step_names[step]}）返工已在后台开始",
        "data": {"job_id": job_id, "running_step": step, "rework": True}
    }


# ── AI 构建聊天：当前状态查询 ──

def _get_current_state(job_id: str) -> Dict[str, Any]:
    """获取构建任务当前状态摘要（下拉面板 / 图谱 / LLM 上下文同源）。"""
    job = build_jobs_db.get(job_id)
    if not job:
        return {"error": "任务不存在"}
    return {
        "job_id": job_id,
        "name": job.name,
        "running_step": job.running_step,
        "progress": job.progress,
        "progress_message": job.progress_message,
        "meta_confirmed": job.meta_confirmed,
        "step1_confirmed": job.step1_confirmed,
        "step2_confirmed": job.step2_confirmed,
        "step3_confirmed": job.step3_confirmed,
        "entity_types": job.step1_entity_types or job.step1_concepts or [],
        "entity_type_relations": job.step1_entity_type_relations or [],
        "entities": job.step2_entities or [],
        # step3_relations 是关系建模的最终结果（step2 完成时两者相等，step3 完成后 step3_relations 更完整）
        "relations": job.step3_relations or job.step2_relations or [],
        "verification": job.step3_verification or job.step4_verification,
        "ontology_id": job.ontology_id,
        "error_message": job.error_message,
        "status": job.status,
    }


# ── AI 构建聊天：编辑处理 ──

def _apply_edit_operation(job, operation: dict) -> str:
    """将结构化编辑操作应用到 job 当前状态（即时写回，不落库到正式本体）。

    支持操作类型：
    - add_entity_type: 新增实体类型
    - update_entity_type: 更新实体类型（按 name 匹配）
    - delete_entity_type: 删除实体类型（按 name 匹配）
    - add_entity: 新增实体
    - update_entity: 更新实体
    - delete_entity: 删除实体
    - add_relation: 新增关系
    - delete_relation: 删除关系
    - add_et_relation: 新增类型间关系
    - delete_et_relation: 删除类型间关系

    Returns:
        操作结果描述文本
    """
    op = operation.get("op", "")
    target = operation.get("target", {})
    if not op or not target:
        return "编辑操作无效：缺少 op 或 target"

    if op == "add_entity_type":
        if not job.step1_entity_types:
            job.step1_entity_types = []
        job.step1_entity_types.append(target)
        return f"已新增实体类型「{target.get('name', '')}」"

    elif op == "update_entity_type":
        name = target.get("name", "")
        source = job.step1_entity_types or job.step1_concepts or []
        for et in source:
            if _normalize_name(et.get("name", "")) == _normalize_name(name):
                et.update(target)
                return f"已更新实体类型「{name}」"
        return f"未找到实体类型「{name}」"

    elif op == "delete_entity_type":
        name = target.get("name", "")
        source = job.step1_entity_types or job.step1_concepts or []
        old_len = len(source)
        kept = [et for et in source if _normalize_name(et.get("name", "")) != _normalize_name(name)]
        job.step1_entity_types = kept
        job.step1_concepts = kept  # 同步兼容字段，避免 or 回退读到旧值
        return f"已删除实体类型「{name}」" if len(kept) < old_len else f"未找到实体类型「{name}」"

    elif op == "keep_only_entity_types":
        # 白名单保留：仅保留 keep_names 及其子类型（parent_entity_type_name 逐层下钻），
        # 删除其余实体类型，并级联清理类型间关系、实例及实例间关系。
        keep_names = target.get("keep_names") or target.get("names") or []
        keep_names = [_normalize_name(n) for n in keep_names if n]
        if not keep_names:
            return "保留名单为空，未执行删除"
        source = job.step1_entity_types or job.step1_concepts or []
        # 保留集合：白名单 + 所有父类型在保留集合内的后代子类型（迭代下钻至稳定）
        keep_set = set(keep_names)
        changed = True
        while changed:
            changed = False
            for et in source:
                nm = _normalize_name(et.get("name", ""))
                if not nm or nm in keep_set:
                    continue
                parent = _normalize_name(et.get("parent_entity_type_name") or et.get("parent_concept_name") or "")
                if parent and parent in keep_set:
                    keep_set.add(nm)
                    changed = True

        kept = [et for et in source if _normalize_name(et.get("name", "")) in keep_set]
        removed_names = {
            _normalize_name(et.get("name", ""))
            for et in source if _normalize_name(et.get("name", "")) not in keep_set
        }
        job.step1_entity_types = kept
        job.step1_concepts = kept  # 同步兼容字段

        # 清理类型间关系：任一端类型被删则删
        et_rels = job.step1_entity_type_relations or []
        job.step1_entity_type_relations = [
            r for r in et_rels
            if _normalize_name(r.get("source_entity_type_name", "") or r.get("source", "")) not in removed_names
            and _normalize_name(r.get("target_entity_type_name", "") or r.get("target", "")) not in removed_names
        ]

        # 删除 instance_of 指向被删类型的实体
        ents = job.step2_entities or []
        kept_ents = [e for e in ents if _normalize_name(e.get("instance_of", "")) not in removed_names]
        removed_ent_names = {
            _normalize_name(e.get("name", ""))
            for e in ents if _normalize_name(e.get("instance_of", "")) in removed_names
        }
        job.step2_entities = kept_ents

        # 删除涉及被删实体的实例间关系（step2/step3 两处兼容字段同步）
        for field in ("step2_relations", "step3_relations"):
            rels = getattr(job, field) or []
            kept_rels = [
                r for r in rels
                if _normalize_name(r.get("source", "")) not in removed_ent_names
                and _normalize_name(r.get("target", "")) not in removed_ent_names
            ]
            setattr(job, field, kept_rels)

        return (
            f"已保留 {len(kept)} 个实体类型（含子类型），"
            f"删除其余 {len(removed_names)} 个类型及其关联实体/关系"
        )

    elif op == "add_entity":
        if not job.step2_entities:
            job.step2_entities = []
        job.step2_entities.append(target)
        return f"已新增实体「{target.get('name', '')}」"

    elif op == "update_entity":
        name = target.get("name", "")
        source = job.step2_entities or []
        for ent in source:
            if _normalize_name(ent.get("name", "")) == _normalize_name(name):
                ent.update(target)
                return f"已更新实体「{name}」"
        return f"未找到实体「{name}」"

    elif op == "delete_entity":
        name = target.get("name", "")
        source = job.step2_entities or []
        old_len = len(source)
        job.step2_entities = [ent for ent in source if _normalize_name(ent.get("name", "")) != _normalize_name(name)]
        return f"已删除实体「{name}」" if len(job.step2_entities) < old_len else f"未找到实体「{name}」"

    elif op == "add_relation":
        # 同步写入 step2_relations 与 step3_relations，避免两个历史兼容字段不一致
        if not job.step2_relations:
            job.step2_relations = []
        job.step2_relations.append(target)
        if not job.step3_relations:
            job.step3_relations = []
        job.step3_relations.append(target)
        return f"已新增关系「{target.get('source', '')} → {target.get('target', '')}」"

    elif op == "delete_relation":
        src = target.get("source", "")
        tgt = target.get("target", "")
        rel_type = target.get("relation_type", "")
        removed_any = False
        # 同时从 step2_relations 与 step3_relations 删除，避免旧字段仍残留被删关系
        for field in ("step2_relations", "step3_relations"):
            source = getattr(job, field) or []
            keep = []
            for r in source:
                if _normalize_name(r.get("source", "")) == _normalize_name(src) and _normalize_name(r.get("target", "")) == _normalize_name(tgt):
                    # 若用户指明了关系类型，需同时匹配才删除（精确删除）
                    if rel_type and _normalize_name(r.get("relation_type", "")) != _normalize_name(rel_type):
                        keep.append(r)
                        continue
                    continue
                keep.append(r)
            if len(keep) < len(source):
                removed_any = True
            setattr(job, field, keep)
        return f"已删除关系「{src} → {tgt}」" if removed_any else f"未找到关系「{src} → {tgt}」"

    elif op == "add_et_relation":
        if not job.step1_entity_type_relations:
            job.step1_entity_type_relations = []
        job.step1_entity_type_relations.append(target)
        return f"已新增类型间关系「{target.get('source_entity_type_name', '')} → {target.get('target_entity_type_name', '')}」"

    elif op == "delete_et_relation":
        src = target.get("source_entity_type_name", "")
        tgt = target.get("target_entity_type_name", "")
        source = job.step1_entity_type_relations or []
        old_len = len(source)
        job.step1_entity_type_relations = [
            r for r in source
            if not (_normalize_name(r.get("source_entity_type_name", "")) == _normalize_name(src)
                    and _normalize_name(r.get("target_entity_type_name", "")) == _normalize_name(tgt))
        ]
        return f"已删除类型间关系「{src} → {tgt}」" if len(job.step1_entity_type_relations) < old_len else f"未找到类型间关系「{src} → {tgt}」"

    return f"未知编辑操作：{op}"


# ── AI 构建聊天：SSE 接口 ──

# 重新提取类关键词：命中时不做状态机校正，保留用户「重跑」语义
_RE_EXTRACT_KEYWORDS = ("重新提取", "再次提取", "重新生成", "再提取一次", "重提", "重新开始提取")

# 重新解析类关键词：命中时跳过「已解析免重跑」逻辑，保留用户「重跑」语义
_RE_PARSE_KEYWORDS = ("重新解析", "再次解析", "重新分析", "重新读取文档", "换一篇", "换一个文档")


def _normalize_intent(job, intent: str, user_message: str) -> str:
    """基于任务状态的意图校正（LLM 分类结果 + 确定性状态机规则）。

    LLM 对「确认/继续/下一步」类模糊表述的分类受上下文影响不稳定，
    曾出现 step1 已完成未确认时，「符合预期，确认进行下一步」被反复
    分到 extract_type，导致流程原地打转、永远进不了实体提取。

    规则：LLM 只需识别出「用户想推进」，具体推进到哪个阶段由构建
    状态机按已产出的结果确定性推导，保证流程单向前进不回跳：

    - extract_type 但 step1 已有结果未确认 → extract_entity（确认即推进）
    - extract_entity 但 step1 无结果 → extract_type（顺序不可跳过）
    - verify 但 step2 无结果 → 回退到最近的未完成阶段
    - complete 但验证未产出 → 回退到最近的未完成阶段

    用户消息含「重新提取」类关键词时不校正（保留重跑语义）。
    """
    if any(kw in user_message for kw in _RE_EXTRACT_KEYWORDS):
        return intent

    has_step1 = bool(job.step1_entity_types or job.step1_concepts)
    has_step2 = bool(job.step2_entities)
    has_verify = bool(job.step3_verification or job.step4_verification)

    if intent == "extract_type" and has_step1 and not job.step1_confirmed:
        return "extract_entity"
    if intent == "extract_entity" and not has_step1:
        return "extract_type"
    if intent == "verify" and not has_step2:
        return "extract_entity" if has_step1 else "extract_type"
    if intent == "complete" and not has_verify:
        if job.step3_confirmed:
            return intent  # 验证已确认（旧任务无验证结果字段），允许收尾
        return "verify" if has_step2 else ("extract_entity" if has_step1 else "extract_type")
    return intent


@app.post("/ontology/build/{job_id}/chat")
async def build_chat(job_id: str, request: Request):
    """AI 构建聊天接口（SSE）。

    接收用户消息，意图分类后执行对应操作，流式返回 AI 回复 + 状态更新 + 图谱数据。

    SSE 事件：
    - chat_status: 状态通知（classifying / executing / replying）
    - chat_reply: AI 自然语言回复
    - state_update: 当前状态变更（下拉面板 + 图谱同源）
    - graph_update: 图谱数据
    - chat_error: 错误信息
    - chat_done: 结束标记
    """
    body = await request.json()
    user_message = (body.get("message") or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    job = _get_job_or_404(job_id)
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    # 初始化 chat_history（兼容旧任务）
    history = job.chat_history or []
    if not job.chat_history:
        job.chat_history = []

    async def chat_generator():
        try:
            # 1. 意图分类（LLM 结果 + 确定性状态机校正，保证流程按已产出结果单向推进）
            yield _sse_format("chat_status", {"status": "classifying", "message": "正在理解你的意图..."})
            # 意图分类/回复生成为同步 LLM 调用，放线程池执行：
            # 直接在事件循环内调用会阻塞整个服务（SSE 心跳停滞、/progress 轮询堆积），
            # 表现为页面「卡住后事件一次性涌出」
            intent_result = await asyncio.to_thread(
                agent_orchestrator.classify_intent, job, history, user_message
            )
            raw_intent = intent_result["intent"]
            intent = _normalize_intent(job, raw_intent, user_message)
            if intent != raw_intent:
                logger.info(f"[{job_id}] 意图状态机校正: {raw_intent} → {intent}")
            logger.info(f"[{job_id}] 聊天意图: {intent}")

            # 2. 执行操作
            yield _sse_format("chat_status", {"status": "executing", "message": f"正在执行「{intent}」..."})
            tool_summary = ""
            try:
                if intent == "parse":
                    tool_summary = await _chat_parse(job_id, user_message)
                elif intent == "extract_type":
                    tool_summary = await _chat_extract_type(job_id, user_message)
                elif intent == "extract_entity":
                    tool_summary = await _chat_extract_entity(job_id, user_message)
                elif intent == "verify":
                    tool_summary = await _chat_verify(job_id)
                elif intent == "complete":
                    tool_summary = await _chat_complete(job_id)
                elif intent == "edit":
                    tool_summary = await _chat_edit(job_id, user_message)
                else:
                    tool_summary = intent_result.get("summary", "")
            except Exception as e:
                logger.error(f"[{job_id}] 聊天操作执行失败: {e}")
                yield _sse_format("chat_error", {"error": str(e)})
                return

            # 3. 生成自然语言回复（同步 LLM 调用，放线程池避免阻塞事件循环）
            yield _sse_format("chat_status", {"status": "replying", "message": "正在生成回复..."})
            reply = await asyncio.to_thread(
                agent_orchestrator.generate_reply, job, history, user_message, tool_summary
            )

            # 4. 保存聊天历史
            # 本轮若启动了后台任务（running_step>=0），回复消息携带任务标记，
            # 前端在该消息下方渲染常显状态标签（运行中→完成/失败）
            task_meta = None
            if job.running_step is not None and job.running_step >= 0:
                task_meta = {"stage": job.running_step, "status": "running"}
            now = datetime.now().isoformat()
            job.chat_history.append({"role": "user", "content": user_message, "created_at": now})
            assistant_msg = {"role": "assistant", "content": reply, "intent": intent, "created_at": now}
            if task_meta:
                assistant_msg["task"] = task_meta
            job.chat_history.append(assistant_msg)

            # 5. 滚动摘要：超过保留轮数且达到阈值时，压缩较早历史到 history_summary
            keep_msgs = config.CHAT_HISTORY_KEEP_RECENT * 2
            if len(job.chat_history) > keep_msgs and len(job.chat_history) >= config.CHAT_HISTORY_SUMMARY_THRESHOLD:
                older = job.chat_history[:len(job.chat_history) - keep_msgs]
                recent = job.chat_history[len(job.chat_history) - keep_msgs:]
                summary = await asyncio.to_thread(
                    agent_orchestrator.summarize_history, older, old_summary=getattr(job, "history_summary", "")
                )
                if summary:
                    job.history_summary = summary
                job.chat_history = recent

            save_build_job(job_id)
            save_build_jobs_index()

            # 6. 先推送状态与图谱（保证前端生成折叠载荷时已拿到最新状态），再推送回复
            yield _sse_format("state_update", _get_current_state(job_id))

            graph = _build_stage_graph(job, job.running_step if job.running_step >= 0 else 4) if not job.ontology_id else _graph_data(job.ontology_id)
            yield _sse_format("graph_update", graph)

            yield _sse_format("chat_reply", {"reply": reply, "intent": intent, "task": task_meta})

            yield _sse_format("chat_done", {"status": "done"})
        except Exception as e:
            logger.error(f"[{job_id}] 聊天 SSE 异常: {e}")
            yield _sse_format("chat_error", {"error": str(e)})

    return StreamingResponse(chat_generator(), media_type="text/event-stream")


# ── AI 构建聊天：聊天历史 ──

@app.get("/ontology/build/{job_id}/history")
async def build_chat_history(job_id: str):
    """获取聊天历史（用于刷新恢复）。"""
    job = _get_job_or_404(job_id)
    # 兼容修复：早期版本可能重复推送文档摘要（首次解析+重解析各一次），
    # 返回前去重，只保留第一条 doc_summary 消息，刷新后不再显示重复
    seen_summary = False
    deduped = []
    for msg in job.chat_history or []:
        if isinstance(msg, dict) and msg.get("intent") == "doc_summary":
            if seen_summary:
                continue
            seen_summary = True
        deduped.append(msg)

    # 对账：服务重启等异常中断的任务，消息上的任务标签可能永远停留在 running；
    # 任务空闲时按各阶段是否已产出结果翻成终态，避免刷新后标签一直转圈
    if job.running_step == -1:
        stage_has_output = {
            0: bool(job.meta_entity_types or job.step0_summary),
            1: bool(job.step1_entity_types or job.step1_concepts),
            2: bool(job.step2_entities),
            3: bool(job.step3_verification or job.step4_verification),
        }
        reconciled = False
        for m in deduped:
            t = m.get("task") if isinstance(m, dict) else None
            if t and t.get("status") == "running":
                t["status"] = "done" if stage_has_output.get(t.get("stage")) else "failed"
                t["result_summary"] = "任务已结束（刷新时自动对账）"
                reconciled = True
        if reconciled:
            # deduped 内元素与 job.chat_history 同引用，翻状态即改库内数据，落盘自愈
            async with build_lock:
                save_build_job(job_id)
            logger.info(f"[{job_id}] 聊天历史任务标签对账完成（running → 终态）")
    return {
        "success": True,
        "data": {
            "chat_history": deduped,
            "state": _get_current_state(job_id),
        }
    }


# ── AI 构建聊天：编辑接口 ──

@app.post("/ontology/build/{job_id}/edit")
async def build_edit(job_id: str, request: Request):
    """增量编辑当前状态（即时写回，step3 确认时才真正落库）。"""
    body = await request.json()
    operation = body.get("operation", {})
    if not operation:
        raise HTTPException(status_code=400, detail="缺少编辑操作")

    job = _get_job_or_404(job_id)
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    result = _apply_edit_operation(job, operation)
    job.update_time = datetime.now()
    save_build_job(job_id)
    save_build_jobs_index()
    return {"success": True, "message": result, "data": _get_current_state(job_id)}


# ── AI 构建聊天：从已完成本体开启对话 ──

@app.post("/ontology/build/from-ontology")
async def build_from_ontology(request: Request):
    """从已完成本体开启 AI 构建对话任务。

    读取正式本体数据初始化当前状态（step1-3 预填已确认），
    chat_history 回填该本体全部历史，保证上下文连续。
    """
    body = await request.json()
    ontology_id = (body.get("ontology_id") or "").strip()
    if not ontology_id:
        raise HTTPException(status_code=400, detail="缺少 ontology_id")

    ont = ontologies_db.get(ontology_id)
    if not ont:
        raise HTTPException(status_code=404, detail="本体不存在")

    now = datetime.now()
    job_id = f"job_{uuid.uuid4().hex[:8]}"

    # 从正式本体读取数据填充当前状态
    ets = entity_types_db.get(ontology_id, [])
    step1_types = []
    for et in ets:
        item = {
            "name": et.name,
            "description": et.description or "",
            "color": et.color,
            "property_schema": [
                {"name": ps.name, "category": ps.category, "data_type": ps.data_type,
                 "unit": ps.unit or "", "required": ps.required, "description": ps.description or ""}
                for ps in (et.property_schema or [])
            ],
            "parent_entity_type_name": _find_parent_entity_type_name(et, ets),
        }
        step1_types.append(item)

    et_rels = entity_type_relations_db.get(ontology_id, [])
    step1_et_rels = []
    for etr in et_rels:
        src_name = _find_entity_type_name(etr.source_entity_type_id, ets)
        tgt_name = _find_entity_type_name(etr.target_entity_type_id, ets)
        if src_name and tgt_name:
            step1_et_rels.append({
                "source_entity_type_name": src_name,
                "target_entity_type_name": tgt_name,
                "relation_type": etr.relation_type,
                "description": etr.description or "",
            })

    ents = entities_db.get(ontology_id, [])
    step2_entities = []
    for ent in ents:
        inst_name = _find_entity_type_name(ent.instance_of, ets) if ent.instance_of else ""
        step2_entities.append({
            "name": ent.name,
            "instance_of": inst_name,
            "properties": [{"name": p.name, "value": p.value} for p in (ent.properties or [])],
        })

    rels = relations_db.get(ontology_id, [])
    ent_map = {e.id: e.name for e in ents}
    step2_relations = []
    for rel in rels:
        src_name = ent_map.get(rel.source_id, "")
        tgt_name = ent_map.get(rel.target_id, "")
        if src_name and tgt_name:
            step2_relations.append({
                "source": src_name, "target": tgt_name,
                "relation_type": rel.relation_type,
            })

    # 查找该本体的构建任务历史，回填 chat_history
    chat_history = []
    for j in build_jobs_db.values():
        if j.ontology_id == ontology_id and j.chat_history:
            chat_history = list(j.chat_history)
            break

    job = BuildJob(
        id=job_id, name=f"再编辑 - {ont.name}", description=ont.description or "",
        build_type="ai_build_reopen",
        meta_confirmed=True, step1_confirmed=True, step2_confirmed=True, step3_confirmed=True,
        step1_entity_types=step1_types, step1_entity_type_relations=step1_et_rels,
        step2_entities=step2_entities, step2_relations=step2_relations,
        ontology_id=ontology_id,
        chat_history=chat_history,
        create_time=now, update_time=now,
        progress=100, progress_message="从正式本体加载完成",
        status="completed",
        step1_concepts=[],  # 兼容旧字段
    )
    build_jobs_db[job_id] = job
    save_build_job(job_id)
    save_build_jobs_index()

    return {"success": True, "data": {"job_id": job_id, "state": _get_current_state(job_id)}}


def _find_parent_entity_type_name(et, all_ets) -> str:
    """从所有 EntityType 中查找父类型名称。"""
    if not et.parent_entity_type_id:
        return ""
    for p in all_ets:
        if p.id == et.parent_entity_type_id:
            return p.name
    return ""


def _find_entity_type_name(type_id, ets) -> str:
    """从 EntityType 列表中按 ID 查找名称。"""
    for et in ets:
        if et.id == type_id:
            return et.name
    return ""


# ── AI 构建聊天：各意图处理函数 ──

async def _background_reparse_meta(job_id: str) -> None:
    """后台任务：聊天触发的文档重新解析（阶段 0）。

    与上传后的首次解析（_background_parse_document）不同：默认只对已有 source_text
    重新调用 LLM 推荐本体模型；若检测到 source_text 是历史截断文本，则先恢复全文。
    """
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    # 兼容修复：上传接口历史缺陷曾把 source_text 存成截断文本（仅前 ~1.2 万字），
    # 导致分批提取只覆盖文档开头、后半部分全部丢失。
    # 源文件仍在且长度小于 char_count 时，重新提取全文并清除基于旧文本的摘要/规划，
    # 使摘要与分批规划基于完整文档重新生成。
    try:
        _src_path = os.path.join(BUILD_JOBS_DIR, f'{job_id}_source')
        if (job.source_text and job.char_count > 0
                and len(job.source_text) < job.char_count
                and os.path.exists(_src_path)):
            _full = extract_text(_src_path, job.source_filename)
            if len(_full) > len(job.source_text):
                job.source_text = _full
                job.char_count = len(_full)
                # 旧摘要/规划基于截断文本生成，作废待重新生成
                job.step0_summary = ""
                job.step0_suggestion = ""
                job.step1_plan = []
                job.step1_hierarchy_hint = ""
                job.update_time = datetime.now()
                save_build_job(job_id)
                save_build_jobs_index()
                logger.info(
                    f"[{job_id}] 检测到 source_text 为截断文本（{len(job.source_text)}→{len(_full)} 字符），"
                    f"已重新提取全文"
                )
    except Exception as _e:
        logger.warning(f"[{job_id}] 重新提取全文失败，继续使用现有文本: {_e}")
    try:
        _mark_stage_started(job_id, 0)
        # 文案不带「重新」：进入本函数时阶段 0 产出必为空（首次解析或重跑前已清空）
        _set_job_progress(job_id, 0, 30, "正在调用AI解析文档...")
        from doc_parser import truncate_for_llm
        from build_prompts import build_meta_messages
        trunc = truncate_for_llm(job.source_text)
        messages = build_meta_messages(trunc, job.name)
        result = await _llm_json_async(messages, temperature=0.3,
                                       max_tokens=config.LLM_MAX_TOKENS,
                                       thinking_type=config.get_llm_params("step0")[1])
        async with build_lock:
            job.meta_entity_types = result.get("entity_types", [])
            job.meta_relation_types = result.get("relation_types", [])
            job.meta_confirmed = False
            job.update_time = datetime.now()
            save_build_job(job_id)
        save_build_jobs_index()
        # 重新生成文档摘要 + 构建规划（失败静默降级）
        await _generate_doc_summary_and_plan(job_id)
        # 联动聊天：翻任务标签为完成（摘要消息已由上方推送，不再追加完成回复）
        await _finalize_task_chat(
            job_id, 0, True,
            f"文档解析完成，识别到 {len(job.meta_entity_types)} 个实体类型候选",
            no_message=True,
        )
        _set_job_progress(
            job_id, -1, 100,
            f"文档解析完成，识别到 {len(job.meta_entity_types)} 个实体类型候选"
        )
        _mark_stage_finished(job_id, 0)
        _emit_event(job_id, "parse_done", {
            "step": 0,
            "meta_entity_types": job.meta_entity_types,
            "meta_relation_types": job.meta_relation_types,
            "planned_step1_batches": len(job.step1_plan) if job.step1_plan else 0,
        })
    except Exception as e:
        logger.exception(f"[{job_id}] 后台文档重新解析失败: {e}")
        _mark_stage_finished(job_id, 0, success=False)
        _set_job_progress(job_id, -1, 0, "文档解析异常")
        await _finalize_task_chat(job_id, 0, False, f"文档解析异常: {str(e)[:200]}")
        _emit_event(job_id, "error", {"step": 0, "message": str(e)})
    finally:
        _background_tasks.pop(job_id, None)


async def _chat_parse(job_id: str, user_message: str = "") -> str:
    """处理文档解析意图。

    已有解析产出（meta 候选/摘要/构建规划任一非空）时默认文档能正确解析，
    不重复解析同一篇文档：直接同步状态并引导用户进入下一步；
    仅当用户消息含「重新解析」类关键词时清空旧产出后完整重跑。
    """
    job = _get_job_or_404(job_id)
    if not job.source_text:
        return "没有可解析的文档内容，请先上传文档"
    # 解析产出任一非空即视为已解析完成（meta 候选为解析必产出的权威标志）
    already_done = bool(
        job.meta_entity_types or job.meta_relation_types
        or job.step0_summary or job.step0_suggestion or job.step1_plan
    )
    wants_reparse = any(kw in user_message for kw in _RE_PARSE_KEYWORDS)
    if already_done and not wants_reparse:
        # 已解析且用户无重跑意愿：不启动后台任务，避免重复解析同一篇文档；
        # 同步进度为完成态并补推 parse_done（刷新前端面板），按构建进度引导下一步
        _set_job_progress(job_id, -1, 100, "文档解析已完成")
        _mark_stage_finished(job_id, 0)  # 自愈：上一轮若中断残留 running，此处收敛为 done
        _emit_event(job_id, "parse_done", {
            "step": 0,
            "meta_entity_types": job.meta_entity_types,
            "meta_relation_types": job.meta_relation_types,
            "planned_step1_batches": len(job.step1_plan) if job.step1_plan else 0,
        })
        logger.info(f"[{job_id}] 文档已解析过，跳过重复解析直接引导下一步")
        # 按当前构建进度推导下一步（仅提示，不自动推进）
        next_hint = _next_step_hint(job)
        return (
            f"文档此前已解析完成（识别到 {len(job.meta_entity_types)} 个实体类型候选），"
            f"无需重复解析。{next_hint}；如确需重新解析，请说「重新解析文档」。"
        )
    if already_done and wants_reparse:
        # 用户明确要求重新解析：清空阶段 0 旧产出，让后台任务完整重跑
        async with build_lock:
            job.meta_entity_types = []
            job.meta_relation_types = []
            job.meta_confirmed = False
            job.step0_summary = ""
            job.step0_suggestion = ""
            job.step1_plan = []
            job.step1_hierarchy_hint = ""
            job.update_time = datetime.now()
            save_build_job(job_id)
        logger.info(f"[{job_id}] 用户要求重新解析，已清空阶段 0 旧产出")
    _set_job_progress(job_id, 0, 10, "正在重新解析文档..." if already_done else "正在解析文档...")
    task = asyncio.create_task(_background_reparse_meta(job_id))
    _background_tasks[job_id] = task
    return "文档解析已在后台开始，请稍候查看结果"


def _next_step_hint(job) -> str:
    """按当前构建进度推导下一步引导（仅提示，不自动推进）。"""
    ets = job.step1_entity_types or job.step1_concepts or []
    if not ets and not job.step1_confirmed:
        return "下一步请确认候选清单，然后开始提取实体类型（可直接说「提取实体类型」）"
    if not job.step1_confirmed:
        return f"实体类型已提取（共 {len(ets)} 个），下一步请确认类型清单后提取实体"
    if not job.step2_entities and not job.step2_confirmed:
        return "下一步请提取实体（可直接说「提取实体」）"
    if not job.step2_confirmed:
        return f"实体已提取（共 {len(job.step2_entities)} 个），下一步请确认实体清单后进行验证"
    if not (job.step3_verification or job.step4_verification) and not job.step3_confirmed:
        return "下一步请进行分析验证（可直接说「开始验证」）"
    return "验证已完成，下一步请确认验证结果并完成构建（可直接说「完成构建」）"


async def _finalize_task_chat(job_id: str, stage: int, success: bool,
                              result_summary: str, no_message: bool = False) -> None:
    """后台任务收尾（聊天联动）：翻消息上的任务标签 + 推送完成引导回复。

    - 在 chat_history 中找到该 stage 最后一条 running 标签消息，翻成 done/failed（含结果摘要）
    - no_message=False 时用 LLM 生成「当前状态 + 下一步建议」回复，追加进 chat_history
      并通过 chat_message 事件推送（message 字段）；LLM 失败降级为结果摘要模板
    - no_message=True 时不追加回复（阶段 0 的完成回复即文档摘要消息，避免重复）
    - 幂等：标签已是终态时只按需补推消息，不重复翻转
    """
    job = build_jobs_db.get(job_id)
    if not job:
        return
    status = "done" if success else "failed"
    # 找该 stage 最后一条带任务标签的消息（通常就是启动该任务的那条 AI 回复）
    target_idx = None
    for i in range(len(job.chat_history) - 1, -1, -1):
        m = job.chat_history[i]
        t = m.get("task") if isinstance(m, dict) else None
        if t and t.get("stage") == stage:
            target_idx = i
            break
    if target_idx is not None and job.chat_history[target_idx]["task"].get("status") == "running":
        job.chat_history[target_idx]["task"].update({
            "status": status,
            "result_summary": result_summary,
        })

    message_payload = None
    if not no_message:
        # 失败时引导续跑/重跑，成功时按构建进度推导下一步
        next_hint = (
            _next_step_hint(job) if success
            else "可回复「继续提取」从失败批次续跑（已成功批次不会重复处理），或回复「重新提取」完整重跑"
        )
        reply = ""
        try:
            messages = agent_prompts.build_stage_done_messages(
                job, stage, result_summary, next_hint
            )
            max_tokens, thinking = config.get_chat_llm_params("chat")
            # LLM 调用放线程池，避免阻塞事件循环（后台任务与 SSE 共用事件循环）
            reply = await asyncio.to_thread(
                call_llm, messages, temperature=0.5,
                max_tokens=max_tokens, thinking_type=thinking,
            )
        except Exception as e:
            logger.warning(f"[{job_id}] 阶段 {stage} 完成回复生成失败，降级为模板: {e}")
        if not reply:
            reply = f"{result_summary}。{next_hint}。"
        message_payload = {
            "role": "assistant",
            "content": reply,
            "intent": f"stage{stage}_done",
            "created_at": datetime.now().isoformat(),
        }

    async with build_lock:
        if message_payload is not None:
            job.chat_history.append(message_payload)
        job.update_time = datetime.now()
        save_build_job(job_id)
    save_build_jobs_index()
    _emit_event(job_id, "chat_message", {
        "message": message_payload,  # None 时前端仅应用 task_update 翻标签
        "task_update": {"stage": stage, "status": status, "result_summary": result_summary},
    })
    logger.info(f"[{job_id}] 阶段 {stage} 任务收尾（{status}），已联动聊天标签与完成回复")


async def _chat_extract_type(job_id: str, user_message: str = "") -> str:
    """处理实体类型提取意图。"""
    job = _get_job_or_404(job_id)
    # 如果文档解析已提取但未确认，自动确认
    if not job.meta_confirmed:
        if not job.source_text:
            return "请先上传文档进行解析"
        job.meta_confirmed = True
        job.update_time = datetime.now()
        save_build_job(job_id)
        save_build_jobs_index()
        logger.info(f"[{job_id}] 自动确认文档解析")
    existing_types = job.step1_entity_types or job.step1_concepts or []
    already_done = (bool(existing_types)
                    and job.step1_batches_done >= job.step1_batches_total
                    and job.step1_failed_batch < 0)
    wants_reextract = any(kw in user_message for kw in _RE_EXTRACT_KEYWORDS)
    if already_done and not wants_reextract:
        # 已有完整提取结果且无失败且用户无重跑意愿：无需启动后台任务
        # （防重复跑分支本来也不会重提取），直接同步状态并如实告知，
        # 避免「已在后台开始」话术与秒完成的实际不符，用户干等通知却永远等不到
        _set_job_progress(job_id, -1, 100, "本体提取已完成")
        _mark_stage_finished(job_id, 1)  # 自愈：上一轮若中断残留 running，此处收敛为 done
        _emit_event(job_id, "step_done", {
            "step": 1,
            "entity_types": existing_types,
            "entity_type_relations": job.step1_entity_type_relations or [],
            "concepts": existing_types,  # 兼容旧前端
            "total": len(existing_types)
        })
        logger.info(f"[{job_id}] 实体类型已有完整结果（{len(existing_types)} 个），跳过重复提取直接展示")
        return (
            f"实体类型此前已提取完成（共 {len(existing_types)} 个类型），已直接展示在结果面板中，"
            f"无需重新提取。请确认后进入实体提取阶段。"
        )
    if already_done and wants_reextract:
        # 用户明确要求重新提取：清空 step1 旧结果，让后台任务完整重跑
        # （不清空会被防重复跑分支秒结束，等于没重提）
        async with build_lock:
            job.step1_entity_types = []
            job.step1_concepts = []
            job.step1_entity_type_relations = []
            job.step1_batch_results = []
            job.step1_batch_relations_results = []
            job.step1_batches_total = 0
            job.step1_batches_done = 0
            job.step1_failed_batch = -1
            job.step1_failed_reason = None
            job.step1_cross_batch_done = False
            job.step1_cross_batch_relations = []
            job.update_time = datetime.now()
            save_build_job(job_id)
        logger.info(f"[{job_id}] 用户要求重新提取，已清空 step1 旧结果（{len(existing_types)} 个类型）")
    _set_job_progress(job_id, 1, 20, "正在提取实体类型...")
    task = asyncio.create_task(_background_extract_entity_types(job_id))
    _background_tasks[job_id] = task
    # 如实写明本轮启动的阶段（step1 类型层），供 LLM 回复对齐本轮动作
    return (
        "本轮动作：已启动【实体类型提取】阶段（step1，类型层，提取抽象类型定义而非具体实例）。"
        "提取完成后请在结果面板确认类型清单，确认后进入实体+关系提取阶段。"
    )


async def _chat_extract_entity(job_id: str, user_message: str = "") -> str:
    """处理实体提取意图。"""
    job = _get_job_or_404(job_id)
    # 如果实体类型已提取但未确认，自动确认（用户说"确认"后进入此意图）
    if not job.step1_confirmed:
        ets = job.step1_entity_types or job.step1_concepts or []
        if not ets:
            return "请先提取实体类型"
        job.step1_confirmed = True
        job.update_time = datetime.now()
        save_build_job(job_id)
        save_build_jobs_index()
        logger.info(f"[{job_id}] 自动确认 step1（实体类型 {len(ets)} 个）")
    existing_entities = job.step2_entities or []
    already_done = (bool(existing_entities)
                    and job.step2_batches_done >= job.step2_batches_total
                    and job.step2_failed_batch < 0)
    wants_reextract = any(kw in user_message for kw in _RE_EXTRACT_KEYWORDS)
    if already_done and not wants_reextract:
        # 已有完整提取结果且无失败且用户无重跑意愿：不启动后台任务
        # （防重复跑分支会秒结束，任务状态卡片一闪而逝且告知话术与实际不符），
        # 直接同步状态并如实告知
        _set_job_progress(job_id, -1, 100, "实体提取已完成")
        _mark_stage_finished(job_id, 2)  # 自愈：上一轮若中断残留 running，此处收敛为 done
        _emit_event(job_id, "step_done", {
            "step": 2,
            "entities": existing_entities,
            "total": len(existing_entities)
        })
        logger.info(f"[{job_id}] 实体已有完整结果（{len(existing_entities)} 个），跳过重复提取直接展示")
        return (
            f"实体此前已提取完成（共 {len(existing_entities)} 个），已直接展示在结果面板中，"
            f"无需重新提取。请确认后进入验证阶段。"
        )
    if already_done and wants_reextract:
        # 用户明确要求重新提取：清空 step2 旧结果及依赖实体的 step3 验证，
        # 让后台任务完整重跑（不清空会被防重复跑分支秒结束，等于没重提）
        async with build_lock:
            job.step2_entities = []
            job.step2_relations = []
            job.step3_relations = []  # 兼容旧字段
            job.step2_confirmed = False
            job.step2_batch_results = []
            job.step2_batch_relations_results = []
            job.step2_batches_total = 0
            job.step2_batches_done = 0
            job.step2_failed_batch = -1
            job.step2_failed_reason = None
            job.step3_verification = None
            job.step3_confirmed = False
            job.step4_verification = None  # 兼容旧字段
            job.step4_confirmed = False
            job.update_time = datetime.now()
            save_build_job(job_id)
        logger.info(f"[{job_id}] 用户要求重新提取，已清空 step2 旧结果（{len(existing_entities)} 个实体）")
    _set_job_progress(job_id, 2, 20, "正在提取实体...")
    task = asyncio.create_task(_background_extract_entities(job_id))
    _background_tasks[job_id] = task
    # 回复模板如实写明「确认了什么 + 启动了哪个阶段」，供 LLM 生成回复时对齐本轮动作，
    # 避免回复照搬历史中 step1 的旧话术（用户误以为重新提取实体类型）
    type_count = len(job.step1_entity_types or job.step1_concepts or [])
    return (
        f"本轮动作：1) 已确认实体类型清单（共 {type_count} 个类型，step1 完成）；"
        f"2) 已启动【实体+关系提取】阶段（step2，实例层，非实体类型提取）。"
        f"提取完成后请在结果面板确认实体与关系清单，确认后进入验证阶段。"
    )


async def _chat_verify(job_id: str) -> str:
    """处理验证意图。"""
    job = _get_job_or_404(job_id)
    # 实体+关系已提取但未确认时，自动确认（与 _chat_extract_type/_chat_extract_entity 的自动确认保持一致），
    # 避免用户说「验证」却被「请先确认实体提取结果」拦截，导致回复与实际动作不一致。
    if not job.step2_confirmed:
        ents = job.step2_entities or []
        if not ents:
            return "实体清单为空，请先提取实体"
        job.step2_confirmed = True
        job.step = max(job.step, 3)
        job.update_time = datetime.now()
        save_build_job(job_id)
        save_build_jobs_index()
        logger.info(f"[{job_id}] 自动确认 step2（实体 {len(ents)} 个）")
    _set_job_progress(job_id, 3, 20, "正在验证...")
    task = asyncio.create_task(_background_verify_and_report(job_id))
    _background_tasks[job_id] = task
    return "验证已在后台开始，请稍候查看结果"


async def _chat_complete(job_id: str) -> str:
    """处理完成构建意图。"""
    job = _get_job_or_404(job_id)
    # 验证已完成但未确认时，自动确认（用户说「完成构建/接受存疑完成构建」即视为接受验证结果），
    # 再生成正式本体，避免被「请先完成验证」拦截导致无法收尾。
    if not job.step3_confirmed:
        if not job.step3_verification and not job.step4_verification:
            return "请先完成验证"
        job.step3_confirmed = True
        job.step4_confirmed = True  # 兼容旧字段
        job.update_time = datetime.now()
        save_build_job(job_id)
        save_build_jobs_index()
        logger.info(f"[{job_id}] 自动确认 step3（验证完成，接受存疑项）")

    ent_count = len(job.step2_entities or [])
    rel_count = len(job.step3_relations or job.step2_relations or [])
    oid = _generate_formal_ontology(job_id, target_ontology_id=job.ontology_id)
    job.ontology_id = oid
    job.status = "completed"
    job.step = 4
    job.running_step = -1
    job.progress = 100
    job.progress_message = f"本体生成成功！共 {ent_count} 个实体，{rel_count} 条关系"
    job.error_message = None
    job.update_time = datetime.now()
    save_build_job(job_id)
    save_build_jobs_index()
    return f"构建完成！正式本体已生成，ID: {oid}"


async def _chat_edit(job_id: str, user_message: str) -> str:
    """处理编辑意图：用 LLM 将用户自然语言转为结构化编辑操作。"""
    job = _get_job_or_404(job_id)
    state = _get_current_state(job_id)
    # 构造编辑 prompts
    from agent.prompts import build_state_summary, build_context_history
    system = (
        "你是本体构建编辑助手。根据用户输入、当前状态和最近对话，生成结构化编辑操作。\n"
        "重要：编辑操作随时可执行，不受「阶段是否确认」限制——用户要求删除/修改某条关系、实体或实体类型时，"
        "只要当前状态里存在对应目标，就立即生成对应操作，不要因为阶段未确认而拒绝。\n"
        "「恢复/撤销上一个删除」等表述，请结合「最近对话」判断之前删除的是哪条关系/实体，"
        "生成对应的 add_relation（或 add_entity）来恢复；用户说「仅删除X」时，只生成删除 X 的操作，不要误删其它。\n"
        "当用户要求「仅保留 A/B/C（及其子类型），其余实体类型全部删除」这类白名单保留意图时，"
        "务必使用 keep_only_entity_types 操作，target 为 {\"keep_names\": [\"A\", \"B\", \"C\"]}，"
        "只列出要保留的类型名，不要逐个生成 delete_entity_type。\n"
        "只返回 JSON 数组，每个元素一个操作：\n"
        '{"op": "add_entity_type|update_entity_type|delete_entity_type|keep_only_entity_types|add_entity|update_entity|delete_entity|add_relation|delete_relation|add_et_relation|delete_et_relation", "target": {...}}\n'
        "keep_only_entity_types 的 target 格式：{\"keep_names\": [\"要保留的类型名\", ...]}。\n"
        "删除关系的 target 格式：{\"source\": \"源实体名\", \"target\": \"目标实体名\"}，"
        "若用户指明了关系类型，可附 \"relation_type\": \"类型名\" 用于精确匹配。\n"
        "新增关系的 target 格式：{\"source\": \"源实体名\", \"target\": \"目标实体名\", \"relation_type\": \"类型名\"}。\n"
        "不要任何解释或 markdown。如果无法确定编辑意图，返回空数组 []。"
    )
    history_text = build_context_history(job.chat_history or [], getattr(job, "history_summary", ""))
    # 编辑判断需要完整类型名清单（build_state_summary 截断前 30 个），
    # 此处额外注入全量类型名，确保「仅保留X其余删除」能拿到准确的保留名单、不漏删。
    full_types = job.step1_entity_types or job.step1_concepts or []
    full_type_names = [
        et.get("name", "") for et in full_types
        if isinstance(et, dict) and et.get("name")
    ]
    user = (
        f"当前状态：\n{build_state_summary(job)}\n\n"
        f"完整实体类型清单（共 {len(full_type_names)} 个，用于准确判断保留/删除，勿遗漏）：\n"
        f"{'、'.join(full_type_names)}\n\n"
        f"最近对话：\n{history_text or '（无）'}\n\n"
        f"用户输入：{user_message}\n\n"
        f"请生成编辑操作 JSON 数组。"
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    max_tokens, thinking = config.get_chat_llm_params("edit")
    try:
        ops = call_llm_json(messages, temperature=0.2, max_tokens=max_tokens, thinking_type=thinking)
    except Exception as e:
        return f"编辑解析失败：{e}"

    if not ops or not isinstance(ops, list):
        return "无法理解你的编辑意图，请换个方式描述"

    results = []
    for op in ops:
        result = _apply_edit_operation(job, op)
        results.append(result)

    job.update_time = datetime.now()
    save_build_job(job_id)
    return "；".join(results)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10256, log_config=None)
