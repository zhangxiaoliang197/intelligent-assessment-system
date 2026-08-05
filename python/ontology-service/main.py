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


# ---------- 数据模型 ----------
class EntityType(BaseModel):
    """实体类型定义。"""
    name: str
    color: Optional[str] = None


class RelationType(BaseModel):
    """关系类型定义。"""
    name: str


class Entity(BaseModel):
    """实体（概念节点）。"""
    id: str
    ontology_id: str
    name: str
    type: str
    properties: Dict[str, str] = Field(default_factory=dict)
    # B 阶段数据绑定：实体绑定到具体数据字段（ass_field_annotation）
    # 结构示例: {"field_id":"...", "dataset_id":"...", "table_name":"...", "column_name":"..."}
    bindings: Dict[str, str] = Field(default_factory=dict)
    create_time: datetime
    update_time: datetime


class Relation(BaseModel):
    """关系（概念之间的有向边）。"""
    id: str
    ontology_id: str
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, str] = Field(default_factory=dict)
    # B 阶段数据绑定：关系绑定到具体指标（ass_indicator）
    # 结构示例: {"indicator_id":"..."}
    bindings: Dict[str, str] = Field(default_factory=dict)
    weight: float = 1.0
    create_time: datetime


class OntologyModel(BaseModel):
    """本体模型（一个独立的本体空间，隔离实体与关系）。"""
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    entity_types: List[EntityType] = Field(default_factory=list)
    relation_types: List[RelationType] = Field(default_factory=list)
    create_time: datetime
    update_time: datetime
    status: str = "活跃"
    # B 阶段：默认本体标志，三服务自动取默认本体的依据；同一时刻仅一个为 True
    is_default: bool = False


class BuildJob(BaseModel):
    """本体分步构建任务（承载三步流程的状态机）。

    支持断点续作：每步结果持久化到 data/build_jobs/job_{id}.json。
    流程：upload → meta 推荐 → step1 概念提取 → step2 层次结构 → step3 序列化生成正式本体。
    """
    id: str                                    # job_xxxxxxxx
    name: str                                  # 本体名称
    description: str = ""
    step: int = 0                              # 0=待开始, 1=概念提取, 2=层次结构, 3=序列化, 4=已完成
    status: str = "draft"                      # draft | completed | abandoned

    # 文档源（持久化，支持断点续作）
    source_filename: str = ""
    source_text: str = ""                      # 解析后的纯文本
    char_count: int = 0                        # 文档字符数（前端展示用）

    # Step 0 结果：元模型（LLM 推荐，用户确认后不可被 LLM 修改）
    meta_entity_types: List[Dict[str, Any]] = []
    meta_relation_types: List[Dict[str, Any]] = []
    meta_confirmed: bool = False

    # Step 1 结果：概念清单
    step1_concepts: List[Dict[str, Any]] = []
    step1_confirmed: bool = False

    # Step 2 结果：层次结构
    step2_entities: List[Dict[str, Any]] = []
    step2_relations: List[Dict[str, Any]] = []
    step2_confirmed: bool = False

    # Step 3 结果：最终序列化
    step3_entities: List[Dict[str, Any]] = []
    step3_relations: List[Dict[str, Any]] = []

    # Step 1 分批状态（长文档分批提取概念，支持断点续作）
    step1_batches_total: int = 0                          # 总批数；0=从未分批
    step1_batches_done: int = 0                           # 已成功批数
    step1_batch_results: List[List[Dict[str, Any]]] = []  # 每批概念列表，按批次顺序暂存
    step1_failed_batch: int = -1                          # 失败批次索引；-1=无失败
    step1_failed_reason: Optional[str] = None             # 失败原因

    # Step 2 分组状态（概念过多时分组构建层次结构，支持断点续作）
    step2_groups_total: int = 0                           # 总组数；0=从未分组
    step2_groups_done: int = 0                            # 已成功组数
    step2_group_results: List[Dict[str, Any]] = []        # 每组 {"entities":[...], "relations":[...]}
    step2_failed_group: int = -1                          # 失败组索引；-1=无失败
    step2_failed_reason: Optional[str] = None             # 失败原因

    # Step 2 跨组关系补充（分组合并后由 LLM 补充跨组实体间关系）
    step2_cross_group_done: bool = False                  # 跨组关系补充是否完成
    step2_cross_group_relations: List[Dict[str, Any]] = []  # LLM 补充的跨组关系列表
    step2_cross_group_failed: bool = False                # 跨组补充是否失败
    step2_cross_group_reason: Optional[str] = None        # 跨组补充失败原因

    # 关联正式本体（第三步完成时生成）
    ontology_id: Optional[str] = None

    # 后台任务进度跟踪（每步 LLM 调用期间用户可离开页面）
    running_step: int = -1                     # -1=空闲, 0=概念提取中, 1=结构构建中, 2=序列化中
    progress: int = 0                          # 0-100
    progress_message: str = ""                 # 当前进度描述
    error_message: Optional[str] = None        # 后台任务失败时的错误信息

    create_time: datetime
    update_time: datetime


