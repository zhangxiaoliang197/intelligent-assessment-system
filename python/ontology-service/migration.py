"""旧数据迁移模块。

将 schema_version=1（或缺失）的本体数据迁移到 schema_version=2：
- 实体 type（字符串）→ instance_of（概念ID），并为每个唯一 type 创建 ConceptType
- 实体 properties: Dict[str,str] → List[Property]（结构化属性对象）
- 关系 properties: Dict[str,str] → List[Property]
- 新增 concepts 列表（从唯一 type 值实例化为 ConceptType）

迁移前自动备份 data 目录，失败可回滚。

设计原则：
- 幂等：已迁移（schema_version>=2）的数据原样返回，不重复迁移
- 保守：无法判断的字段降级为默认值（category=descriptive, data_type=string）
- 可溯源：迁移后的 ConceptType 保留原 type 名，便于人工核对
"""
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List

import logging
logger = logging.getLogger("ontology-service")


# 当前数据 schema 版本
SCHEMA_VERSION = 2


def backup_data_dir(data_dir: str) -> str:
    """备份 data 目录到同级 data_backup_YYYYMMDD_HHMMSS/。

    仅备份 *.json 文件与子目录，跳过 .locks 等临时目录。

    Args:
        data_dir: data 目录绝对路径

    Returns:
        备份目录绝对路径
    """
    import shutil
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parent = os.path.dirname(data_dir)
    backup_dir = os.path.join(parent, f"data_backup_{timestamp}")
    shutil.copytree(data_dir, backup_dir, ignore=shutil.ignore_patterns('.locks', '*.tmp'))
    logger.info(f"已备份 data 目录到 {backup_dir}")
    return backup_dir


def _make_property(prop_id: str, owner_id: str, name: str, value: Any) -> Dict[str, Any]:
    """从 key-value 构造结构化属性 dict。

    迁移时无法判断属性分类（描述型/指标型），统一降级为 descriptive。
    后续用户可在前端手动改分类，或 step4 验证时 LLM 辅助标注。

    Args:
        prop_id: 属性ID
        owner_id: 所属实体/关系ID
        name: 属性名
        value: 属性值

    Returns:
        结构化属性 dict
    """
    now = datetime.now().isoformat()
    return {
        "id": prop_id,
        "entity_id": owner_id,
        "name": name,
        "value": value,
        "category": "descriptive",
        "data_type": "string",
        "unit": "",
        "source_snippet": "",
        "bindings": {},
        "history": [],
        "verification": None,
        "create_time": now,
        "update_time": now,
    }


def _migrate_properties_dict_to_list(props_dict: Any, owner_id: str) -> List[Dict[str, Any]]:
    """将 Dict[str,str] 属性转为 List[Property]。

    兼容三种输入：
    - Dict[str,str]（旧格式）：逐项转换
    - List[Property]（已是新格式）：原样返回
    - None/空：返回空列表
    """
    if not props_dict:
        return []
    # 已是新格式（List[dict] 且元素含 id 字段）
    if isinstance(props_dict, list):
        return props_dict
    if not isinstance(props_dict, dict):
        return []
    result = []
    for name, value in props_dict.items():
        prop_id = f"prop_{uuid.uuid4().hex[:8]}"
        result.append(_make_property(prop_id, owner_id, name, value))
    return result


