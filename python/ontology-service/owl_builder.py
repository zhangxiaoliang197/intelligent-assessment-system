"""OWL 2 / RDF 本体生成器：将 Pydantic 数据模型映射为 OWL 2 文件。

设计要点（与 docs/OWL2-Neo4j-存储层重构方案.md 第三节对齐）：

| Pydantic 模型          | OWL 2 映射                                       |
|------------------------|--------------------------------------------------|
| OntologyModel          | owl:Ontology（IRI=base/{id}#）                   |
| EntityType（本体模型）   | owl:Class 顶层（subClassOf owl:Thing）           |
| ConceptType（实体类型）    | owl:Class（subClassOf EntityType）               |
| Entity（实体）         | owl:NamedIndividual（rdf:type ConceptType）      |
| Property（属性）       | owl:DatatypeProperty 断言（动态创建，支持中文）  |
| Relation（关系）       | owl:ObjectProperty 断言                          |
| PropertySchema（骨架） | 类 annotation（JSON 序列化，SHACL-like）         |

设计说明：
- IRI 命名空间隔离：每个本体独立 IRI，互不污染
- HermiT 推理机不校验 PropertySchema（仅 annotation），但记录供人工审阅与未来 SHACL 扩展
- owlready2 对中文 local name 兼容良好，Protégé 可正确显示
- 每次构建创建独立 World，避免多次调用累积数据
- 关系属性（Relation.properties）v1 暂不导出，避免 ObjectProperty 断言的 reification 复杂度

序列化格式：RDF/XML（Protégé 默认支持的格式）
"""

import os
import json
import logging
import re
from typing import List, Optional, Dict, Any, Tuple

import owlready2
from owlready2 import owl, types

from models import (
    OntologyModel, ConceptType, Entity, Relation, Property,
    EntityType, EntityTypeRelation, RelationType
)

logger = logging.getLogger("ontology-service")

# 全局默认 IRI base（每个本体在此基础上 + {id}# 隔离）
DEFAULT_IRI_BASE = "http://intelligent-assessment.local/ontology/"

# 默认输出目录（与 main.py DATA_DIR 对齐）
DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "ontologies"
)


# ──────────────────────────────────────────────────────────────
# IRI local name 处理
# ──────────────────────────────────────────────────────────────

# PN_LOCAL 子集：保留 ASCII 字母数字下划线 + 中文
_INVALID_LOCAL_CHAR = re.compile(r'[^a-zA-Z0-9_\u4e00-\u9fff]')


def _sanitize_local_name(name: str) -> str:
    """将任意字符串转为合法的 IRI local name（PN_LOCAL 子集）。

    规则：
    - 保留中文（\\u4e00-\\u9fff）与 ASCII 字母数字下划线
    - 其他字符替换为下划线
    - 不能以数字开头（前缀下划线）
    - 空字符串返回 'unnamed'

    owlready2 对中文 local name 兼容良好，Protégé 也能正确显示。
    """
    if not name:
        return "unnamed"
    sanitized = _INVALID_LOCAL_CHAR.sub('_', name)
    if not sanitized:
        return "unnamed"
    if sanitized[0].isdigit():
        sanitized = "_" + sanitized
    return sanitized


def _unique_local_name(name: str, used: set) -> str:
    """生成唯一的 local name，冲突时追加 _2 _3 ..."""
    base = _sanitize_local_name(name)
    if base not in used:
        used.add(base)
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    final = f"{base}_{i}"
    used.add(final)
    return final


# ──────────────────────────────────────────────────────────────
# 数据类型转换
# ──────────────────────────────────────────────────────────────

def _convert_value(value: Any, data_type: str) -> Optional[Any]:
    """根据 data_type 将属性值转换为 OWL 兼容类型。

    - number → float（转换失败降级为 string）
    - date → str（OWL 用 xsd:string，Phase 2 不引入 xsd:dateTime 复杂度）
    - enum / string → str
    """
    if value is None:
        return None
    if data_type == "number":
        try:
            return float(value)
        except (ValueError, TypeError):
            return str(value)
    # date / enum / string / 未知类型统一字符串化
    if isinstance(value, str):
        return value
    return str(value)


def _data_type_range(data_type: str) -> Any:
    """data_type → OWL range 类。"""
    if data_type == "number":
        return float
    # date / enum / string 统一为 xsd:string
    return str


# ──────────────────────────────────────────────────────────────
# OwlBuilder 主体
# ──────────────────────────────────────────────────────────────