# ---------- 后台任务管理 ----------
# 存储正在运行的后台LLM任务（asyncio.Task），即使HTTP连接断开也继续执行
_background_tasks: Dict[str, Any] = {}


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
    """合并多组构建的实体，按 name 去重。

    Args:
        all_entities: 所有组的实体列表（已展开为一维）

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
            # type 不覆盖
            # parent 取首个非空
            if not existing.get("parent") and e.get("parent"):
                existing["parent"] = e["parent"]
            # properties 浅合并：后者补充前者没有的 key
            ex_props = existing.get("properties") or {}
            new_props = e.get("properties") or {}
            for k, v in new_props.items():
                if k not in ex_props:
                    ex_props[k] = v
            existing["properties"] = ex_props
    return [merged[k] for k in order]


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
    """后台任务：Step 1 概念提取（LLM调用，支持长文档分批 + 断点续作）。"""
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        # ---- 1. 判断是首次还是续跑 ----
        # 续跑条件：已分批过、未跑完、有失败标记
        is_resume = (job.step1_batches_total > 0
                     and job.step1_batches_done < job.step1_batches_total
                     and job.step1_failed_batch >= 0)
        # 已有完整 step1_concepts 且无失败 → 直接结束（防重复跑）
        if not is_resume and job.step1_concepts and job.step1_failed_batch < 0:
            _set_job_progress(job_id, -1, 100, "概念提取已完成")
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
        for idx in range(start_idx, total):
            _set_job_progress(
                job_id, 0,
                10 + int(85 * idx / max(total, 1)),
                f"正在提取概念（第 {idx + 1}/{total} 批）..." if total > 1 else "正在调用AI提取概念..."
            )
            batch_text = batches[idx] if idx < len(batches) else ""
            messages = build_prompts.build_step1_batch_messages(
                batch_text, job.name, job.meta_entity_types,
                batch_idx=idx, total_batches=total
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

        # ---- 4. 全部成功后合并去重 ----
        _set_job_progress(job_id, 0, 96, "正在合并概念...")
        all_concepts = [c for batch in job.step1_batch_results for c in batch]
        merged = _merge_concepts(all_concepts)
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
        logger.info(f"[{job_id}] 后台概念提取完成: {len(merged)} 个概念（{total} 批合并）")
    except Exception as e:
        logger.error(f"[{job_id}] 后台概念提取失败: {e}")
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
    finally:
        _background_tasks.pop(job_id, None)


async def _background_build_structure(job_id: str) -> None:
    """后台任务：Step 2 层次结构构建（LLM调用，支持概念分组 + 跨组关系补充 + 断点续作）。"""
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        concepts = job.step1_concepts or []
        if not concepts:
            raise ValueError("概念清单为空，无法构建层次结构")

        # ---- 1. 判断续跑状态 ----
        # 分组续跑：已分组过、未跑完、有失败标记
        is_group_resume = (job.step2_groups_total > 0
                           and job.step2_groups_done < job.step2_groups_total
                           and job.step2_failed_group >= 0)
        # 跨组补充续跑：分组已全部成功、跨组补充未完成
        # 注意：不依赖 cross_group_failed——旧数据/异常场景下该标记可能为 false，
        # 只要分组全部完成而跨组补充未完成，就应续跑跨组，而非重跑分组
        is_cross_resume = (job.step2_groups_total > 0
                           and job.step2_groups_done == job.step2_groups_total
                           and not job.step2_cross_group_done)
        # 已有完整 step2 结果且无失败 → 直接结束（防重复跑）
        if (not is_group_resume and not is_cross_resume
                and job.step2_entities and job.step2_failed_group < 0
                and (job.step2_cross_group_done or not job.step2_cross_group_failed)):
            _set_job_progress(job_id, -1, 100, "结构构建已完成")
            return

        # ---- 2. 重建 groups（无论首次还是续跑都重新分组，纯函数结果稳定）----
        if len(concepts) <= config.STEP2_GROUP_THRESHOLD_CONCEPTS:
            # 概念少：单组，保持兼容
            groups = [concepts]
            total = 1
        else:
            groups = _group_concepts(concepts, config.STEP2_GROUP_SIZE)
            total = len(groups)

        # 首次运行：记录总组数
        if job.step2_groups_total == 0:
            async with build_lock:
                job.step2_groups_total = total
                while len(job.step2_group_results) < total:
                    job.step2_group_results.append({"entities": [], "relations": []})
                job.update_time = datetime.now()
                save_build_job(job_id)
        elif job.step2_groups_total != total:
            logger.warning(
                f"[{job_id}] 分组数变化 {job.step2_groups_total}→{total}，"
                f"已成功 {job.step2_groups_done} 组结果保留，按新边界续跑"
            )
            async with build_lock:
                job.step2_groups_total = total
                while len(job.step2_group_results) < total:
                    job.step2_group_results.append({"entities": [], "relations": []})
                save_build_job(job_id)

        total = job.step2_groups_total

        # ---- 3. 分组续跑：从失败组开始跑剩余分组（跨组续跑跳过此循环）----
        if not is_cross_resume:
            start_idx = job.step2_groups_done if is_group_resume else 0
            logger.info(
                f"[{job_id}] Step2 结构构建：共 {total} 组，"
                f"{'续跑从第 ' + str(start_idx + 1) + ' 组' if is_group_resume else '首次从头'}开始"
            )
            for idx in range(start_idx, total):
                _set_job_progress(
                    job_id, 1,
                    10 + int(70 * idx / max(total, 1)),
                    f"正在构建层次结构（第 {idx + 1}/{total} 组）..." if total > 1 else "正在调用AI构建层次结构..."
                )
                group_concepts = groups[idx] if idx < len(groups) else []
                messages = build_prompts.build_step2_messages(
                    group_concepts, job.meta_entity_types, job.meta_relation_types
                )
                result = await _llm_json_async(messages, temperature=0.3, max_tokens=config.LLM_MAX_TOKENS)
                if not isinstance(result, dict):
                    raise ValueError(f"第 {idx + 1}/{total} 组返回格式异常（非对象），原始类型: {type(result).__name__}")
                group_entities = result.get("entities", [])
                group_relations = result.get("relations", [])

                async with build_lock:
                    while len(job.step2_group_results) <= idx:
                        job.step2_group_results.append({"entities": [], "relations": []})
                    job.step2_group_results[idx] = {"entities": group_entities, "relations": group_relations}
                    job.step2_groups_done = idx + 1
                    job.step2_failed_group = -1
                    job.step2_failed_reason = None
                    job.update_time = datetime.now()
                    save_build_job(job_id)
                logger.info(f"[{job_id}] Step2 第 {idx + 1}/{total} 组完成: {len(group_entities)} 实体, {len(group_relations)} 关系")

        # ---- 4. 合并实体 + 组内关系 ----
        _set_job_progress(job_id, 1, 82, "正在合并结构...")
        all_entities = [e for g in job.step2_group_results for e in g.get("entities", [])]
        all_relations = [r for g in job.step2_group_results for r in g.get("relations", [])]
        merged_entities = _merge_entities(all_entities)
        logger.info(
            f"[{job_id}] Step2 合并: {len(all_entities)}→{len(merged_entities)} 实体, "
            f"{len(all_relations)} 组内关系（{total} 组）"
        )

        # ---- 5. LLM 补充跨组关系（仅多组时执行，单组无需）----
        # 跨组补充失败可续跑：若已完成则跳过；若失败则重跑
        if total > 1 and not job.step2_cross_group_done:
            _set_job_progress(job_id, 1, 88, "正在补充跨组关系...")
            # 实体过多时取前 N 个（仅 name+type，控制 prompt 长度）
            entities_for_prompt = merged_entities[:config.STEP2_CROSS_GROUP_ENTITY_BATCH]
            cross_messages = build_prompts.build_step2_cross_group_messages(
                entities_for_prompt, all_relations,
                job.meta_entity_types, job.meta_relation_types
            )
            try:
                cross_result = await _llm_json_async(cross_messages, temperature=0.3, max_tokens=config.LLM_MAX_TOKENS)
                if not isinstance(cross_result, dict):
                    raise ValueError(f"跨组关系补充返回格式异常（非对象），原始类型: {type(cross_result).__name__}")
                cross_relations = cross_result.get("relations", [])
                if not isinstance(cross_relations, list):
                    cross_relations = []
                logger.info(f"[{job_id}] Step2 跨组关系补充: {len(cross_relations)} 条")
                async with build_lock:
                    job.step2_cross_group_relations = cross_relations
                    job.step2_cross_group_done = True
                    job.step2_cross_group_failed = False
                    job.step2_cross_group_reason = None
                    job.update_time = datetime.now()
                    save_build_job(job_id)
            except Exception as _e:
                # 跨组关系补充属"锦上添花"，失败不阻塞 Step 2 完成，仅标记失败供前端"继续构建"重试跨组
                logger.warning(f"[{job_id}] Step2 跨组关系补充失败，降级为仅组内关系: {_e}")
                async with build_lock:
                    job.step2_cross_group_failed = True
                    job.step2_cross_group_reason = str(_e)[:200]
                    job.step2_cross_group_done = False
                    job.update_time = datetime.now()
                    save_build_job(job_id)
        elif total <= 1:
            # 单组无需跨组补充，直接标记完成
            async with build_lock:
                job.step2_cross_group_done = True
                job.step2_cross_group_relations = []
                save_build_job(job_id)

        # ---- 6. 合并所有关系（组内 + 跨组）并去重 ----
        final_relations = _deduplicate_relations(all_relations + job.step2_cross_group_relations)
        cross_count = len(final_relations) - len(_deduplicate_relations(all_relations))

        async with build_lock:
            job.step2_entities = merged_entities
            job.step2_relations = final_relations
            job.step = max(job.step, 2)  # 结构已生成，等待用户确认（确认后才进入 step 3）
            job.running_step = -1
            job.progress = 100
            if total > 1:
                job.progress_message = (
                    f"结构构建完成，共 {len(merged_entities)} 个实体，{len(final_relations)} 条关系"
                    f"（{total} 组合并，含 {cross_count} 条跨组关系）"
                )
            else:
                job.progress_message = f"结构构建完成，共 {len(merged_entities)} 个实体，{len(final_relations)} 条关系"
            job.error_message = None
            job.update_time = datetime.now()
            save_build_job(job_id)
            save_build_jobs_index()
        logger.info(
            f"[{job_id}] 后台结构构建完成: {len(merged_entities)} 实体, {len(final_relations)} 关系"
            f"（含 {cross_count} 跨组）" if total > 1 else f"[{job_id}] 后台结构构建完成: {len(merged_entities)} 实体, {len(final_relations)} 关系"
        )
    except Exception as e:
        logger.error(f"[{job_id}] 后台结构构建失败: {e}")
        async with build_lock:
            job.running_step = -1
            job.progress = 0
            # 判断失败发生在分组阶段还是跨组补充阶段
            if job.step2_groups_done < job.step2_groups_total:
                # 分组阶段失败
                failed_idx = job.step2_groups_done
                job.step2_failed_group = failed_idx
                job.step2_failed_reason = str(e)[:200]
                job.error_message = f"第 {failed_idx + 1}/{job.step2_groups_total} 组失败: {str(e)[:150]}"
                job.progress_message = f"第 {failed_idx + 1}/{job.step2_groups_total} 组失败，可点击继续构建从该组续跑"
            else:
                # 跨组补充阶段失败
                job.step2_cross_group_failed = True
                job.step2_cross_group_reason = str(e)[:200]
                job.error_message = f"跨组关系补充失败: {str(e)[:150]}"
                job.progress_message = "跨组关系补充失败，可点击继续构建重新补充跨组关系"
            job.update_time = datetime.now()
            save_build_job(job_id)
    finally:
        _background_tasks.pop(job_id, None)


async def _background_generate_ontology(job_id: str) -> None:
    """后台任务：Step 3 最终序列化 + 生成正式本体（LLM调用）。"""
    job = build_jobs_db.get(job_id)
    if not job or job.status == "completed":
        return
    try:
        _set_job_progress(job_id, 2, 10, "正在准备数据...")
        _set_job_progress(job_id, 2, 30, "正在调用AI做最终序列化...")
        messages = build_prompts.build_step3_messages(
            job.step2_entities, job.step2_relations,
            job.meta_entity_types, job.meta_relation_types
        )
        result = await _llm_json_async(messages, temperature=0.3, max_tokens=8000)
        if not isinstance(result, dict):
            raise ValueError("LLM 返回格式异常")
        final_entities = result.get("entities", job.step2_entities)
        final_relations = result.get("relations", job.step2_relations)

        # 生成正式本体
        now = datetime.now()
        new_oid = f"ont_{uuid.uuid4().hex[:8]}"
        ont = OntologyModel(
            id=new_oid, name=job.name, description=job.description, version="1.0.0",
            entity_types=[EntityType(**t) for t in job.meta_entity_types],
            relation_types=[RelationType(**t) for t in job.meta_relation_types],
            create_time=now, update_time=now, status="活跃",
        )
        ent_map: Dict[str, str] = {}
        new_entities: List[Entity] = []
        for ed in final_entities:
            new_eid = f"ent_{uuid.uuid4().hex[:8]}"
            ent_map[ed.get("name", "")] = new_eid
            new_entities.append(Entity(
                id=new_eid, ontology_id=new_oid, name=ed.get("name", "未命名"),
                type=ed.get("type", "概念"), properties=ed.get("properties", {}),
                create_time=now, update_time=now,
            ))
        new_relations: List[Relation] = []
        for rd in final_relations:
            src = ent_map.get(rd.get("source", ""))
            tgt = ent_map.get(rd.get("target", ""))
            if not src or not tgt:
                continue
            new_relations.append(Relation(
                id=f"rel_{uuid.uuid4().hex[:8]}", ontology_id=new_oid,
                source_id=src, target_id=tgt,
                relation_type=rd.get("relation_type", "关联"),
                properties=rd.get("properties", {}), weight=rd.get("weight", 1.0),
                create_time=now,
            ))

        async with db_lock:
            ontologies_db[new_oid] = ont
            entities_db[new_oid] = new_entities
            relations_db[new_oid] = new_relations
            save_ontology(new_oid)
            save_index()

        async with build_lock:
            job.ontology_id = new_oid
            job.step = 4
            job.status = "completed"
            job.running_step = -1
            job.progress = 100
            job.progress_message = "本体生成成功！"
            job.update_time = datetime.now()
            save_build_job(job_id)
            save_build_jobs_index()
        logger.info(f"[{job_id}] 后台本体生成成功: {new_oid}")
    except Exception as e:
        logger.error(f"[{job_id}] 后台本体生成失败: {e}")
        async with build_lock:
            job.running_step = -1
            job.progress = 0
            job.error_message = str(e)[:200]
            job.update_time = datetime.now()
            save_build_job(job_id)
    finally:
        _background_tasks.pop(job_id, None)


# ---------- 持久化 ----------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
INDEX_FILE = os.path.join(DATA_DIR, 'ontologies_index.json')
LOCK_DIR = os.path.join(DATA_DIR, '.locks')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOCK_DIR, exist_ok=True)


def _ontology_file(ontology_id: str) -> str:
    """本体数据文件路径。"""
    return os.path.join(DATA_DIR, f'ontology_{ontology_id}.json')


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


# ---------- 内存数据（按 ontology_id 组织，实现多本体隔离）----------
# ontologies_db: ontology_id -> OntologyModel
# entities_db: ontology_id -> List[Entity]
# relations_db: ontology_id -> List[Relation]
ontologies_db: Dict[str, OntologyModel] = {}
entities_db: Dict[str, List[Entity]] = {}
relations_db: Dict[str, List[Relation]] = {}

# 协程锁：保护内存全局变量，防 FastAPI 异步并发竞态
db_lock = __import__('asyncio').Lock()


def save_ontology(ontology_id: str) -> None:
    """持久化单个本体（元信息 + 实体 + 关系）到独立文件。"""
    ont = ontologies_db.get(ontology_id)
    if not ont:
        return
    data = {
        'ontology': ont.dict(),
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
    """启动时加载所有本体数据到内存。"""
    global ontologies_db, entities_db, relations_db
    ontologies_db = {}
    entities_db = {}
    relations_db = {}

    index = load_json_with_backup(INDEX_FILE, [])
    if not isinstance(index, list):
        index = []

    for item in index:
        try:
            ont = OntologyModel(**item)
        except Exception as e:
            logger.warning(f"索引项解析失败，跳过: {e}")
            continue
        ontologies_db[ont.id] = ont
        # 加载该本体的实体关系
        data = load_json_with_backup(_ontology_file(ont.id), {'entities': [], 'relations': []})
        ents = []
        for e in data.get('entities', []):
            try:
                ents.append(Entity(**e))
            except Exception as e2:
                logger.warning(f"实体解析失败，跳过: {e2}")
        rels = []
        for r in data.get('relations', []):
            try:
                rels.append(Relation(**r))
            except Exception as e2:
                logger.warning(f"关系解析失败，跳过: {e2}")
        entities_db[ont.id] = ents
        relations_db[ont.id] = rels

    logger.info(f"加载完成: {len(ontologies_db)} 个本体, "
                f"{sum(len(v) for v in entities_db.values())} 个实体, "
                f"{sum(len(v) for v in relations_db.values())} 条关系")


def _count_entities(ontology_id: str) -> int:
    """统计某本体的实体数。"""
    return len(entities_db.get(ontology_id, []))


def _count_relations(ontology_id: str) -> int:
    """统计某本体的关系数。"""
    return len(relations_db.get(ontology_id, []))


def _ontology_summary(ont: OntologyModel) -> Dict[str, Any]:
    """返回本体摘要（含实时计数）。"""
    d = ont.dict()
    d['entities_count'] = _count_entities(ont.id)
    d['relations_count'] = _count_relations(ont.id)
    return d


def _get_ontology_or_404(ontology_id: str) -> OntologyModel:
    """获取本体，不存在则抛 404。"""
    ont = ontologies_db.get(ontology_id)
    if not ont:
        raise HTTPException(status_code=404, detail="本体模型不存在")
    return ont


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


def _validate_entity_type(ontology_id: str, entity_type: str) -> None:
    """校验实体类型在本体元模型定义内。"""
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
def seed_if_empty() -> None:
    """首次启动且无任何本体时，写入作战指挥示例本体。"""
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
    )
    ontologies_db[oid] = ont

    # 实体定义：能力维度 + 指标 + 参战对象
    seed_entities = [
        ("作战效能", "概念", {"定义": "综合评估指标", "重要性": "高"}),
        ("打击能力", "概念", {"定义": "武器打击效果", "权重": "0.4"}),
        ("生存能力", "概念", {"定义": "存活概率", "权重": "0.3"}),
        ("保障能力", "概念", {"定义": "后勤保障水平", "权重": "0.3"}),
        ("命中率", "属性", {"公式": "命中/射击*100%", "单位": "%"}),
        ("摧毁率", "属性", {"公式": "摧毁/命中*100%", "单位": "%"}),
        ("战损率", "属性", {"公式": "损失/总数*100%", "单位": "%"}),
        ("红方部队", "实体", {"阵营": "红方", "类型": "合成营"}),
        ("蓝方部队", "实体", {"阵营": "蓝方", "类型": "机步连"}),
        ("武器平台", "实体", {"类别": "装备", "状态": "在役"}),
        ("弹药消耗", "事件", {"单位": "发", "阶段": "全期"}),
    ]
    ent_map = {}  # name -> id，用于构造关系
    ents = []
    for idx, (name, etype, props) in enumerate(seed_entities):
        eid = f"ent_seed_{idx:02d}"
        ent_map[name] = eid
        ents.append(Entity(
            id=eid, ontology_id=oid, name=name, type=etype,
            properties=props, create_time=now, update_time=now,
        ))
    entities_db[oid] = ents

    # 关系定义：层级包含 + 影响关系
    seed_relations = [
        ("作战效能", "包含", "打击能力", 1.0),
        ("作战效能", "包含", "生存能力", 1.0),
        ("作战效能", "包含", "保障能力", 1.0),
        ("打击能力", "影响", "命中率", 0.8),
        ("打击能力", "影响", "摧毁率", 0.8),
        ("生存能力", "影响", "战损率", 0.7),
        ("保障能力", "影响", "战损率", 0.5),
        ("红方部队", "关联", "武器平台", 0.6),
        ("蓝方部队", "关联", "武器平台", 0.6),
        ("红方部队", "关联", "蓝方部队", 0.9),
        ("武器平台", "衡量", "命中率", 0.7),
        ("武器平台", "衡量", "摧毁率", 0.7),
        ("弹药消耗", "衡量", "打击能力", 0.6),
    ]
    rels = []
    for idx, (src, rtype, tgt, w) in enumerate(seed_relations):
        if src not in ent_map or tgt not in ent_map:
            continue
        rels.append(Relation(
            id=f"rel_seed_{idx:02d}", ontology_id=oid,
            source_id=ent_map[src], target_id=ent_map[tgt],
            relation_type=rtype, properties={}, weight=w,
            create_time=now,
        ))
    relations_db[oid] = rels

    save_ontology(oid)
    save_index()
    logger.info(f"已写入示例本体: {ont.name} ({len(ents)} 实体, {len(rels)} 关系)")


# 启动时加载数据并按需 seed
load_db()
seed_if_empty()
load_build_jobs()


@app.on_event("startup")
async def _retry_pending_build_jobs():
    """服务启动时重试卡死的构建任务（事件循环就绪后执行）。"""
    if not _pending_retries:
        return
    # 延迟 2 秒，确保服务完全就绪
    await asyncio.sleep(2)
    for job_id in _pending_retries:
        job = build_jobs_db.get(job_id)
        if not job or job.status == "completed":
            continue
        # 根据 confirmed 状态判断该重试哪一步
        if job.step2_confirmed:
            logger.info(f"[{job_id}] 自动重试 step3（序列化）")
            _set_job_progress(job_id, 2, 5, "服务重启后自动重试...")
            task = asyncio.create_task(_background_generate_ontology(job_id))
            _background_tasks[job_id] = task
        elif job.step1_confirmed:
            logger.info(f"[{job_id}] 自动重试 step2（层次结构）")
            _set_job_progress(job_id, 1, 5, "服务重启后自动重试...")
            task = asyncio.create_task(_background_build_structure(job_id))
            _background_tasks[job_id] = task
        elif job.meta_confirmed:
            logger.info(f"[{job_id}] 自动重试 step1（概念提取）")
            _set_job_progress(job_id, 0, 5, "服务重启后自动重试...")
            task = asyncio.create_task(_background_extract_concepts(job_id))
            _background_tasks[job_id] = task
    _pending_retries.clear()


# ---------- 图谱与路径辅助 ----------
def _graph_data(ontology_id: str) -> Dict[str, Any]:
    """聚合某本体的图谱数据（nodes/links）。"""
    nodes = []
    links = []
    for e in entities_db.get(ontology_id, []):
        nodes.append({
            "id": e.id,
            "name": e.name,
            "type": e.type,
            "category": e.type,
        })
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
        "entities": [e.dict() for e in path_entities],
        "relations": [r.dict() for r in path_relations],
    }


# ---------- 本体上下文（供 B2 三服务 prompt 注入消费）----------
def _select_entities_by_question(ents: List[Entity], question: str, top_k: int) -> List[Entity]:
    """按问题关键词筛选实体，命中优先，不超过 top_k。

    简单 in 匹配（实体名/属性键值），不引入向量检索。
    命中数为 0 时退化为取前 top_k 个，保证上下文非空。
    """
    if len(ents) <= top_k:
        return list(ents)
    if not question:
        return ents[:top_k]
    q_lower = question.lower()
    hits, misses = [], []
    for e in ents:
        hit = (q_lower in e.name.lower()
               or any(q_lower in str(v).lower() for v in e.properties.values())
               or any(q_lower in str(k).lower() for k in e.properties.keys()))
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

    selected = _select_entities_by_question(ents, question, top_k)
    selected_ids = {e.id for e in selected}
    # 关系：仅保留两端实体都在选中集合内的，避免 summary 出现"未知"节点
    selected_rels = [r for r in rels
                     if r.source_id in selected_ids and r.target_id in selected_ids]

    # ── 拼接可直接塞 prompt 的中文背景文本 ──
    lines = [f"【领域本体：{ont.name}】"]
    if ont.description:
        lines.append(f"说明：{ont.description}")
    lines.append(f"概念清单（共 {len(selected)} 个）：")
    for e in selected:
        parts = [f"- {e.name}（类型：{e.type}）"]
        if e.properties:
            prop_str = "、".join(f"{k}:{v}" for k, v in e.properties.items())
            parts.append(f"属性[{prop_str}]")
        if e.bindings and e.bindings.get("table_name") and e.bindings.get("column_name"):
            parts.append(f"绑定数据字段[{e.bindings['table_name']}.{e.bindings['column_name']}]")
        lines.append(" ".join(parts))

    if selected_rels:
        lines.append(f"概念关系链路（共 {len(selected_rels)} 条）：")
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
        "entities": [e.dict() for e in selected],
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
    for oid, ents in entities_db.items():
        total_entities += len(ents)
        for e in ents:
            entity_types[e.type] += 1
    for oid, rels in relations_db.items():
        total_relations += len(rels)
        for r in rels:
            relation_types[r.relation_type] += 1
    return {
        "success": True,
        "data": {
            "total_entities": total_entities,
            "total_relations": total_relations,
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
    """删除本体及其下属的所有实体与关系（仅删该本体，不影响其他本体）。"""
    async with db_lock:
        if ontology_id not in ontologies_db:
            raise HTTPException(status_code=404, detail="本体模型不存在")
        ontologies_db.pop(ontology_id)
        entities_db.pop(ontology_id, None)
        relations_db.pop(ontology_id, None)
        save_index()
        # 删除本体数据文件（保留 .bak 以便误删恢复）
        path = _ontology_file(ontology_id)
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
    entity_type: str = Form(...),
    properties: str = Form("{}")
):
    """向指定本体添加实体。"""
    _get_ontology_or_404(ontology_id)
    _validate_entity_type(ontology_id, entity_type)
    props = _parse_json_arg(properties, {})

    async with db_lock:
        ont = ontologies_db[ontology_id]
        entity = Entity(
            id=f"ent_{uuid.uuid4().hex[:8]}",
            ontology_id=ontology_id,
            name=name,
            type=entity_type,
            properties=props,
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
        "data": entity.dict()
    }


@app.get("/ontology/{ontology_id}/entity/list")
async def list_entities(
    ontology_id: str,
    entity_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """列出某本体的实体（支持按类型过滤与分页）。"""
    _get_ontology_or_404(ontology_id)
    filtered = entities_db.get(ontology_id, [])
    if entity_type:
        filtered = [e for e in filtered if e.type == entity_type]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [e.dict() for e in items]
    }


@app.get("/ontology/{ontology_id}/entity/{entity_id}")
async def get_entity(ontology_id: str, entity_id: str):
    """获取本体内某个实体。"""
    _get_ontology_or_404(ontology_id)
    entity = _find_entity(ontology_id, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="实体不存在")
    return {"success": True, "data": entity.dict()}


@app.put("/ontology/{ontology_id}/entity/{entity_id}")
async def update_entity(
    ontology_id: str,
    entity_id: str,
    name: str = Form(...),
    entity_type: str = Form(...),
    properties: str = Form("{}")
):
    """更新实体。"""
    _get_ontology_or_404(ontology_id)
    _validate_entity_type(ontology_id, entity_type)
    props = _parse_json_arg(properties, {})

    async with db_lock:
        entity = _find_entity(ontology_id, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")
        entity.name = name
        entity.type = entity_type
        entity.properties = props
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
    props = _parse_json_arg(properties, {})

    async with db_lock:
        if not _find_entity(ontology_id, source_id):
            raise HTTPException(status_code=400, detail="源实体不存在")
        if not _find_entity(ontology_id, target_id):
            raise HTTPException(status_code=400, detail="目标实体不存在")

        relation = Relation(
            id=f"rel_{uuid.uuid4().hex[:8]}",
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


@app.get("/ontology/{ontology_id}/bindings")
async def get_bindings(ontology_id: str):
    """返回该本体所有绑定的紧凑结构（仅含已绑定的实体/关系）。

    供前端 badge 展示与 B2 prompt 注入消费。
    """
    _get_ontology_or_404(ontology_id)
    bound_entities = [
        {"id": e.id, "name": e.name, "type": e.type, "bindings": e.bindings}
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
    """导入本体文件，建立旧id->新id映射，重定向关系，避免断链。"""
    try:
        content = await file.read()
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")

    now = datetime.now()
    new_oid = f"ont_{uuid.uuid4().hex[:8]}"

    # 解析元模型类型
    et_list = data.get("entity_types") or DEFAULT_ENTITY_TYPES
    rt_list = data.get("relation_types") or DEFAULT_RELATION_TYPES

    ont = OntologyModel(
        id=new_oid,
        name=data.get("name", "导入本体"),
        description=data.get("description", ""),
        version=data.get("version", "1.0.0"),
        entity_types=[EntityType(**t) for t in et_list],
        relation_types=[RelationType(**t) for t in rt_list],
        create_time=now,
        update_time=now,
        status="活跃",
    )

    # 旧实体id -> 新实体id 映射，防止关系断链
    id_map = {}
    new_entities = []
    for ed in data.get("entities", []):
        old_id = ed.get("id") or f"ent_{uuid.uuid4().hex[:8]}"
        new_id = f"ent_{uuid.uuid4().hex[:8]}"
        id_map[old_id] = new_id
        new_entities.append(Entity(
            id=new_id,
            ontology_id=new_oid,
            name=ed.get("name", "未命名"),
            type=ed.get("type", "概念"),
            properties=ed.get("properties", {}),
            bindings=ed.get("bindings", {}),
            create_time=now,
            update_time=now,
        ))

    new_relations = []
    for rd in data.get("relations", []):
        src = id_map.get(rd.get("source_id"))
        tgt = id_map.get(rd.get("target_id"))
        # 跳过指向不存在实体的关系
        if not src or not tgt:
            continue
        new_relations.append(Relation(
            id=f"rel_{uuid.uuid4().hex[:8]}",
            ontology_id=new_oid,
            source_id=src,
            target_id=tgt,
            relation_type=rd.get("relation_type") or rd.get("type", "关联"),
            properties=rd.get("properties", {}),
            bindings=rd.get("bindings", {}),
            weight=rd.get("weight", 1.0),
            create_time=now,
        ))

    async with db_lock:
        ontologies_db[new_oid] = ont
        entities_db[new_oid] = new_entities
        relations_db[new_oid] = new_relations
        save_ontology(new_oid)
        save_index()

    return {
        "success": True,
        "message": "本体模型导入成功",
        "data": {
            "ontology_id": new_oid,
            "entities_imported": len(new_entities),
            "relations_imported": len(new_relations)
        }
    }


@app.get("/ontology/export/{ontology_id}")
async def export_ontology(ontology_id: str):
    """导出本体为 JSON（含元模型 + 实体 + 关系）。"""
    ont = _get_ontology_or_404(ontology_id)
    data = {
        "name": ont.name,
        "description": ont.description,
        "version": ont.version,
        "entity_types": [t.dict() for t in ont.entity_types],
        "relation_types": [t.dict() for t in ont.relation_types],
        "entities": [e.dict() for e in entities_db.get(ontology_id, [])],
        "relations": [r.dict() for r in relations_db.get(ontology_id, [])]
    }
    return {"success": True, "data": data}


@app.post("/ontology/search")
async def search_ontology(
    query: str = Form(...),
    ontology_id: str = Form(...)
):
    """在某本体内搜索实体与关系（匹配名称、类型、关系类型、属性键值）。"""
    _get_ontology_or_404(ontology_id)
    query_lower = query.lower()

    matched_entities = []
    for e in entities_db.get(ontology_id, []):
        if (query_lower in e.name.lower()
                or query_lower in e.type.lower()):
            matched_entities.append(e.dict())
            continue
        # 搜索属性键值
        hit = any(query_lower in str(k).lower() or query_lower in str(v).lower()
                  for k, v in e.properties.items())
        if hit:
            matched_entities.append(e.dict())

    matched_relations = []
    for r in relations_db.get(ontology_id, []):
        if query_lower in r.relation_type.lower():
            matched_relations.append(r.dict())
            continue
        hit = any(query_lower in str(k).lower() or query_lower in str(v).lower()
                  for k, v in r.properties.items())
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
    description: str = Form("")
):
    """上传文档创建构建任务，并同步调用 LLM 推荐元模型。

    流程：
    1. 解析文档为纯文本
    2. 创建 BuildJob（step=0）
    3. 调用 LLM 推荐元模型（失败则用默认元模型兜底）
    4. 持久化任务，返回 job_id + 推荐的元模型

    用户后续可通过 PUT /ontology/build/{job_id}/meta 确认或编辑元模型。
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
        create_time=now,
        update_time=now,
    )

    # 3. 调用 LLM 推荐元模型（失败用默认元模型兜底，不阻塞上传）
    try:
        messages = build_prompts.build_meta_messages(doc_text_truncated, name)
        meta = await _llm_json_async(messages, temperature=0.3, max_tokens=2000)
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
                "meta_confirmed": j.meta_confirmed,
                "step1_confirmed": j.step1_confirmed,
                "step2_confirmed": j.step2_confirmed,
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
    """查询构建任务进度（轻量级，供前端轮询）。"""
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
            "meta_confirmed": job.meta_confirmed,
            "step1_confirmed": job.step1_confirmed,
            "step2_confirmed": job.step2_confirmed,
            "ontology_id": job.ontology_id,
            # Step 1 分批状态（前端用于显示"第 X/N 批"和"继续提取"按钮）
            "step1_batches_total": job.step1_batches_total,
            "step1_batches_done": job.step1_batches_done,
            "step1_failed_batch": job.step1_failed_batch,
            # Step 2 分组状态（前端用于显示"第 X/N 组"和"继续构建"按钮）
            "step2_groups_total": job.step2_groups_total,
            "step2_groups_done": job.step2_groups_done,
            "step2_failed_group": job.step2_failed_group,
            # Step 2 跨组关系补充状态
            "step2_cross_group_done": job.step2_cross_group_done,
            "step2_cross_group_failed": job.step2_cross_group_failed,
        }
    }