def migrate_ontology_dict(data: Dict[str, Any], ontology_id: str) -> Dict[str, Any]:
    """迁移单个本体数据 dict 到 schema_version=2。

    幂等：若已迁移（schema_version>=2）则原样返回。

    Args:
        data: 原始本体数据 dict，含 ontology/entities/relations
        ontology_id: 本体ID

    Returns:
        迁移后的 dict，结构为 {ontology, concepts, entities, relations}
    """
    if not isinstance(data, dict):
        return data

    ontology = data.get("ontology", {})
    if isinstance(ontology, dict) and ontology.get("schema_version", 1) >= SCHEMA_VERSION:
        return data  # 已迁移，原样返回

    now = datetime.now().isoformat()
    entities = data.get("entities", []) or []
    relations = data.get("relations", []) or []
    existing_concepts = data.get("concepts", []) or []

    # ── 1. 收集所有实体的唯一 type，生成 ConceptType ──
    # entity_type name → ConceptType dict（迁移时每个唯一 type 实例化为一个概念节点）
    concept_map: Dict[str, Dict[str, Any]] = {}
    # 优先从 ontology.entity_types 继承 color
    entity_type_colors: Dict[str, str] = {}
    if isinstance(ontology, dict):
        for et in ontology.get("entity_types", []) or []:
            if isinstance(et, dict) and et.get("name"):
                entity_type_colors[et["name"]] = et.get("color", "#5470c6")

    # 已有 concepts（理论上 v1 没有，但防御性处理）
    for c in existing_concepts:
        if isinstance(c, dict) and c.get("name"):
            concept_map[c["name"]] = c

    concepts: List[Dict[str, Any]] = list(existing_concepts)
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        type_name = ent.get("type", "未分类")
        if type_name not in concept_map:
            concept_id = f"concept_{uuid.uuid4().hex[:8]}"
            concept = {
                "id": concept_id,
                "ontology_id": ontology_id,
                "name": type_name,
                "entity_type": type_name,
                "description": f"迁移自动生成：{type_name} 类概念",
                "color": entity_type_colors.get(type_name, "#5470c6"),
                "property_schema": [],
                "source_snippet": "",
                "create_time": now,
                "update_time": now,
            }
            concept_map[type_name] = concept
            concepts.append(concept)

    # ── 2. 迁移实体：type → instance_of, properties Dict → List ──
    migrated_entities: List[Dict[str, Any]] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        type_name = ent.get("type", "未分类")
        concept = concept_map.get(type_name)
        instance_of = concept["id"] if concept else ""

        ent_id = ent.get("id", f"ent_{uuid.uuid4().hex[:8]}")
        old_props = ent.get("properties", {})
        # 兼容：若 properties 已是 list（新格式），_migrate_properties_dict_to_list 会原样返回
        new_props = _migrate_properties_dict_to_list(old_props, ent_id)

        migrated_ent = {
            "id": ent_id,
            "ontology_id": ontology_id,
            "name": ent.get("name", "未命名"),
            "instance_of": instance_of,
            "is_primary": False,
            "properties": new_props,
            "bindings": ent.get("bindings", {}) or {},
            "source_snippet": ent.get("source_snippet", "") or "",
            "create_time": ent.get("create_time", now),
            "update_time": ent.get("update_time", now),
        }
        migrated_entities.append(migrated_ent)

    # ── 3. 迁移关系：properties Dict → List ──
    migrated_relations: List[Dict[str, Any]] = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        rel_id = rel.get("id", f"rel_{uuid.uuid4().hex[:8]}")
        old_props = rel.get("properties", {})
        new_props = _migrate_properties_dict_to_list(old_props, rel_id)

        migrated_rel = {
            "id": rel_id,
            "ontology_id": ontology_id,
            "source_id": rel.get("source_id", ""),
            "target_id": rel.get("target_id", ""),
            "relation_type": rel.get("relation_type", "关联"),
            "properties": new_props,
            "bindings": rel.get("bindings", {}) or {},
            "weight": rel.get("weight", 1.0),
            "source_snippet": rel.get("source_snippet", "") or "",
            "create_time": rel.get("create_time", now),
        }
        migrated_relations.append(migrated_rel)

    # ── 4. 更新 ontology 元信息 ──
    if not isinstance(ontology, dict):
        ontology = {}
    ontology["schema_version"] = SCHEMA_VERSION

    logger.info(
        f"本体 {ontology_id} 迁移完成：{len(concepts)} 概念, "
        f"{len(migrated_entities)} 实体, {len(migrated_relations)} 关系"
    )

    return {
        "ontology": ontology,
        "concepts": concepts,
        "entities": migrated_entities,
        "relations": migrated_relations,
    }