class OwlBuilder:
    """Pydantic 模型 → OWL 2 本体映射器。

    用法：
        builder = OwlBuilder()
        onto = builder.build(ont, concepts, entities, relations)
        builder.save(onto, "output.owl")

    或一步到位：
        path = builder.build_and_save(ont, concepts, entities, relations)
    """

    def __init__(self, iri_base: str = DEFAULT_IRI_BASE,
                 output_dir: str = DEFAULT_OUTPUT_DIR):
        self.iri_base = iri_base
        self.output_dir = output_dir

    # ── IRI 与路径 ──

    def _build_iri(self, ontology_id: str) -> str:
        """构建本体 IRI：{iri_base}{ontology_id}#"""
        return f"{self.iri_base}{ontology_id}#"

    def _default_path(self, ontology_id: str) -> str:
        """默认输出路径：{output_dir}/ontology_{id}.owl"""
        return os.path.join(self.output_dir, f"ontology_{ontology_id}.owl")

    # ── 核心构建 ──

    def build(self, ont: OntologyModel,
              concepts: List[ConceptType],
              entities: List[Entity],
              relations: List[Relation],
              entity_type_relations: Optional[List[EntityTypeRelation]] = None) -> owlready2.Ontology:
        """构建 OWL 本体对象（内存中的 owlready2.Ontology）。

        v3 改造：
        - EntityType 自带层级（parent_entity_type_id），OWL 中映射为 subClassOf
        - concepts 参数兼容 v3（与 ont.entity_types 同源），v2 实体类型仍 subClassOf EntityType
        - 新增 entity_type_relations → ObjectProperty（类型间关系，domain/range 限定）

        Args:
            ont: 本体模型（含 entity_types / relation_types）
            concepts: 实体类型列表（类型层）；v3 中与 ont.entity_types 同源
            entities: 实体列表（实例层）
            relations: 关系列表（实例间）
            entity_type_relations: 实体类型间关系列表（v3 新增，可选）

        Returns:
            owlready2.Ontology 对象，可继续操作或 save
        """
        # 每次构建创建独立 World，避免累积
        world = owlready2.World()
        iri = self._build_iri(ont.id)
        onto = world.get_ontology(iri)

        # 收集已用 local name，避免 class/individual 重名冲突
        used_names: set = set()

        with onto:
            # 1. 创建 annotation property（用于 PropertySchema）
            #    全局唯一，所有 ConceptType 共用
            schema_ann = types.new_class("propertySchema", (owl.AnnotationProperty,))
            schema_ann.comment = [
                "属性骨架（JSON）：descriptive/metric 分类、data_type、unit、required 等。"
                "HermiT 不校验 annotation，仅记录供人工审阅与未来 SHACL 扩展。"
            ]

            # 2. EntityType → owl:Class（v3：自带层级 + property_schema）
            #    按 et.id 建索引，供 Entity rdf:type 和 parent 层级引用
            #    v3 中 ont.entity_types 即完整类型层（含层级 + 属性骨架）
            et_classes: Dict[str, Any] = {}     # et.id -> owl:Class
            et_by_name: Dict[str, Any] = {}     # et.name -> owl:Class（供 v2 实体类型 subClassOf 引用）
            for et in ont.entity_types:
                if not et.name:
                    continue
                cname = _unique_local_name(et.name, used_names)
                cls = types.new_class(cname, (owl.Thing,))
                cls.label = [et.name]
                comments = []
                if et.color:
                    comments.append(f"颜色: {et.color}")
                if et.description:
                    comments.append(et.description)
                if et.source_snippet:
                    comments.append(f"来源: {et.source_snippet}")
                if comments:
                    cls.comment = comments
                # v3：PropertySchema 作为 annotation
                if et.property_schema:
                    schema_json = json.dumps(
                        [ps.dict() for ps in et.property_schema],
                        ensure_ascii=False
                    )
                    cls.propertySchema = [schema_json]
                et_classes[et.id] = cls
                et_by_name[et.name] = cls

            # v3：设置 EntityType 层级（parent_entity_type_id → subClassOf）
            for et in ont.entity_types:
                if et.parent_entity_type_id:
                    parent_cls = et_classes.get(et.parent_entity_type_id)
                    if parent_cls and parent_cls is not et_classes.get(et.id):
                        cls = et_classes[et.id]
                        # 追加父类（OWL 允许多重继承）
                        if parent_cls not in cls.is_a:
                            cls.is_a = tuple(cls.is_a) + (parent_cls,)

            # 3. ConceptType（实体类型）→ owl:Class (subClassOf EntityType)
            #    v3 兼容：concepts 与 ont.entity_types 同源时跳过（已在 step 2 创建）
            #    v2 兼容：concepts 不在 entity_types 中时按原逻辑创建
            concept_classes: Dict[str, Any] = {}
            et_ids = {et.id for et in ont.entity_types}
            for c in concepts:
                if c.id in et_ids:
                    # v3：已在 step 2 创建，直接引用
                    concept_classes[c.id] = et_classes[c.id]
                    continue
                # v2：实体类型不在本体模型中，创建新类 subClassOf EntityType
                cname = _unique_local_name(c.name, used_names)
                parents: List[Any] = []
                if c.entity_type and c.entity_type in et_by_name:
                    parents.append(et_by_name[c.entity_type])
                if not parents:
                    parents.append(owl.Thing)
                cls = types.new_class(cname, tuple(parents))
                cls.label = [c.name]
                comments = []
                if c.description:
                    comments.append(c.description)
                if c.source_snippet:
                    comments.append(f"来源: {c.source_snippet}")
                if comments:
                    cls.comment = comments
                # PropertySchema 作为 annotation（JSON 序列化）
                if c.property_schema:
                    schema_json = json.dumps(
                        [ps.dict() for ps in c.property_schema],
                        ensure_ascii=False
                    )
                    cls.propertySchema = [schema_json]
                concept_classes[c.id] = cls

            # 4. DatatypeProperty 缓存（按属性名去重，跨实体共享）
            data_props: Dict[str, Any] = {}
            # 5. ObjectProperty 缓存（按 relation_type 去重，类型层+实例层共用）
            obj_props: Dict[str, Any] = {}

            # 5.5 EntityTypeRelation → ObjectProperty domain/range（v3 新增：类型间关系）
            #     在实例断言前设置 domain/range，使同一 ObjectProperty 带类型约束
            if entity_type_relations:
                for etr in entity_type_relations:
                    src_cls = et_classes.get(etr.source_entity_type_id)
                    tgt_cls = et_classes.get(etr.target_entity_type_id)
                    if not src_cls or not tgt_cls:
                        continue
                    op = _get_or_create_obj_prop(etr.relation_type, obj_props)
                    # 设置 domain/range（仅首次设置生效，避免覆盖）
                    if not op.domain:
                        op.domain = [src_cls]
                    if not op.range:
                        op.range = [tgt_cls]

            # 6. Entity（实体）→ owl:NamedIndividual
            ent_individuals: Dict[str, Any] = {}
            for e in entities:
                iname = _unique_local_name(e.name, used_names)
                # rdf:type 指向 ConceptType class（无实体类型则 owl:Thing 兜底）
                parent_cls = concept_classes.get(e.instance_of, owl.Thing)
                ind = parent_cls(name=iname)
                ind.label = [e.name]
                comments = []
                if e.source_snippet:
                    comments.append(f"来源: {e.source_snippet}")
                if e.is_primary:
                    comments.append("主要实体")
                if comments:
                    ind.comment = comments
                ent_individuals[e.id] = ind

                # 设置结构化属性（DatatypeProperty 断言）
                for p in e.properties:
                    if p.value is None:
                        continue
                    dp = _get_or_create_data_prop(p, data_props)
                    val = _convert_value(p.value, p.data_type)
                    if val is None:
                        continue
                    _append_value(ind, dp, val)

            # 7. Relation（关系）→ ObjectProperty 断言
            for r in relations:
                src_ind = ent_individuals.get(r.source_id)
                tgt_ind = ent_individuals.get(r.target_id)
                if not src_ind or not tgt_ind:
                    # 实体不存在则跳过（防御性）
                    continue
                op = _get_or_create_obj_prop(r.relation_type, obj_props)
                _append_value(src_ind, op, tgt_ind)

        # 设置本体元信息（owl:Ontology 级 annotation）
        # 注意：owlready2 metadata 仅支持预定义 annotation properties
        # （comment / label / seeAlso / isDefinedBy / versionInfo 等），
        # 不能用任意属性名，否则抛 ValueError
        if ont.description:
            onto.metadata.comment.append(ont.description)
        if ont.version:
            onto.metadata.versionInfo.append(ont.version)
        # 标记生成时间与源 schema_version（追加到 comment）
        from datetime import datetime
        onto.metadata.comment.append(
            f"generated_at={datetime.now().isoformat(timespec='seconds')} "
            f"schema_version={ont.schema_version}"
        )

        logger.info(
            "OWL 构建完成: ontology_id=%s, entity_types=%d, concepts=%d, "
            "entities=%d, relations=%d",
            ont.id, len(ont.entity_types), len(concepts),
            len(entities), len(relations)
        )
        return onto

    # ── 序列化 ──

    def save(self, onto: owlready2.Ontology, file_path: str) -> str:
        """保存 OWL 本体到 RDF/XML 文件。

        Args:
            onto: build() 返回的 Ontology 对象
            file_path: 输出路径

        Returns:
            实际保存路径
        """
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        onto.save(file=file_path, format="rdfxml")
        logger.info("OWL 已保存: %s", file_path)
        return file_path

    def build_and_save(self, ont: OntologyModel,
                       concepts: List[ConceptType],
                       entities: List[Entity],
                       relations: List[Relation],
                       file_path: Optional[str] = None,
                       entity_type_relations: Optional[List[EntityTypeRelation]] = None) -> str:
        """一步到位：构建 + 保存。

        Args:
            ont: 本体模型
            concepts: 实体类型列表
            entities: 实体列表
            relations: 关系列表
            file_path: 指定输出路径；None 则用默认 {output_dir}/ontology_{id}.owl
            entity_type_relations: 实体类型间关系列表（v3 新增，可选）

        Returns:
            保存路径
        """
        onto = self.build(ont, concepts, entities, relations, entity_type_relations)
        if file_path is None:
            file_path = self._default_path(ont.id)
        return self.save(onto, file_path)


