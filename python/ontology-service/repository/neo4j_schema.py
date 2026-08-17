"""Neo4j Schema 初始化：唯一约束 + 索引（幂等执行）。

数据模型映射（与 docs/OWL2-Neo4j-存储层重构方案.md 第三节对齐）：

节点标签：
  :Ontology    - 本体元信息（id, name, description, version, status, schema_version）
  :EntityType  - 本体模型实体类型（id, ontology_id, name, color）
  :Concept     - 实体类型/类型层（id, ontology_id, name, entity_type, description, color, property_schema_json）
  :Entity      - 实体/实例层（id, ontology_id, name, instance_of, is_primary, properties_json）
  :Relation    - 关系（id, ontology_id, relation_type, weight, properties_json）
  :Template    - 本体模板（id, name, data_json）
  :BuildJob    - 构建任务（id, name, status, data_json）

关系类型：
  (:Ontology)-[:HAS_ENTITY_TYPE]->(:EntityType)
  (:Ontology)-[:HAS_CONCEPT]->(:Concept)
  (:Ontology)-[:HAS_ENTITY]->(:Entity)
  (:Ontology)-[:HAS_RELATION]->(:Relation)
  (:Entity)-[:INSTANCE_OF_CONCEPT]->(:Concept)
  (:Relation)-[:SOURCE]->(:Entity)
  (:Relation)-[:TARGET]->(:Entity)

设计说明：
- Property 嵌在 Entity/Relation 的 properties_json（JSON 字符串），v1 不拆独立节点
- PropertySchema 嵌在 Concept 的 property_schema_json
- BuildJob/Template 用 data_json 存储完整序列化数据（避免拆字段）
- 所有约束/索引幂等创建（IF NOT EXISTS），可重复执行
"""
import logging
from typing import List, Tuple
from neo4j import Driver

logger = logging.getLogger("ontology-service")


# ──────────────────────────────────────────────────────────────
# Schema 定义
# ──────────────────────────────────────────────────────────────

# 唯一约束（7个）：确保实体 ID 全局唯一
UNIQUE_CONSTRAINTS: List[Tuple[str, str, str]] = [
    # (constraint_name, label, property)
    ("ont_id_unique",        "Ontology",   "id"),
    ("entity_type_id_unique","EntityType", "id"),
    ("concept_id_unique",    "Concept",    "id"),
    ("entity_id_unique",     "Entity",     "id"),
    ("relation_id_unique",   "Relation",   "id"),
    ("template_id_unique",   "Template",   "id"),
    ("build_job_id_unique",  "BuildJob",   "id"),
]

# 索引（10个）：加速常用查询路径
INDEXES: List[Tuple[str, str, str]] = [
    # (index_name, label, property)
    ("ont_name_idx",            "Ontology",   "name"),
    ("entity_type_ont_idx",     "EntityType", "ontology_id"),
    ("entity_type_name_idx",    "EntityType", "name"),
    ("concept_ont_idx",         "Concept",    "ontology_id"),
    ("concept_name_idx",        "Concept",    "name"),
    ("entity_ont_idx",          "Entity",     "ontology_id"),
    ("entity_name_idx",         "Entity",     "name"),
    ("entity_instance_of_idx",  "Entity",     "instance_of"),
    ("relation_ont_idx",        "Relation",   "ontology_id"),
    ("relation_type_idx",       "Relation",   "relation_type"),
]


def init_schema(driver: Driver) -> None:
    """初始化 Neo4j schema：创建所有唯一约束和索引（幂等）。

    Args:
        driver: Neo4j Driver 实例
    """
    with driver.session() as session:
        # 创建唯一约束
        for constraint_name, label, prop in UNIQUE_CONSTRAINTS:
            cypher = (
                f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
            try:
                session.run(cypher)
                logger.debug("约束已创建: %s (%s.%s)", constraint_name, label, prop)
            except Exception as e:
                logger.warning("创建约束失败 %s: %s", constraint_name, e)

        # 创建索引
        for index_name, label, prop in INDEXES:
            cypher = (
                f"CREATE INDEX {index_name} IF NOT EXISTS "
                f"FOR (n:{label}) ON (n.{prop})"
            )
            try:
                session.run(cypher)
                logger.debug("索引已创建: %s (%s.%s)", index_name, label, prop)
            except Exception as e:
                logger.warning("创建索引失败 %s: %s", index_name, e)

    logger.info(
        "Neo4j schema 初始化完成: %d 唯一约束 + %d 索引",
        len(UNIQUE_CONSTRAINTS), len(INDEXES)
    )


def drop_schema(driver: Driver) -> None:
    """删除所有约束和索引（仅用于测试/重置）。

    Args:
        driver: Neo4j Driver 实例
    """
    with driver.session() as session:
        for constraint_name, label, prop in UNIQUE_CONSTRAINTS:
            try:
                session.run(f"DROP CONSTRAINT {constraint_name} IF EXISTS")
            except Exception:
                pass

        for index_name, label, prop in INDEXES:
            try:
                session.run(f"DROP INDEX {index_name} IF EXISTS")
            except Exception:
                pass

    logger.info("Neo4j schema 已清空")


def get_schema_info(driver: Driver) -> dict:
    """获取当前 schema 状态（约束 + 索引数量）。"""
    with driver.session() as session:
        constraints = session.run("SHOW CONSTRAINTS").data()
        indexes = session.run("SHOW INDEXES").data()
        return {
            "constraints_count": len(constraints),
            "indexes_count": len(indexes),
            "constraints": [c.get("name", "") for c in constraints],
            "indexes": [i.get("name", "") for i in indexes],
        }
