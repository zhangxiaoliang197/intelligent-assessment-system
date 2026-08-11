"""Repository 工厂模块。

根据环境变量 ONTOLOGY_REPOSITORY_BACKEND 选择存储后端：
- 'json' (默认): JsonRepository（兼容现有行为）
- 'neo4j':       Neo4jRepository（Phase 3 实现）
- 'dual':        DualRepository（Phase 4 双写过渡）

使用方式：
    from repository import get_repository
    repo = get_repository()
    ont = repo.get_ontology(ontology_id)
"""
import os
import logging

from .base import OntologyRepository
from .json_repository import JsonRepository

logger = logging.getLogger("ontology-service")

_repo_instance: OntologyRepository = None


def get_repository() -> OntologyRepository:
    """获取 Repository 单例。

    首次调用时根据环境变量创建实例，后续返回缓存实例。
    """
    global _repo_instance
    if _repo_instance is not None:
        return _repo_instance

    backend = os.getenv("ONTOLOGY_REPOSITORY_BACKEND", "json").lower()

    if backend == "neo4j":
        try:
            from .neo4j_repository import Neo4jRepository
            _repo_instance = Neo4jRepository()
            logger.info("Repository 后端: Neo4j")
        except ImportError:
            logger.warning("Neo4jRepository 未实现，回退到 JsonRepository")
            _repo_instance = JsonRepository()
    elif backend == "dual":
        try:
            from .dual_repository import DualRepository
            from .neo4j_repository import Neo4jRepository
            _repo_instance = DualRepository(JsonRepository(), Neo4jRepository())
            logger.info("Repository 后端: Dual (JSON + Neo4j)")
        except ImportError:
            logger.warning("DualRepository 未实现，回退到 JsonRepository")
            _repo_instance = JsonRepository()
    else:
        _repo_instance = JsonRepository()
        logger.info("Repository 后端: JSON")

    return _repo_instance


def reset_repository() -> None:
    """重置单例（仅用于测试）。"""
    global _repo_instance
    _repo_instance = None
