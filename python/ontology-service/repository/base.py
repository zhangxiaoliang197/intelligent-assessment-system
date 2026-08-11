"""存储层统一接口（Repository 抽象）。

定义 ontology-service 所有持久化操作的契约：
- JsonRepository：现有内存字典 + JSON 文件实现（Phase 1 包装）
- Neo4jRepository：Neo4j 图数据库实现（Phase 3）
- DualRepository：双写过渡（Phase 4）

设计原则：
- 返回 Pydantic 模型实例，调用方安全读取
- 修改操作通过显式 save_* 方法持久化
- 同步接口；FastAPI 路由用 run_in_executor 包装 IO 重的实现
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple

from models import (
    OntologyModel, ConceptType, EntityType, EntityTypeRelation,
    Entity, Relation, Property,
    PropertyHistoryEntry, TemplateModel, BuildJob
)


class OntologyRepository(ABC):
    """本体存储层抽象基类。"""

    # ── 生命周期 ──
    @abstractmethod
    def load(self) -> None:
        """启动时加载数据（JsonRepository 加载到内存 / Neo4j 校验连接）。"""

    @abstractmethod
    def close(self) -> None:
        """关闭连接/释放资源。"""

    # ── Ontology CRUD ──
    @abstractmethod
    def list_ontologies(self) -> List[OntologyModel]: ...

    @abstractmethod
    def get_ontology(self, ontology_id: str) -> Optional[OntologyModel]: ...

    @abstractmethod
    def save_ontology(self, ontology_id: str) -> None:
        """持久化单个本体（元信息 + 概念 + 实体 + 关系）。"""

    @abstractmethod
    def save_index(self) -> None:
        """持久化本体列表索引。"""

    @abstractmethod
    def delete_ontology(self, ontology_id: str) -> None: ...

    @abstractmethod
    def set_default_ontology(self, ontology_id: str) -> None: ...

    @abstractmethod
    def get_default_ontology(self) -> Optional[OntologyModel]: ...

    @abstractmethod
    def get_ontology_summary(self, ont: OntologyModel) -> Dict[str, Any]: ...

    # ── Concept CRUD ──
    @abstractmethod
    def list_concepts(self, ontology_id: str) -> List[ConceptType]: ...

    @abstractmethod
    def get_concept(self, ontology_id: str, concept_id: str) -> Optional[ConceptType]: ...

    @abstractmethod
    def add_concept(self, ontology_id: str, concept: ConceptType) -> None: ...

    @abstractmethod
    def update_concept(self, ontology_id: str, concept: ConceptType) -> None: ...

    @abstractmethod
    def delete_concept(self, ontology_id: str, concept_id: str) -> None: ...

    # ── EntityTypeRelation CRUD（v3 新增：实体类型间关系）──
    @abstractmethod
    def list_entity_type_relations(self, ontology_id: str) -> List[EntityTypeRelation]: ...

    @abstractmethod
    def add_entity_type_relation(self, ontology_id: str, relation: EntityTypeRelation) -> None: ...

    @abstractmethod
    def delete_entity_type_relation(self, ontology_id: str, relation_id: str) -> None: ...

    # ── Entity CRUD ──
    @abstractmethod
    def list_entities(self, ontology_id: str) -> List[Entity]: ...

    @abstractmethod
    def get_entity(self, ontology_id: str, entity_id: str) -> Optional[Entity]: ...

    @abstractmethod
    def add_entity(self, ontology_id: str, entity: Entity) -> None: ...

    @abstractmethod
    def update_entity(self, ontology_id: str, entity: Entity) -> None: ...

    @abstractmethod
    def delete_entity(self, ontology_id: str, entity_id: str) -> None: ...

    # ── Property CRUD ──
    @abstractmethod
    def add_property(self, ontology_id: str, entity_id: str, prop: Property) -> None: ...

    @abstractmethod
    def update_property(self, ontology_id: str, entity_id: str, prop: Property,
                        auto_history: bool = True) -> None: ...

    @abstractmethod
    def delete_property(self, ontology_id: str, entity_id: str, property_id: str) -> None: ...

    @abstractmethod
    def add_property_history(self, ontology_id: str, entity_id: str,
                             property_id: str, entry: PropertyHistoryEntry) -> None: ...

    # ── Relation CRUD ──
    @abstractmethod
    def list_relations(self, ontology_id: str) -> List[Relation]: ...

    @abstractmethod
    def add_relation(self, ontology_id: str, relation: Relation) -> None: ...

    @abstractmethod
    def delete_relation(self, ontology_id: str, relation_id: str) -> None: ...

    # ── Template CRUD ──
    @abstractmethod
    def list_templates(self) -> List[TemplateModel]: ...

    @abstractmethod
    def get_template(self, template_id: str) -> Optional[TemplateModel]: ...

    @abstractmethod
    def save_template(self, template_id: str) -> None: ...

    @abstractmethod
    def save_templates_index(self) -> None: ...

    @abstractmethod
    def delete_template(self, template_id: str) -> None: ...

    # ── BuildJob CRUD ──
    @abstractmethod
    def list_build_jobs(self) -> List[BuildJob]: ...

    @abstractmethod
    def get_build_job(self, job_id: str) -> Optional[BuildJob]: ...

    @abstractmethod
    def save_build_job(self, job_id: str) -> None: ...

    @abstractmethod
    def save_build_jobs_index(self) -> None: ...

    @abstractmethod
    def delete_build_job(self, job_id: str) -> None: ...

    # ── 图谱查询 ──
    @abstractmethod
    def get_graph_data(self, ontology_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def find_shortest_path(self, ontology_id: str, source_id: str,
                           target_id: str) -> Optional[Dict[str, Any]]: ...

    # ── 统计 ──
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]: ...

    @abstractmethod
    def count_entities(self, ontology_id: str) -> int: ...

    @abstractmethod
    def count_concepts(self, ontology_id: str) -> int: ...

    @abstractmethod
    def count_relations(self, ontology_id: str) -> int: ...

    # ── 导入导出 ──
    @abstractmethod
    def export_ontology(self, ontology_id: str) -> Optional[Dict[str, Any]]: ...

    # ── OWL 集成（Phase 2/5 实现，Phase 1 抛 NotImplementedError）──
    def export_owl(self, ontology_id: str, file_path: str) -> str:
        """导出为 OWL 文件（Phase 2 实现）。"""
        raise NotImplementedError("OWL 导出在 Phase 2 实现")

    def reason_ontology(self, ontology_id: str) -> Dict[str, Any]:
        """执行 OWL 推理（Phase 5 实现）。"""
        raise NotImplementedError("OWL 推理在 Phase 5 实现")