@app.get("/ontology/build/{job_id}")
async def build_get(job_id: str):
    """查询构建任务详情（断点续作用）。"""
    job = _get_job_or_404(job_id)
    return {"success": True, "data": job.dict()}


@app.put("/ontology/build/{job_id}/meta")
async def build_confirm_meta(
    job_id: str,
    entity_types: str = Form(...),
    relation_types: str = Form(...)
):
    """用户确认或编辑元模型。

    确认后元模型固定，后续 step1/step2 的 LLM 调用必须遵守此约束，不可修改。
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

    async with build_lock:
        job.meta_entity_types = et_list
        job.meta_relation_types = rt_list
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
        }
    }


@app.post("/ontology/build/{job_id}/step1")
async def build_step1(job_id: str):
    """Step 1: LLM 从文档提取概念清单（后台异步执行）。

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
        job_id, 0, 5,
        "继续提取概念..." if is_resume else "正在准备提取概念..."
    )
    task = asyncio.create_task(_background_extract_concepts(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "概念提取继续运行，从失败批次续跑..." if is_resume else "概念提取已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 0, "is_resume": is_resume}
    }


@app.put("/ontology/build/{job_id}/step1")
async def build_confirm_step1(job_id: str, concepts: str = Form(...)):
    """用户确认概念清单（可编辑后提交）。

    确认后才能执行 step2。
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
        "message": "概念清单已确认，可执行层次结构构建",
        "data": {"job_id": job_id, "step": job.step}
    }


@app.post("/ontology/build/{job_id}/step2")
async def build_step2(job_id: str):
    """Step 2: LLM 把概念清单整理成层次结构（后台异步执行）。

    前置条件：step1 已确认。
    立即返回，LLM 调用在后台进行，前端轮询结果。
    """
    job = _get_job_or_404(job_id)
    if not job.step1_confirmed:
        raise HTTPException(status_code=400, detail="请先确认概念清单（PUT /ontology/build/{job_id}/step1）")
    if job.step2_confirmed:
        raise HTTPException(status_code=400, detail="层次结构已确认，如需重新生成请先撤销确认")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    # 判断是续跑（分组或跨组关系补充断点续作）还是首次构建
    is_resume = ((job.step2_groups_total > 0
                  and job.step2_groups_done < job.step2_groups_total
                  and job.step2_failed_group >= 0)
                 or (job.step2_groups_total > 0
                     and job.step2_groups_done == job.step2_groups_total
                     and not job.step2_cross_group_done
                     and job.step2_cross_group_failed))

    # 启动后台任务，立即返回（清空陈旧错误，避免前端显示旧报错）
    async with build_lock:
        job.error_message = None
        job.update_time = datetime.now()
        save_build_job(job_id)
    _set_job_progress(
        job_id, 1, 5,
        "继续构建层次结构..." if is_resume else "正在准备构建层次结构..."
    )
    task = asyncio.create_task(_background_build_structure(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "层次结构构建继续运行，从断点续跑..." if is_resume else "层次结构构建已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 1, "is_resume": is_resume}
    }


@app.put("/ontology/build/{job_id}/step2")
async def build_confirm_step2(
    job_id: str,
    entities: str = Form(...),
    relations: str = Form(...)
):
    """用户确认层次结构（可编辑后提交）。

    确认后才能执行 step3。
    """
    job = _get_job_or_404(job_id)
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")

    try:
        entities_list = json.loads(entities) if isinstance(entities, str) else entities
        relations_list = json.loads(relations) if isinstance(relations, str) else relations
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"层次结构 JSON 解析失败: {e}")

    if not isinstance(entities_list, list) or not entities_list:
        raise HTTPException(status_code=400, detail="实体列表不能为空")

    async with build_lock:
        job.step2_entities = entities_list
        job.step2_relations = relations_list if isinstance(relations_list, list) else []
        job.step2_confirmed = True
        job.error_message = None
        job.step = max(job.step, 3)
        job.update_time = datetime.now()
        save_build_job(job_id)

    return {
        "success": True,
        "message": "层次结构已确认，可执行最终序列化",
        "data": {"job_id": job_id, "step": job.step}
    }


@app.post("/ontology/build/{job_id}/step3")
async def build_step3(job_id: str):
    """Step 3: LLM 最终序列化 + 生成正式本体（后台异步执行）。

    前置条件：step2 已确认。
    直接复用已确认的元模型（不再让 LLM 推荐元模型），LLM 仅做一致性检查和属性补充。
    立即返回，LLM 调用 + 本体生成在后台进行，前端轮询结果。
    """
    job = _get_job_or_404(job_id)
    if not job.step2_confirmed:
        raise HTTPException(status_code=400, detail="请先确认层次结构（PUT /ontology/build/{job_id}/step2）")
    if job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成")
    if job.running_step != -1:
        raise HTTPException(status_code=400, detail="当前有步骤正在后台运行中，请等待完成")

    # 启动后台任务，立即返回
    _set_job_progress(job_id, 2, 5, "正在准备最终序列化...")
    task = asyncio.create_task(_background_generate_ontology(job_id))
    _background_tasks[job_id] = task

    return {
        "success": True,
        "message": "最终序列化已在后台开始，您可以离开页面，稍后回来查看结果",
        "data": {"job_id": job_id, "running_step": 2}
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
