"""JsonRepository：基于内存字典 + JSON 文件的存储实现（Phase 1 薄包装）。

Phase 1 策略：薄包装 main.py 现有的模块级函数与全局字典，
不移动任何代码到本文件，通过 lazy import 避免循环依赖。

这样：
- 建立完整 Repository 抽象（供 Neo4jRepository 实现同一接口）
- 零回归风险（main.py 现有代码完全不变）
- Phase 4 可逐 endpoint 将 main.py 的直接字典访问替换为 repo 调用
"""
import logging
from typing import List, Optional, Dict, Any

from models import (
    OntologyModel, ConceptType, EntityType, EntityTypeRelation,
    Entity, Relation, Property,
    PropertyHistoryEntry, TemplateModel, BuildJob
)
from .base import OntologyRepository

logger = logging.getLogger("ontology-service")


class JsonRepository(OntologyRepository):
    """包装 main.py 现有存储逻辑的 JsonRepository 实现。"""

    @property
    def _m(self):
        """Lazy 访问 main 模块（避免循环 import）。

        main.py 顶部会 `from repository import get_repository` 创建 repo 单例，
        若此处模块级 import main 会形成循环。延迟到方法调用时 import 安全。
        """
        import main
        return main

    # ── 生命周期 ──
    def load(self) -> None:
        """加载所有数据到内存（委托给 main.py 的 load_* 函数）。"""
        m = self._m
        m.load_db()
        m.load_templates()
        m.load_build_jobs()

    def close(self) -> None:
        """JSON 存储无需关闭连接。"""
        pass

    # ── Ontology CRUD ──
    def list_ontologies(self) -> List[OntologyModel]:
        return list(self._m.ontologies_db.values())

    def get_ontology(self, ontology_id: str) -> Optional[OntologyModel]:
        return self._m.ontologies_db.get(ontology_id)

    def save_ontology(self, ontology_id: str) -> None:
        self._m.save_ontology(ontology_id)

    def save_index(self) -> None:
        self._m.save_index()

    def delete_ontology(self, ontology_id: str) -> None:
        m = self._m
        if ontology_id in m.ontologies_db:
            del m.ontologies_db[ontology_id]
        m.concepts_db.pop(ontology_id, None)
        m.entity_type_relations_db.pop(ontology_id, None)  # v3 新增
        m.entities_db.pop(ontology_id, None)
        m.relations_db.pop(ontology_id, None)
        m.save_index()
        # 删除数据文件
        import os
        f = m._resolve_ontology_file(ontology_id)
        if os.path.exists(f):
            os.remove(f)
        if os.path.exists(f + '.bak'):
            os.remove(f + '.bak')

    def set_default_ontology(self, ontology_id: str) -> None:
        m = self._m
        for oid, ont in m.ontologies_db.items():
            ont.is_default = (oid == ontology_id)
        m.save_index()

    def get_default_ontology(self) -> Optional[OntologyModel]:
        for ont in self._m.ontologies_db.values():
            if ont.is_default:
                return ont
        return None

    def get_ontology_summary(self, ont: OntologyModel) -> Dict[str, Any]:
        return self._m._ontology_summary(ont)

    # ── Concept CRUD ──
    def list_concepts(self, ontology_id: str) -> List[ConceptType]:
        return self._m.concepts_db.get(ontology_id, [])

    def get_concept(self, ontology_id: str, concept_id: str) -> Optional[ConceptType]:
        for c in self._m.concepts_db.get(ontology_id, []):
            if c.id == concept_id:
                return c
        return None

    def add_concept(self, ontology_id: str, concept: ConceptType) -> None:
        m = self._m
        m.concepts_db.setdefault(ontology_id, []).append(concept)
        m.save_ontology(ontology_id)

    def update_concept(self, ontology_id: str, concept: ConceptType) -> None:
        m = self._m
        lst = m.concepts_db.get(ontology_id, [])
        for i, c in enumerate(lst):
            if c.id == concept.id:
                lst[i] = concept
                m.save_ontology(ontology_id)
                return

    def delete_concept(self, ontology_id: str, concept_id: str) -> None:
        m = self._m
        lst = m.concepts_db.get(ontology_id, [])
        m.concepts_db[ontology_id] = [c for c in lst if c.id != concept_id]
        m.save_ontology(ontology_id)

    # ── EntityTypeRelation CRUD（v3 新增：实体类型间关系）──
    def list_entity_type_relations(self, ontology_id: str) -> List[EntityTypeRelation]:
        return self._m.entity_type_relations_db.get(ontology_id, [])

    def add_entity_type_relation(self, ontology_id: str, relation: EntityTypeRelation) -> None:
        m = self._m
        m.entity_type_relations_db.setdefault(ontology_id, []).append(relation)
        m.save_ontology(ontology_id)

    def delete_entity_type_relation(self, ontology_id: str, relation_id: str) -> None:
        m = self._m
        lst = m.entity_type_relations_db.get(ontology_id, [])
        m.entity_type_relations_db[ontology_id] = [r for r in lst if r.id != relation_id]
        m.save_ontology(ontology_id)

    # ── Entity CRUD ──
    def list_entities(self, ontology_id: str) -> List[Entity]:
        return self._m.entities_db.get(ontology_id, [])

    def get_entity(self, ontology_id: str, entity_id: str) -> Optional[Entity]:
        for e in self._m.entities_db.get(ontology_id, []):
            if e.id == entity_id:
                return e
        return None

    def add_entity(self, ontology_id: str, entity: Entity) -> None:
        m = self._m
        m.entities_db.setdefault(ontology_id, []).append(entity)
        m.save_ontology(ontology_id)

    def update_entity(self, ontology_id: str, entity: Entity) -> None:
        m = self._m
        lst = m.entities_db.get(ontology_id, [])
        for i, e in enumerate(lst):
            if e.id == entity.id:
                lst[i] = entity
                m.save_ontology(ontology_id)
                return

    def delete_entity(self, ontology_id: str, entity_id: str) -> None:
        m = self._m
        lst = m.entities_db.get(ontology_id, [])
        m.entities_db[ontology_id] = [e for e in lst if e.id != entity_id]
        # 级联删除相关关系
        m.relations_db[ontology_id] = [
            r for r in m.relations_db.get(ontology_id, [])
            if r.source_id != entity_id and r.target_id != entity_id
        ]
        m.save_ontology(ontology_id)

    # ── Property CRUD ──
    def add_property(self, ontology_id: str, entity_id: str, prop: Property) -> None:
        m = self._m
        for e in m.entities_db.get(ontology_id, []):
            if e.id == entity_id:
                e.properties.append(prop)
                m.save_ontology(ontology_id)
                return

    def update_property(self, ontology_id: str, entity_id: str, prop: Property,
                        auto_history: bool = True) -> None:
        m = self._m
        for e in m.entities_db.get(ontology_id, []):
            if e.id != entity_id:
                continue
            for i, p in enumerate(e.properties):
                if p.id == prop.id:
                    # 指标型属性值变更时，旧值自动入 history
                    if auto_history and p.category == "metric" and p.value != prop.value:
                        from models import PropertyHistoryEntry
                        from datetime import datetime
                        p.history.append(PropertyHistoryEntry(
                            value=p.value,
                            recorded_at=datetime.now(),
                            source_snippet=p.source_snippet,
                        ))
                    e.properties[i] = prop
                    m.save_ontology(ontology_id)
                    return

    def delete_property(self, ontology_id: str, entity_id: str, property_id: str) -> None:
        m = self._m
        for e in m.entities_db.get(ontology_id, []):
            if e.id == entity_id:
                e.properties = [p for p in e.properties if p.id != property_id]
                m.save_ontology(ontology_id)
                return

    def add_property_history(self, ontology_id: str, entity_id: str,
                             property_id: str, entry: PropertyHistoryEntry) -> None:
        m = self._m
        for e in m.entities_db.get(ontology_id, []):
            if e.id != entity_id:
                continue
            for p in e.properties:
                if p.id == property_id:
                    p.history.append(entry)
                    m.save_ontology(ontology_id)
                    return

    # ── Relation CRUD ──
    def list_relations(self, ontology_id: str) -> List[Relation]:
        return self._m.relations_db.get(ontology_id, [])

    def add_relation(self, ontology_id: str, relation: Relation) -> None:
        m = self._m
        m.relations_db.setdefault(ontology_id, []).append(relation)
        m.save_ontology(ontology_id)

    def delete_relation(self, ontology_id: str, relation_id: str) -> None:
        m = self._m
        lst = m.relations_db.get(ontology_id, [])
        m.relations_db[ontology_id] = [r for r in lst if r.id != relation_id]
        m.save_ontology(ontology_id)

    # ── Template CRUD ──
    def list_templates(self) -> List[TemplateModel]:
        return list(self._m.templates_db.values())

    def get_template(self, template_id: str) -> Optional[TemplateModel]:
        return self._m.templates_db.get(template_id)

    def save_template(self, template_id: str) -> None:
        self._m.save_template(template_id)

    def save_templates_index(self) -> None:
        self._m.save_templates_index()

    def delete_template(self, template_id: str) -> None:
        m = self._m
        if template_id in m.templates_db:
            del m.templates_db[template_id]
            m.save_templates_index()
            import os
            f = m._template_file(template_id)
            if os.path.exists(f):
                os.remove(f)

    # ── BuildJob CRUD ──
    def list_build_jobs(self) -> List[BuildJob]:
        return list(self._m.build_jobs_db.values())

    def get_build_job(self, job_id: str) -> Optional[BuildJob]:
        return self._m.build_jobs_db.get(job_id)

    def save_build_job(self, job_id: str) -> None:
        self._m.save_build_job(job_id)

    def save_build_jobs_index(self) -> None:
        self._m.save_build_jobs_index()

    def delete_build_job(self, job_id: str) -> None:
        m = self._m
        if job_id in m.build_jobs_db:
            del m.build_jobs_db[job_id]
            m.save_build_jobs_index()
            import os
            f = m._build_job_file(job_id)
            if os.path.exists(f):
                os.remove(f)

    # ── 图谱查询 ──
    def get_graph_data(self, ontology_id: str) -> Dict[str, Any]:
        return self._m._graph_data(ontology_id)

    def find_shortest_path(self, ontology_id: str, source_id: str,
                           target_id: str) -> Optional[Dict[str, Any]]:
        return self._m._bfs_path(ontology_id, source_id, target_id)

    # ── 统计 ──
    def get_stats(self) -> Dict[str, Any]:
        m = self._m
        return {
            "total_ontologies": len(m.ontologies_db),
            "total_entities": sum(len(v) for v in m.entities_db.values()),
            "total_relations": sum(len(v) for v in m.relations_db.values()),
            "total_concepts": sum(len(v) for v in m.concepts_db.values()),
            "total_entity_type_relations": sum(len(v) for v in m.entity_type_relations_db.values()),
            "build_tasks_count": sum(1 for j in m.build_jobs_db.values()
                                     if j.status in ("draft", "running")),
        }

    def count_entities(self, ontology_id: str) -> int:
        return len(self._m.entities_db.get(ontology_id, []))

    def count_concepts(self, ontology_id: str) -> int:
        return len(self._m.concepts_db.get(ontology_id, []))

    def count_relations(self, ontology_id: str) -> int:
        return len(self._m.relations_db.get(ontology_id, []))

    # ── 导入导出 ──
    def export_ontology(self, ontology_id: str) -> Optional[Dict[str, Any]]:
        m = self._m
        ont = m.ontologies_db.get(ontology_id)
        if not ont:
            return None
        return {
            "ontology": ont.dict(),
            "concepts": [c.dict() for c in m.concepts_db.get(ontology_id, [])],
            "entity_type_relations": [r.dict() for r in m.entity_type_relations_db.get(ontology_id, [])],
            "entities": [e.dict() for e in m.entities_db.get(ontology_id, [])],
            "relations": [r.dict() for r in m.relations_db.get(ontology_id, [])],
        }