# ──────────────────────────────────────────────────────────────
# 模块级辅助函数（在 build() 的 `with onto:` 块内调用，
# types.new_class 自动注册到当前激活的 ontology）
# ──────────────────────────────────────────────────────────────

def _get_or_create_data_prop(prop: Property,
                              cache: Dict[str, Any]) -> Any:
    """获取或创建 DatatypeProperty（按 sanitized 属性名缓存）。

    必须在 `with ontology:` 块内调用，types.new_class 会注册到当前 ontology。

    命名策略：local name 加 `dp_` 前缀，避免与 ObjectProperty 同名冲突
    （OWL 2 DL 不允许同一 IRI 既是 DatatypeProperty 又是 ObjectProperty）。
    rdfs:label 保留原文名，Protégé 中显示中文属性名。
    """
    # 加 dp_ 前缀避免与 ObjectProperty 同名冲突
    name = "dp_" + _sanitize_local_name(prop.name)
    if name in cache:
        return cache[name]
    dp = types.new_class(name, (owl.DatatypeProperty,))
    dp.label = [prop.name]
    dp.range = [_data_type_range(prop.data_type)]
    # 在 comment 中记录 unit / category（OWL 不强制，仅元信息）
    meta = []
    if prop.unit:
        meta.append(f"unit={prop.unit}")
    if prop.category:
        meta.append(f"category={prop.category}")
    if meta:
        dp.comment = ["; ".join(meta)]
    cache[name] = dp
    return dp


