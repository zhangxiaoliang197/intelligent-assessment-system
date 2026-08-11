"""Neo4jRepository：基于 Neo4j 图数据库的存储实现（Phase 3）。

实现 OntologyRepository ABC 的全部方法，用 Cypher 替代 Python 遍历。

数据模型映射见 repository/neo4j_schema.py 模块文档。

设计要点：
- Property 嵌在 Entity/Relation 节点的 properties_json（JSON 字符串），v1 不拆独立节点
- PropertySchema 嵌在 Concept 节点的 property_schema_json
- BuildJob/Template 用 data_json 存储完整序列化数据
- save_ontology_full 方法：单事务内删旧→全量写入（迁移脚本用）
- save_ontology(ontology_id) 为 no-op：Neo4j 每次操作即时持久化，无需批量保存
  （Phase 4 迁移 main.py 时，_generate_formal_ontology 改调 save_ontology_full）
- find_shortest_path 用 Cypher shortestPath 替代 Python BFS
- get_graph_data 用 Cypher 聚合 nodes/links
- datetime 统一 ISO 字符串存储，读写一致
"""
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from neo4j import GraphDatabase, Driver

from models import (
    OntologyModel, ConceptType, Entity, Relation, Property,
    PropertyHistoryEntry, PropertySchema, EntityType, RelationType,
    TemplateModel, TemplateConceptSchema, BuildJob
)
from .base import OntologyRepository
from .neo4j_schema import init_schema

logger = logging.getLogger("ontology-service")


# ──────────────────────────────────────────────────────────────
# 序列化辅助
# ──────────────────────────────────────────────────────────────

