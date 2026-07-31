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
from filelock import FileLock

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10256)