def _get_or_create_obj_prop(rel_type: str,
                             cache: Dict[str, Any]) -> Any:
    """获取或创建 ObjectProperty（按 sanitized 关系类型名缓存）。

    必须在 `with ontology:` 块内调用。

    命名策略：local name 加 `op_` 前缀，避免与 DatatypeProperty 同名冲突。
    rdfs:label 保留原文名，Protégé 中显示中文关系名。
    """
    # 加 op_ 前缀避免与 DatatypeProperty 同名冲突
    name = "op_" + _sanitize_local_name(rel_type)
    if name in cache:
        return cache[name]
    op = types.new_class(name, (owl.ObjectProperty,))
    op.label = [rel_type]
    cache[name] = op
    return op


def _append_value(ind: Any, prop: Any, value: Any) -> None:
    """向 individual 的某属性追加值（兼容首次设置与多值）。"""
    python_name = prop.python_name
    current = getattr(ind, python_name, None)
    if current is None:
        setattr(ind, python_name, [value])
    elif isinstance(current, list):
        current.append(value)
    else:
        setattr(ind, python_name, [current, value])


# ──────────────────────────────────────────────────────────────
# 便捷函数（供 main.py 调用）
# ──────────────────────────────────────────────────────────────

_default_builder: Optional[OwlBuilder] = None


def get_owl_builder() -> OwlBuilder:
    """获取默认 OwlBuilder 单例（懒加载）。"""
    global _default_builder
    if _default_builder is None:
        _default_builder = OwlBuilder()
    return _default_builder


def export_ontology_to_owl(ont: OntologyModel,
                            concepts: List[ConceptType],
                            entities: List[Entity],
                            relations: List[Relation],
                            file_path: Optional[str] = None,
                            entity_type_relations: Optional[List[EntityTypeRelation]] = None) -> str:
    """便捷接口：将本体导出为 OWL 文件。

    供 main.py 的 _generate_formal_ontology（Phase 5 集成）或
    /ontology/{id}/owl endpoint 调用。

    v3：新增 entity_type_relations 参数，导出类型间关系为带 domain/range 的 ObjectProperty。
    """
    builder = get_owl_builder()
    return builder.build_and_save(
        ont, concepts, entities, relations, file_path, entity_type_relations
    )