def _dt(value: Any) -> str:
    """datetime → ISO 字符串；None → ''。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _parse_dt(value: Any) -> datetime:
    """ISO 字符串 → datetime；失败返回 now()。"""
    if value is None or value == "":
        return datetime.now()
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return datetime.now()


def _entity_to_props(e: Entity) -> dict:
    """Entity Pydantic → Neo4j 节点属性 dict。"""
    return {
        "id": e.id,
        "ontology_id": e.ontology_id,
        "name": e.name,
        "instance_of": e.instance_of,
        "type": e.type,
        "is_primary": e.is_primary,
        "properties_json": json.dumps([p.dict() for p in e.properties],
                                       ensure_ascii=False, default=str),
        "bindings_json": json.dumps(e.bindings, ensure_ascii=False, default=str),
        "source_snippet": e.source_snippet,
        "create_time": _dt(e.create_time),
        "update_time": _dt(e.update_time),
    }


def _props_to_entity(props: dict) -> Entity:
    """Neo4j 节点属性 dict → Entity Pydantic。"""
    properties = []
    pj = props.get("properties_json", "[]")
    if pj:
        try:
            properties = [Property(**p) for p in json.loads(pj)]
        except (json.JSONDecodeError, Exception):
            properties = []
    bindings = {}
    bj = props.get("bindings_json", "{}")
    if bj:
        try:
            bindings = json.loads(bj)
        except (json.JSONDecodeError, Exception):
            bindings = {}
    return Entity(
        id=props["id"],
        ontology_id=props.get("ontology_id", ""),
        name=props.get("name", ""),
        instance_of=props.get("instance_of", ""),
        type=props.get("type", ""),
        is_primary=bool(props.get("is_primary", False)),
        properties=properties,
        bindings=bindings,
        source_snippet=props.get("source_snippet", ""),
        create_time=_parse_dt(props.get("create_time")),
        update_time=_parse_dt(props.get("update_time")),
    )


def _concept_to_props(c: ConceptType) -> dict:
    """ConceptType Pydantic → Neo4j 节点属性 dict。"""
    return {
        "id": c.id,
        "ontology_id": c.ontology_id,
        "name": c.name,
        "entity_type": c.entity_type,
        "description": c.description,
        "color": c.color or "",
        "property_schema_json": json.dumps(
            [ps.dict() for ps in c.property_schema],
            ensure_ascii=False, default=str
        ),
        "source_snippet": c.source_snippet,
        "create_time": _dt(c.create_time),
        "update_time": _dt(c.update_time),
    }


def _props_to_concept(props: dict) -> ConceptType:
    """Neo4j 节点属性 dict → ConceptType Pydantic。"""
    property_schema = []
    psj = props.get("property_schema_json", "[]")
    if psj:
        try:
            property_schema = [PropertySchema(**ps) for ps in json.loads(psj)]
        except (json.JSONDecodeError, Exception):
            property_schema = []
    return ConceptType(
        id=props["id"],
        ontology_id=props.get("ontology_id", ""),
        name=props.get("name", ""),
        entity_type=props.get("entity_type", ""),
        description=props.get("description", ""),
        color=props.get("color", "") or None,
        property_schema=property_schema,
        source_snippet=props.get("source_snippet", ""),
        create_time=_parse_dt(props.get("create_time")),
        update_time=_parse_dt(props.get("update_time")),
    )


def _relation_to_props(r: Relation) -> dict:
    """Relation Pydantic → Neo4j 节点属性 dict。"""
    return {
        "id": r.id,
        "ontology_id": r.ontology_id,
        "relation_type": r.relation_type,
        "source_id": r.source_id,
        "target_id": r.target_id,
        "weight": float(r.weight),
        "properties_json": json.dumps([p.dict() for p in r.properties],
                                       ensure_ascii=False, default=str),
        "bindings_json": json.dumps(r.bindings, ensure_ascii=False, default=str),
        "source_snippet": r.source_snippet,
        "create_time": _dt(r.create_time),
    }


def _props_to_relation(props: dict) -> Relation:
    """Neo4j 节点属性 dict → Relation Pydantic。"""
    properties = []
    pj = props.get("properties_json", "[]")
    if pj:
        try:
            properties = [Property(**p) for p in json.loads(pj)]
        except (json.JSONDecodeError, Exception):
            properties = []
    bindings = {}
    bj = props.get("bindings_json", "{}")
    if bj:
        try:
            bindings = json.loads(bj)
        except (json.JSONDecodeError, Exception):
            bindings = {}
    return Relation(
        id=props["id"],
        ontology_id=props.get("ontology_id", ""),
        source_id=props.get("source_id", ""),
        target_id=props.get("target_id", ""),
        relation_type=props.get("relation_type", ""),
        weight=props.get("weight", 1.0),
        properties=properties,
        bindings=bindings,
        source_snippet=props.get("source_snippet", ""),
        create_time=_parse_dt(props.get("create_time")),
    )


def _ontology_to_props(ont: OntologyModel) -> dict:
    """OntologyModel Pydantic → Neo4j 节点属性 dict。"""
    return {
        "id": ont.id,
        "name": ont.name,
        "description": ont.description,
        "version": ont.version,
        "status": ont.status,
        "is_default": ont.is_default,
        "schema_version": ont.schema_version,
        "entity_types_json": json.dumps(
            [et.dict() for et in ont.entity_types],
            ensure_ascii=False, default=str
        ),
        "relation_types_json": json.dumps(
            [rt.dict() for rt in ont.relation_types],
            ensure_ascii=False, default=str
        ),
        "create_time": _dt(ont.create_time),
        "update_time": _dt(ont.update_time),
    }


def _props_to_ontology(props: dict) -> OntologyModel:
    """Neo4j 节点属性 dict → OntologyModel Pydantic。"""
    entity_types = []
    etj = props.get("entity_types_json", "[]")
    if etj:
        try:
            entity_types = [EntityType(**et) for et in json.loads(etj)]
        except (json.JSONDecodeError, Exception):
            entity_types = []
    relation_types = []
    rtj = props.get("relation_types_json", "[]")
    if rtj:
        try:
            relation_types = [RelationType(**rt) for rt in json.loads(rtj)]
        except (json.JSONDecodeError, Exception):
            relation_types = []
    return OntologyModel(
        id=props["id"],
        name=props.get("name", ""),
        description=props.get("description", ""),
        version=props.get("version", "1.0.0"),
        status=props.get("status", "活跃"),
        is_default=bool(props.get("is_default", False)),
        schema_version=props.get("schema_version", 2),
        entity_types=entity_types,
        relation_types=relation_types,
        create_time=_parse_dt(props.get("create_time")),
        update_time=_parse_dt(props.get("update_time")),
    )


def _template_to_props(t: TemplateModel) -> dict:
    """TemplateModel → Neo4j 属性 dict（整体 data_json + 常用查询字段）。"""
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "version": t.version,
        "source_ontology_id": t.source_ontology_id or "",
        "is_builtin": t.is_builtin,
        "data_json": json.dumps(t.dict(), ensure_ascii=False, default=str),
        "create_time": _dt(t.create_time),
        "update_time": _dt(t.update_time),
    }


def _props_to_template(props: dict) -> TemplateModel:
    """Neo4j 属性 dict → TemplateModel。"""
    dj = props.get("data_json", "{}")
    if dj:
        try:
            data = json.loads(dj)
            return TemplateModel(**data)
        except (json.JSONDecodeError, Exception):
            pass
    return TemplateModel(
        id=props.get("id", ""),
        name=props.get("name", ""),
        description=props.get("description", ""),
        version=props.get("version", "1.0.0"),
        source_ontology_id=props.get("source_ontology_id") or None,
        is_builtin=bool(props.get("is_builtin", False)),
        create_time=_parse_dt(props.get("create_time")),
        update_time=_parse_dt(props.get("update_time")),
    )


def _buildjob_to_props(j: BuildJob) -> dict:
    """BuildJob → Neo4j 属性 dict（整体 data_json + 常用查询字段）。"""
    return {
        "id": j.id,
        "name": j.name,
        "status": j.status,
        "step": j.step,
        "ontology_id": j.ontology_id or "",
        "data_json": json.dumps(j.dict(), ensure_ascii=False, default=str),
        "create_time": _dt(j.create_time),
        "update_time": _dt(j.update_time),
    }


def _props_to_buildjob(props: dict) -> BuildJob:
    """Neo4j 属性 dict → BuildJob。"""
    dj = props.get("data_json", "{}")
    if dj:
        try:
            data = json.loads(dj)
            return BuildJob(**data)
        except (json.JSONDecodeError, Exception):
            pass
    return BuildJob(
        id=props.get("id", ""),
        name=props.get("name", ""),
        status=props.get("status", "draft"),
        step=props.get("step", 0),
        ontology_id=props.get("ontology_id") or None,
        create_time=_parse_dt(props.get("create_time")),
        update_time=_parse_dt(props.get("update_time")),
    )


# ──────────────────────────────────────────────────────────────
# Neo4jRepository 主体
# ──────────────────────────────────────────────────────────────

class Neo4jRepository(OntologyRepository):
    """基于 Neo4j 的本体存储实现。

    所有操作直接读写 Neo4j，无内存缓存。
    save_ontology(ontology_id) 为 no-op（Neo4j 即时持久化）。
    save_ontology_full() 供迁移脚本批量写入。
    """

    def __init__(self, uri: str = None, user: str = None,
                 password: str = None, database: str = None):
        """初始化 Neo4j 连接。

        Args:
            uri: bolt://host:port（默认从 config.py 读取）
            user: 用户名（默认 neo4j）
            password: 密码
            database: 数据库名（默认 neo4j）
        """
        # 延迟 import config 避免循环依赖
        if uri is None or user is None or password is None:
            import config
            uri = uri or config.NEO4J_URI
            user = user or config.NEO4J_USER
            password = password or config.NEO4J_PASSWORD
            database = database or config.NEO4J_DATABASE

        self._uri = uri
        self._database = database
        self._driver: Optional[Driver] = GraphDatabase.driver(
            uri, auth=(user, password)
        )
        logger.info("Neo4jRepository 初始化: uri=%s, db=%s", uri, database)

    @property
    def _session(self):
        """创建新 session（每次操作用独立 session）。"""
        return self._driver.session(database=self._database)

    # ── 生命周期 ──

    def load(self) -> None:
        """校验连接 + 初始化 schema。"""
        try:
            with self._session as s:
                s.run("RETURN 1").consume()
            init_schema(self._driver)
            logger.info("Neo4jRepository 连接成功，schema 已初始化")
        except Exception as e:
            logger.error("Neo4j 连接失败: %s", e)
            raise

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            logger.info("Neo4jRepository 连接已关闭")

    # ── Ontology CRUD ──

    def list_ontologies(self) -> List[OntologyModel]:
        with self._session as s:
            result = s.run("MATCH (o:Ontology) RETURN o ORDER BY o.create_time")
            return [_props_to_ontology(r["o"]) for r in result]

    def get_ontology(self, ontology_id: str) -> Optional[OntologyModel]:
        with self._session as s:
            result = s.run(
                "MATCH (o:Ontology {id: $oid}) RETURN o",
                oid=ontology_id
            )
            r = result.single()
            return _props_to_ontology(r["o"]) if r else None

    def save_ontology(self, ontology_id: str) -> None:
        """no-op：Neo4j 每次操作即时持久化。

        Phase 4 迁移 main.py 后，_generate_formal_ontology 改调
        save_ontology_full 实现批量写入。
        """
        pass

    def save_index(self) -> None:
        """no-op：Neo4j 无索引文件概念。"""
        pass

    def delete_ontology(self, ontology_id: str) -> None:
        """删除本体及其所有关联节点（EntityType/Concept/Entity/Relation）。"""
        with self._session as s:
            # DETACH DELETE 级联删除所有关联节点和关系
            s.run(
                """
                MATCH (o:Ontology {id: $oid})
                OPTIONAL MATCH (o)--(related)
                DETACH DELETE o, related
                """,
                oid=ontology_id
            )
        logger.info("已删除本体: %s", ontology_id)

    def set_default_ontology(self, ontology_id: str) -> None:
        with self._session as s:
            s.run("MATCH (o:Ontology) SET o.is_default = False")
            s.run(
                "MATCH (o:Ontology {id: $oid}) SET o.is_default = True",
                oid=ontology_id
            )

    def get_default_ontology(self) -> Optional[OntologyModel]:
        with self._session as s:
            result = s.run("MATCH (o:Ontology {is_default: True}) RETURN o")
            r = result.single()
            return _props_to_ontology(r["o"]) if r else None

    def get_ontology_summary(self, ont: OntologyModel) -> Dict[str, Any]:
        oid = ont.id
        with self._session as s:
            ent_count = s.run(
                "MATCH (:Entity {ontology_id: $oid}) RETURN count(*) AS c",
                oid=oid
            ).single()["c"]
            rel_count = s.run(
                "MATCH (:Relation {ontology_id: $oid}) RETURN count(*) AS c",
                oid=oid
            ).single()["c"]
            concept_count = s.run(
                "MATCH (:Concept {ontology_id: $oid}) RETURN count(*) AS c",
                oid=oid
            ).single()["c"]
        return {
            "id": ont.id,
            "name": ont.name,
            "entities_count": ent_count,
            "relations_count": rel_count,
            "concepts_count": concept_count,
            "create_time": _dt(ont.create_time),
        }

    # ── 批量写入（迁移脚本用）──

    def save_ontology_full(self, ont: OntologyModel,
                            concepts: List[ConceptType],
                            entities: List[Entity],
                            relations: List[Relation]) -> None:
        """单事务内全量写入一个本体（删旧→写新）。

        供迁移脚本和 _generate_formal_ontology 调用。
        """
        oid = ont.id
        with self._session as s:
            # 1. 删旧（含关联节点）
            s.run(
                """
                MATCH (o:Ontology {id: $oid})
                OPTIONAL MATCH (o)--(related)
                DETACH DELETE o, related
                """,
                oid=oid
            )

            # 2. 写 Ontology 节点
            ont_props = _ontology_to_props(ont)
            s.run(
                "CREATE (o:Ontology) SET o = $props",
                props=ont_props
            )

            # 3. 写 EntityType 节点 + HAS_ENTITY_TYPE 边
            for et in ont.entity_types:
                et_props = {
                    "id": f"et_{oid}_{et.name}",
                    "ontology_id": oid,
                    "name": et.name,
                    "color": et.color or "",
                }
                s.run(
                    """
                    CREATE (et:EntityType) SET et = $props
                    WITH et
                    MATCH (o:Ontology {id: $oid})
                    CREATE (o)-[:HAS_ENTITY_TYPE]->(et)
                    """,
                    props=et_props, oid=oid
                )

            # 4. 写 Concept 节点 + HAS_CONCEPT 边
            for c in concepts:
                c_props = _concept_to_props(c)
                s.run(
                    """
                    CREATE (c:Concept) SET c = $props
                    WITH c
                    MATCH (o:Ontology {id: $oid})
                    CREATE (o)-[:HAS_CONCEPT]->(c)
                    """,
                    props=c_props, oid=oid
                )

            # 5. 写 Entity 节点 + HAS_ENTITY 边 + INSTANCE_OF_CONCEPT 边
            for e in entities:
                e_props = _entity_to_props(e)
                s.run(
                    """
                    CREATE (e:Entity) SET e = $props
                    WITH e
                    MATCH (o:Ontology {id: $oid})
                    CREATE (o)-[:HAS_ENTITY]->(e)
                    """,
                    props=e_props, oid=oid
                )
                # INSTANCE_OF_CONCEPT 边（如果概念存在）
                if e.instance_of:
                    s.run(
                        """
                        MATCH (e:Entity {id: $eid}), (c:Concept {id: $cid})
                        CREATE (e)-[:INSTANCE_OF_CONCEPT]->(c)
                        """,
                        eid=e.id, cid=e.instance_of
                    )

            # 6. 写 Relation 节点 + HAS_RELATION 边 + SOURCE/TARGET 边
            for r in relations:
                r_props = _relation_to_props(r)
                s.run(
                    """
                    CREATE (r:Relation) SET r = $props
                    WITH r
                    MATCH (o:Ontology {id: $oid})
                    CREATE (o)-[:HAS_RELATION]->(r)
                    """,
                    props=r_props, oid=oid
                )
                # SOURCE / TARGET 边
                s.run(
                    """
                    MATCH (r:Relation {id: $rid}), (src:Entity {id: $sid})
                    CREATE (r)-[:SOURCE]->(src)
                    """,
                    rid=r.id, sid=r.source_id
                )
                s.run(
                    """
                    MATCH (r:Relation {id: $rid}), (tgt:Entity {id: $tid})
                    CREATE (r)-[:TARGET]->(tgt)
                    """,
                    rid=r.id, tid=r.target_id
                )

        logger.info(
            "save_ontology_full: ontology=%s, concepts=%d, entities=%d, relations=%d",
            oid, len(concepts), len(entities), len(relations)
        )

    # ── Concept CRUD ──

    def list_concepts(self, ontology_id: str) -> List[ConceptType]:
        with self._session as s:
            result = s.run(
                "MATCH (c:Concept {ontology_id: $oid}) RETURN c ORDER BY c.create_time",
                oid=ontology_id
            )
            return [_props_to_concept(r["c"]) for r in result]

    def get_concept(self, ontology_id: str, concept_id: str) -> Optional[ConceptType]:
        with self._session as s:
            result = s.run(
                "MATCH (c:Concept {id: $cid, ontology_id: $oid}) RETURN c",
                oid=ontology_id, cid=concept_id
            )
            r = result.single()
            return _props_to_concept(r["c"]) if r else None

    def add_concept(self, ontology_id: str, concept: ConceptType) -> None:
        c_props = _concept_to_props(concept)
        with self._session as s:
            s.run("CREATE (c:Concept) SET c = $props", props=c_props)
            s.run(
                """
                MATCH (o:Ontology {id: $oid}), (c:Concept {id: $cid})
                CREATE (o)-[:HAS_CONCEPT]->(c)
                """,
                oid=ontology_id, cid=concept.id
            )

    def update_concept(self, ontology_id: str, concept: ConceptType) -> None:
        c_props = _concept_to_props(concept)
        with self._session as s:
            s.run(
                "MATCH (c:Concept {id: $cid}) SET c = $props",
                cid=concept.id, props=c_props
            )

    def delete_concept(self, ontology_id: str, concept_id: str) -> None:
        with self._session as s:
            s.run(
                "MATCH (c:Concept {id: $cid}) DETACH DELETE c",
                cid=concept_id
            )

    # ── Entity CRUD ──

    def list_entities(self, ontology_id: str) -> List[Entity]:
        with self._session as s:
            result = s.run(
                "MATCH (e:Entity {ontology_id: $oid}) RETURN e ORDER BY e.create_time",
                oid=ontology_id
            )
            return [_props_to_entity(r["e"]) for r in result]

    def get_entity(self, ontology_id: str, entity_id: str) -> Optional[Entity]:
        with self._session as s:
            result = s.run(
                "MATCH (e:Entity {id: $eid, ontology_id: $oid}) RETURN e",
                oid=ontology_id, eid=entity_id
            )
            r = result.single()
            return _props_to_entity(r["e"]) if r else None

    def add_entity(self, ontology_id: str, entity: Entity) -> None:
        e_props = _entity_to_props(entity)
        with self._session as s:
            s.run("CREATE (e:Entity) SET e = $props", props=e_props)
            s.run(
                """
                MATCH (o:Ontology {id: $oid}), (e:Entity {id: $eid})
                CREATE (o)-[:HAS_ENTITY]->(e)
                """,
                oid=ontology_id, eid=entity.id
            )
            if entity.instance_of:
                s.run(
                    """
                    MATCH (e:Entity {id: $eid}), (c:Concept {id: $cid})
                    CREATE (e)-[:INSTANCE_OF_CONCEPT]->(c)
                    """,
                    eid=entity.id, cid=entity.instance_of
                )

    def update_entity(self, ontology_id: str, entity: Entity) -> None:
        e_props = _entity_to_props(entity)
        with self._session as s:
            s.run(
                "MATCH (e:Entity {id: $eid}) SET e = $props",
                eid=entity.id, props=e_props
            )

    def delete_entity(self, ontology_id: str, entity_id: str) -> None:
        """删除实体 + 级联删除相关关系。"""
        with self._session as s:
            # 先删除引用此实体的关系
            s.run(
                """
                MATCH (r:Relation)-[:SOURCE|TARGET]->(e:Entity {id: $eid})
                DETACH DELETE r
                """,
                eid=entity_id
            )
            # 再删除实体本身
            s.run(
                "MATCH (e:Entity {id: $eid}) DETACH DELETE e",
                eid=entity_id
            )

    # ── Property CRUD ──

    def _update_entity_properties(self, ontology_id: str, entity_id: str,
                                    properties: List[Property]) -> None:
        """更新实体的 properties_json。"""
        props_json = json.dumps(
            [p.dict() for p in properties],
            ensure_ascii=False, default=str
        )
        with self._session as s:
            s.run(
                "MATCH (e:Entity {id: $eid}) SET e.properties_json = $pj",
                eid=entity_id, pj=props_json
            )

    def add_property(self, ontology_id: str, entity_id: str, prop: Property) -> None:
        e = self.get_entity(ontology_id, entity_id)
        if e:
            e.properties.append(prop)
            self._update_entity_properties(ontology_id, entity_id, e.properties)

    def update_property(self, ontology_id: str, entity_id: str, prop: Property,
                        auto_history: bool = True) -> None:
        e = self.get_entity(ontology_id, entity_id)
        if not e:
            return
        for i, p in enumerate(e.properties):
            if p.id == prop.id:
                # 指标型属性值变更时，旧值自动入 history
                if auto_history and p.category == "metric" and p.value != prop.value:
                    e.properties[i].history.append(PropertyHistoryEntry(
                        value=p.value,
                        recorded_at=datetime.now(),
                        source_snippet=p.source_snippet,
                    ))
                e.properties[i] = prop
                break
        self._update_entity_properties(ontology_id, entity_id, e.properties)

    def delete_property(self, ontology_id: str, entity_id: str, property_id: str) -> None:
        e = self.get_entity(ontology_id, entity_id)
        if not e:
            return
        e.properties = [p for p in e.properties if p.id != property_id]
        self._update_entity_properties(ontology_id, entity_id, e.properties)

    def add_property_history(self, ontology_id: str, entity_id: str,
                             property_id: str, entry: PropertyHistoryEntry) -> None:
        e = self.get_entity(ontology_id, entity_id)
        if not e:
            return
        for p in e.properties:
            if p.id == property_id:
                p.history.append(entry)
                break
        self._update_entity_properties(ontology_id, entity_id, e.properties)

    # ── Relation CRUD ──

    def list_relations(self, ontology_id: str) -> List[Relation]:
        with self._session as s:
            result = s.run(
                "MATCH (r:Relation {ontology_id: $oid}) RETURN r ORDER BY r.create_time",
                oid=ontology_id
            )
            return [_props_to_relation(r["r"]) for r in result]

    def add_relation(self, ontology_id: str, relation: Relation) -> None:
        r_props = _relation_to_props(relation)
        with self._session as s:
            s.run("CREATE (r:Relation) SET r = $props", props=r_props)
            s.run(
                """
                MATCH (o:Ontology {id: $oid}), (r:Relation {id: $rid})
                CREATE (o)-[:HAS_RELATION]->(r)
                """,
                oid=ontology_id, rid=relation.id
            )
            # SOURCE / TARGET 边
            s.run(
                """
                MATCH (r:Relation {id: $rid}), (src:Entity {id: $sid})
                CREATE (r)-[:SOURCE]->(src)
                """,
                rid=relation.id, sid=relation.source_id
            )
            s.run(
                """
                MATCH (r:Relation {id: $rid}), (tgt:Entity {id: $tid})
                CREATE (r)-[:TARGET]->(tgt)
                """,
                rid=relation.id, tid=relation.target_id
            )

    def delete_relation(self, ontology_id: str, relation_id: str) -> None:
        with self._session as s:
            s.run(
                "MATCH (r:Relation {id: $rid}) DETACH DELETE r",
                rid=relation_id
            )

    # ── Template CRUD ──

    def list_templates(self) -> List[TemplateModel]:
        with self._session as s:
            result = s.run("MATCH (t:Template) RETURN t ORDER BY t.create_time")
            return [_props_to_template(r["t"]) for r in result]

    def get_template(self, template_id: str) -> Optional[TemplateModel]:
        with self._session as s:
            result = s.run("MATCH (t:Template {id: $tid}) RETURN t", tid=template_id)
            r = result.single()
            return _props_to_template(r["t"]) if r else None

    def save_template(self, template_id: str) -> None:
        """no-op：Neo4j 即时持久化。模板通过 add/update_template 写入。"""
        pass

    def save_templates_index(self) -> None:
        """no-op。"""
        pass

    def upsert_template(self, template: TemplateModel) -> None:
        """创建或更新模板（MERGE）。"""
        t_props = _template_to_props(template)
        with self._session as s:
            s.run(
                "MERGE (t:Template {id: $tid}) SET t = $props",
                tid=template.id, props=t_props
            )

    def delete_template(self, template_id: str) -> None:
        with self._session as s:
            s.run(
                "MATCH (t:Template {id: $tid}) DETACH DELETE t",
                tid=template_id
            )

    # ── BuildJob CRUD ──

    def list_build_jobs(self) -> List[BuildJob]:
        with self._session as s:
            result = s.run("MATCH (j:BuildJob) RETURN j ORDER BY j.create_time DESC")
            return [_props_to_buildjob(r["j"]) for r in result]

    def get_build_job(self, job_id: str) -> Optional[BuildJob]:
        with self._session as s:
            result = s.run("MATCH (j:BuildJob {id: $jid}) RETURN j", jid=job_id)
            r = result.single()
            return _props_to_buildjob(r["j"]) if r else None

    def save_build_job(self, job_id: str) -> None:
        """no-op：Neo4j 即时持久化。"""
        pass

    def save_build_jobs_index(self) -> None:
        """no-op。"""
        pass

    def upsert_build_job(self, job: BuildJob) -> None:
        """创建或更新构建任务（MERGE）。"""
        j_props = _buildjob_to_props(job)
        with self._session as s:
            s.run(
                "MERGE (j:BuildJob {id: $jid}) SET j = $props",
                jid=job.id, props=j_props
            )

    def delete_build_job(self, job_id: str) -> None:
        with self._session as s:
            s.run(
                "MATCH (j:BuildJob {id: $jid}) DETACH DELETE j",
                jid=job_id
            )

    # ── 图谱查询 ──

    def get_graph_data(self, ontology_id: str) -> Dict[str, Any]:
        """用 Cypher 聚合生成图谱数据（nodes + links）。

        与 JsonRepository._graph_data 返回格式完全对齐：
        - 概念节点（node_type="concept"）：id/name/type/node_type/entity_type/color
        - 实体节点（node_type="entity"）：id/name/type/node_type/concept_type/concept_id/is_primary
        - instance_of 边：source=concept_id, target=entity_id, relation="instance_of"
        - 关系边：source=source_id, target=target_id, relation=relation_type

        重要：`type` 字段保持为类型名（如"人物""事件"），供前端按 entity_types
        颜色匹配；`node_type` 字段区分概念节点与实体节点。
        """
        with self._session as s:
            # 查询概念
            concept_result = s.run(
                """
                MATCH (c:Concept {ontology_id: $oid})
                RETURN c.id AS id, c.name AS name, c.entity_type AS entity_type,
                       c.color AS color
                """,
                oid=ontology_id
            )
            concepts_data = [dict(r) for r in concept_result]

            # 查询实体
            ent_result = s.run(
                """
                MATCH (e:Entity {ontology_id: $oid})
                RETURN e.id AS id, e.name AS name, e.instance_of AS instance_of,
                       e.is_primary AS is_primary
                """,
                oid=ontology_id
            )
            entities_data = [dict(r) for r in ent_result]

            # 查询关系
            rel_result = s.run(
                """
                MATCH (r:Relation {ontology_id: $oid})
                RETURN r.id AS id, r.source_id AS source, r.target_id AS target,
                       r.relation_type AS type, r.weight AS weight
                """,
                oid=ontology_id
            )
            relations_data = [dict(r) for r in rel_result]

        # 概念映射（concept_id -> {name, entity_type, color}）
        concept_map = {
            c["id"]: {
                "name": c["name"],
                "entity_type": c["entity_type"],
                "color": c["color"],
            }
            for c in concepts_data
        }

        nodes = []
        links = []

        # ── 概念节点 ──
        for c in concepts_data:
            nodes.append({
                "id": c["id"],
                "name": c["name"],
                "type": c["entity_type"] or c["name"] or "概念",
                "node_type": "concept",
                "entity_type": c["entity_type"],
                "color": c["color"],
            })

        # ── 实体节点 + instance_of 边 ──
        for e in entities_data:
            concept = concept_map.get(e["instance_of"])
            concept_name = concept["name"] if concept else ""
            # type 用概念的 entity_type（元模型类型名），兼容前端颜色匹配
            type_name = (concept["entity_type"] if concept else "未分类") or "未分类"
            nodes.append({
                "id": e["id"],
                "name": e["name"],
                "type": type_name,
                "node_type": "entity",
                "concept_type": concept_name,
                "concept_id": e["instance_of"],
                "is_primary": e.get("is_primary", False),
            })
            # instance_of 边（概念→实体）
            if e["instance_of"]:
                links.append({
                    "source": e["instance_of"],
                    "target": e["id"],
                    "relation": "instance_of",
                    "weight": 1.0,
                })

        # ── 关系边 ──
        for r in relations_data:
            links.append({
                "source": r["source"],
                "target": r["target"],
                "relation": r["type"],
                "weight": r.get("weight", 1.0),
            })

        return {"nodes": nodes, "links": links}

    def find_shortest_path(self, ontology_id: str, source_id: str,
                           target_id: str) -> Optional[Dict[str, Any]]:
        """用 Cypher shortestPath 求最短路径，返回格式与 JsonRepository._bfs_path 对齐。

        Returns:
            {"entities": [entity_dict_with_type], "relations": [relation_dict]}
            或 None（不可达/起点终点不存在）
        """
        # 先校验起点终点存在
        with self._session as s:
            exists = s.run(
                """
                MATCH (src:Entity {id: $sid, ontology_id: $oid}),
                      (tgt:Entity {id: $tid, ontology_id: $oid})
                RETURN count(*) AS c
                """,
                oid=ontology_id, sid=source_id, tid=target_id
            ).single()
            if not exists or exists["c"] == 0:
                return None

            # shortestPath 走 SOURCE/TARGET 边（Relation 节点作为中间桥接）
            # 路径形态：Entity <-[:TARGET]- Relation -[:SOURCE]-> Entity <-[:TARGET]- ...
            result = s.run(
                """
                MATCH (src:Entity {id: $sid, ontology_id: $oid}),
                      (tgt:Entity {id: $tid, ontology_id: $oid}),
                      p = shortestPath((src)-[:SOURCE|TARGET*]-(tgt))
                RETURN p
                """,
                oid=ontology_id, sid=source_id, tid=target_id
            )
            r = result.single()
            if not r:
                return None

            path = r["p"]

            # 路径节点中分离出 Entity 节点（按路径顺序）和 Relation 节点（按路径顺序）
            entity_nodes = []
            relation_nodes = []
            for node in path.nodes:
                labels = set(node.labels)
                if "Entity" in labels:
                    entity_nodes.append(node)
                elif "Relation" in labels:
                    relation_nodes.append(node)

            # 路径关系数 = Entity 数 - 1（每两个 Entity 之间一个 Relation 桥接）
            # relation_nodes 的顺序应与 entity_pairs 对齐
            # 取每个 Relation 的属性构造 Relation Pydantic
            relations = []
            for rn in relation_nodes:
                rel_props = {
                    "id": rn["id"],
                    "ontology_id": rn.get("ontology_id", ""),
                    "source_id": rn.get("source_id", ""),
                    "target_id": rn.get("target_id", ""),
                    "relation_type": rn.get("relation_type", ""),
                    "weight": rn.get("weight", 1.0),
                    "source_snippet": rn.get("source_snippet", ""),
                }
                # 解析 properties_json / bindings_json
                pj = rn.get("properties_json", "[]")
                try:
                    rel_props["properties"] = [Property(**p) for p in json.loads(pj)] if pj else []
                except (json.JSONDecodeError, Exception):
                    rel_props["properties"] = []
                bj = rn.get("bindings_json", "{}")
                try:
                    rel_props["bindings"] = json.loads(bj) if bj else {}
                except (json.JSONDecodeError, Exception):
                    rel_props["bindings"] = {}
                rel_props["create_time"] = _parse_dt(rn.get("create_time"))
                try:
                    relations.append(Relation(**rel_props))
                except Exception:
                    continue

            # 构造 entity dict（带 type 字段，与 _entity_dict_with_type 对齐）
            entities = []
            for en in entity_nodes:
                ent_props = dict(en)
                eid = ent_props.get("id", "")
                instance_of = ent_props.get("instance_of", "")
                # 推导 type 字段
                type_name = "未分类"
                if instance_of:
                    # 查概念取 entity_type
                    concept = s.run(
                        "MATCH (c:Concept {id: $cid}) RETURN c.entity_type AS et, c.name AS cn",
                        cid=instance_of
                    ).single()
                    if concept:
                        type_name = concept["et"] or concept["cn"] or "未分类"
                # 完整 Entity dict
                e = _props_to_entity(ent_props)
                d = e.dict()
                if not d.get("type"):
                    d["type"] = type_name
                entities.append(d)

        return {
            "entities": entities,
            "relations": [r.dict() for r in relations],
        }

    # ── 统计 ──

    def get_stats(self) -> Dict[str, Any]:
        with self._session as s:
            ont_count = s.run("MATCH (:Ontology) RETURN count(*) AS c").single()["c"]
            ent_count = s.run("MATCH (:Entity) RETURN count(*) AS c").single()["c"]
            rel_count = s.run("MATCH (:Relation) RETURN count(*) AS c").single()["c"]
            concept_count = s.run("MATCH (:Concept) RETURN count(*) AS c").single()["c"]
            job_count = s.run(
                "MATCH (j:BuildJob) WHERE j.status IN ['draft', 'running'] "
                "RETURN count(*) AS c"
            ).single()["c"]
        return {
            "total_ontologies": ont_count,
            "total_entities": ent_count,
            "total_relations": rel_count,
            "total_concepts": concept_count,
            "build_tasks_count": job_count,
        }

    def count_entities(self, ontology_id: str) -> int:
        with self._session as s:
            return s.run(
                "MATCH (:Entity {ontology_id: $oid}) RETURN count(*) AS c",
                oid=ontology_id
            ).single()["c"]

    def count_concepts(self, ontology_id: str) -> int:
        with self._session as s:
            return s.run(
                "MATCH (:Concept {ontology_id: $oid}) RETURN count(*) AS c",
                oid=ontology_id
            ).single()["c"]

    def count_relations(self, ontology_id: str) -> int:
        with self._session as s:
            return s.run(
                "MATCH (:Relation {ontology_id: $oid}) RETURN count(*) AS c",
                oid=ontology_id
            ).single()["c"]

    # ── 导入导出 ──

    def export_ontology(self, ontology_id: str) -> Optional[Dict[str, Any]]:
        ont = self.get_ontology(ontology_id)
        if not ont:
            return None
        concepts = self.list_concepts(ontology_id)
        entities = self.list_entities(ontology_id)
        relations = self.list_relations(ontology_id)
        return {
            "ontology": ont.dict(),
            "concepts": [c.dict() for c in concepts],
            "entities": [e.dict() for e in entities],
            "relations": [r.dict() for r in relations],
        }
