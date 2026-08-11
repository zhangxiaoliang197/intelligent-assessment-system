"""Repository 契约测试：验证 JsonRepository 与 Neo4jRepository 行为一致（Phase 3）。

运行方式（在 ontology-service 目录下）：

    # 仅运行契约测试（需 Neo4j 已启动且数据已迁移）
    python -m pytest tests/test_repository_contract.py -v

    # 跳过 Neo4j 测试（仅 JSON）
    ONTOLOGY_SKIP_NEO4J=1 python -m pytest tests/test_repository_contract.py -v

设计原则：
- 不修改任何持久化数据（只读测试，所有断言基于已迁移的数据）
- 对每个已迁移的本体，断言 JSON 与 Neo4j 返回相同的：
    * ontology 元信息（id/name/schema_version/entity_types/relation_types）
    * concepts 数量与字段
    * entities 数量与字段
    * relations 数量与字段
- 图谱查询 / 统计 / 路径查找的行为一致性

依赖：
- JsonRepository 通过 main.py 间接加载数据（会触发 load_db）
- Neo4jRepository 直连 bolt://localhost:7687（需已执行 migrate_to_neo4j --all）
"""
import os
import sys
from pathlib import Path

try:
    import pytest
except ImportError:
    # pytest 未安装时，提供最小占位以便 __main__ 直接运行
    class _PytestStub:
        class fixture:
            def __init__(self, *args, **kwargs):
                pass
            def __call__(self, fn):
                return fn
        @staticmethod
        def skip(msg):
            print(f"[SKIP] {msg}")
            sys.exit(0)
    pytest = _PytestStub()

# 将 ontology-service 根目录加入 sys.path
_SERVICE_DIR = Path(__file__).resolve().parent.parent
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

from models import OntologyModel, ConceptType, Entity, Relation
from repository.json_repository import JsonRepository


# ──────────────────────────────────────────────────────────────
# Fixture：JsonRepository 单例（仅加载一次）
# ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def json_repo():
    """加载 JSON 数据到内存的 JsonRepository 单例。"""
    repo = JsonRepository()
    repo.load()
    return repo


@pytest.fixture(scope="module")
def neo4j_repo():
    """Neo4jRepository 单例。若 Neo4j 未启动则跳过测试。"""
    if os.getenv("ONTOLOGY_SKIP_NEO4J", "0") == "1":
        pytest.skip("ONTOLOGY_SKIP_NEO4J=1，跳过 Neo4j 测试")
    try:
        from repository.neo4j_repository import Neo4jRepository
        repo = Neo4jRepository()
        repo.load()  # 校验连接 + 初始化 schema
        return repo
    except Exception as e:
        pytest.skip(f"Neo4j 不可用（{e}），跳过 Neo4j 测试")


@pytest.fixture(scope="module")
def all_ontology_ids(json_repo):
    """所有已迁移本体的 ID 列表。"""
    return [ont.id for ont in json_repo.list_ontologies()]


# ──────────────────────────────────────────────────────────────
# 测试 1：本体列表一致
# ──────────────────────────────────────────────────────────────

def test_ontology_count_matches(json_repo, neo4j_repo):
    """JSON 与 Neo4j 的本体总数应一致。"""
    json_count = len(json_repo.list_ontologies())
    neo4j_count = len(neo4j_repo.list_ontologies())
    assert json_count == neo4j_count, (
        f"本体数量不一致: JSON={json_count}, Neo4j={neo4j_count}"
    )


def test_ontology_metadata_matches(json_repo, neo4j_repo, all_ontology_ids):
    """每个本体的元信息（id/name/schema_version）应一致。"""
    for oid in all_ontology_ids:
        j = json_repo.get_ontology(oid)
        n = neo4j_repo.get_ontology(oid)
        assert n is not None, f"Neo4j 中找不到本体 {oid}"
        assert j.id == n.id, f"{oid}: id 不一致"
        assert j.name == n.name, f"{oid}: name 不一致 JSON={j.name!r} Neo4j={n.name!r}"
        assert j.schema_version == n.schema_version, (
            f"{oid}: schema_version 不一致 JSON={j.schema_version} Neo4j={n.schema_version}"
        )
        # entity_types / relation_types 列表长度一致
        assert len(j.entity_types) == len(n.entity_types), (
            f"{oid}: entity_types 数量不一致 JSON={len(j.entity_types)} Neo4j={len(n.entity_types)}"
        )
        assert len(j.relation_types) == len(n.relation_types), (
            f"{oid}: relation_types 数量不一致 JSON={len(j.relation_types)} Neo4j={len(n.relation_types)}"
        )


# ──────────────────────────────────────────────────────────────
# 测试 2：概念一致
# ──────────────────────────────────────────────────────────────

def test_concepts_match(json_repo, neo4j_repo, all_ontology_ids):
    """每个本体的概念数量与字段一致。"""
    for oid in all_ontology_ids:
        j_list = json_repo.list_concepts(oid)
        n_list = neo4j_repo.list_concepts(oid)
        assert len(j_list) == len(n_list), (
            f"{oid}: 概念数量不一致 JSON={len(j_list)} Neo4j={len(n_list)}"
        )
        # 按 id 索引比较
        j_map = {c.id: c for c in j_list}
        n_map = {c.id: c for c in n_list}
        assert set(j_map.keys()) == set(n_map.keys()), (
            f"{oid}: 概念 ID 集合不一致"
        )
        for cid in j_map:
            jc = j_map[cid]
            nc = n_map[cid]
            assert jc.name == nc.name, f"{oid}/{cid}: name 不一致"
            assert jc.entity_type == nc.entity_type, f"{oid}/{cid}: entity_type 不一致"
            assert jc.color == nc.color, f"{oid}/{cid}: color 不一致"
            assert len(jc.property_schema) == len(nc.property_schema), (
                f"{oid}/{cid}: property_schema 数量不一致"
            )


# ──────────────────────────────────────────────────────────────
# 测试 3：实体一致
# ──────────────────────────────────────────────────────────────

def test_entities_match(json_repo, neo4j_repo, all_ontology_ids):
    """每个本体的实体数量与关键字段一致。"""
    for oid in all_ontology_ids:
        j_list = json_repo.list_entities(oid)
        n_list = neo4j_repo.list_entities(oid)
        assert len(j_list) == len(n_list), (
            f"{oid}: 实体数量不一致 JSON={len(j_list)} Neo4j={len(n_list)}"
        )
        j_map = {e.id: e for e in j_list}
        n_map = {e.id: e for e in n_list}
        assert set(j_map.keys()) == set(n_map.keys()), f"{oid}: 实体 ID 集合不一致"
        for eid in j_map:
            je = j_map[eid]
            ne = n_map[eid]
            assert je.name == ne.name, f"{oid}/{eid}: name 不一致"
            assert je.instance_of == ne.instance_of, f"{oid}/{eid}: instance_of 不一致"
            assert je.is_primary == ne.is_primary, f"{oid}/{eid}: is_primary 不一致"
            assert len(je.properties) == len(ne.properties), (
                f"{oid}/{eid}: properties 数量不一致 JSON={len(je.properties)} Neo4j={len(ne.properties)}"
            )


# ──────────────────────────────────────────────────────────────
# 测试 4：关系一致
# ──────────────────────────────────────────────────────────────

def test_relations_match(json_repo, neo4j_repo, all_ontology_ids):
    """每个本体的关系数量与关键字段一致。"""
    for oid in all_ontology_ids:
        j_list = json_repo.list_relations(oid)
        n_list = neo4j_repo.list_relations(oid)
        assert len(j_list) == len(n_list), (
            f"{oid}: 关系数量不一致 JSON={len(j_list)} Neo4j={len(n_list)}"
        )
        j_map = {r.id: r for r in j_list}
        n_map = {r.id: r for r in n_list}
        assert set(j_map.keys()) == set(n_map.keys()), f"{oid}: 关系 ID 集合不一致"
        for rid in j_map:
            jr = j_map[rid]
            nr = n_map[rid]
            assert jr.relation_type == nr.relation_type, f"{oid}/{rid}: relation_type 不一致"
            assert jr.source_id == nr.source_id, f"{oid}/{rid}: source_id 不一致"
            assert jr.target_id == nr.target_id, f"{oid}/{rid}: target_id 不一致"
            assert jr.weight == nr.weight, f"{oid}/{rid}: weight 不一致"


# ──────────────────────────────────────────────────────────────
# 测试 5：图谱查询一致
# ──────────────────────────────────────────────────────────────

def test_graph_data_matches(json_repo, neo4j_repo, all_ontology_ids):
    """get_graph_data 返回的 nodes/links 数量一致。"""
    for oid in all_ontology_ids:
        j_graph = json_repo.get_graph_data(oid)
        n_graph = neo4j_repo.get_graph_data(oid)
        assert len(j_graph["nodes"]) == len(n_graph["nodes"]), (
            f"{oid}: 图谱节点数量不一致 JSON={len(j_graph['nodes'])} Neo4j={len(n_graph['nodes'])}"
        )
        assert len(j_graph["links"]) == len(n_graph["links"]), (
            f"{oid}: 图谱边数量不一致 JSON={len(j_graph['links'])} Neo4j={len(n_graph['links'])}"
        )


# ──────────────────────────────────────────────────────────────
# 测试 6：统计一致
# ──────────────────────────────────────────────────────────────

def test_stats_match(json_repo, neo4j_repo):
    """get_stats 返回的全局统计一致。"""
    j = json_repo.get_stats()
    n = neo4j_repo.get_stats()
    assert j["total_ontologies"] == n["total_ontologies"], (
        f"total_ontologies 不一致 JSON={j['total_ontologies']} Neo4j={n['total_ontologies']}"
    )
    assert j["total_entities"] == n["total_entities"], (
        f"total_entities 不一致 JSON={j['total_entities']} Neo4j={n['total_entities']}"
    )
    assert j["total_relations"] == n["total_relations"], (
        f"total_relations 不一致 JSON={j['total_relations']} Neo4j={n['total_relations']}"
    )
    assert j["total_concepts"] == n["total_concepts"], (
        f"total_concepts 不一致 JSON={j['total_concepts']} Neo4j={n['total_concepts']}"
    )


def test_count_methods_match(json_repo, neo4j_repo, all_ontology_ids):
    """count_entities / count_concepts / count_relations 一致。"""
    for oid in all_ontology_ids:
        assert json_repo.count_entities(oid) == neo4j_repo.count_entities(oid), (
            f"{oid}: count_entities 不一致"
        )
        assert json_repo.count_concepts(oid) == neo4j_repo.count_concepts(oid), (
            f"{oid}: count_concepts 不一致"
        )
        assert json_repo.count_relations(oid) == neo4j_repo.count_relations(oid), (
            f"{oid}: count_relations 不一致"
        )


# ──────────────────────────────────────────────────────────────
# 测试 7：导出一致
# ──────────────────────────────────────────────────────────────

def test_export_matches(json_repo, neo4j_repo, all_ontology_ids):
    """export_ontology 返回的数据结构一致。"""
    for oid in all_ontology_ids:
        j = json_repo.export_ontology(oid)
        n = neo4j_repo.export_ontology(oid)
        assert j is not None and n is not None, f"{oid}: export 返回 None"
        assert len(j["concepts"]) == len(n["concepts"]), f"{oid}: export concepts 数量不一致"
        assert len(j["entities"]) == len(n["entities"]), f"{oid}: export entities 数量不一致"
        assert len(j["relations"]) == len(n["relations"]), f"{oid}: export relations 数量不一致"


# ──────────────────────────────────────────────────────────────
# 测试 8：默认本体
# ──────────────────────────────────────────────────────────────

def test_default_ontology_matches(json_repo, neo4j_repo):
    """get_default_ontology 行为一致（要么都返回 None，要么返回相同 id）。"""
    j_def = json_repo.get_default_ontology()
    n_def = neo4j_repo.get_default_ontology()
    if j_def is None and n_def is None:
        return  # 都无默认，一致
    assert j_def is not None and n_def is not None, (
        f"默认本体不一致: JSON={'None' if j_def is None else j_def.id} "
        f"Neo4j={'None' if n_def is None else n_def.id}"
    )
    assert j_def.id == n_def.id, f"默认本体 id 不一致 JSON={j_def.id} Neo4j={n_def.id}"


# ──────────────────────────────────────────────────────────────
# 主入口：直接运行打印汇总
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 直接运行：不依赖 pytest，逐个打印测试结果
    print("=" * 70)
    print("Repository 契约测试（JSON ↔ Neo4j）")
    print("=" * 70)

    json_repo = JsonRepository()
    json_repo.load()
    try:
        from repository.neo4j_repository import Neo4jRepository
        neo4j_repo = Neo4jRepository()
        neo4j_repo.load()
    except Exception as e:
        print(f"[SKIP] Neo4j 不可用: {e}")
        sys.exit(0)

    all_oids = [o.id for o in json_repo.list_ontologies()]
    print(f"待验证本体: {len(all_oids)} 个")
    print()

    failures = [0]  # 用 list 包装便于闭包修改（避免 nonlocal/global 作用域问题）

    def check(name, cond, detail=""):
        status = "[OK]  " if cond else "[FAIL]"
        if not cond:
            failures[0] += 1
        print(f"  {status} {name}" + (f"  ({detail})" if detail else ""))

    # 1. 本体数量
    jc = len(json_repo.list_ontologies())
    nc = len(neo4j_repo.list_ontologies())
    check("本体数量一致", jc == nc, f"JSON={jc} Neo4j={nc}")

    # 2. 逐本体验证
    for oid in all_oids:
        print(f"\n  ── 本体 {oid} ──")
        jo = json_repo.get_ontology(oid)
        no = neo4j_repo.get_ontology(oid)
        check(f"{oid}: 元信息存在", no is not None)
        if no:
            check(f"{oid}: name 一致", jo.name == no.name, f"JSON={jo.name!r} Neo4j={no.name!r}")

        # 概念
        jc_list = json_repo.list_concepts(oid)
        nc_list = neo4j_repo.list_concepts(oid)
        check(f"{oid}: 概念数量一致", len(jc_list) == len(nc_list),
              f"JSON={len(jc_list)} Neo4j={len(nc_list)}")

        # 实体
        je_list = json_repo.list_entities(oid)
        ne_list = neo4j_repo.list_entities(oid)
        check(f"{oid}: 实体数量一致", len(je_list) == len(ne_list),
              f"JSON={len(je_list)} Neo4j={len(ne_list)}")

        # 关系
        jr_list = json_repo.list_relations(oid)
        nr_list = neo4j_repo.list_relations(oid)
        check(f"{oid}: 关系数量一致", len(jr_list) == len(nr_list),
              f"JSON={len(jr_list)} Neo4j={len(nr_list)}")

        # 图谱
        jg = json_repo.get_graph_data(oid)
        ng = neo4j_repo.get_graph_data(oid)
        check(f"{oid}: 图谱节点一致", len(jg["nodes"]) == len(ng["nodes"]),
              f"JSON={len(jg['nodes'])} Neo4j={len(ng['nodes'])}")
        check(f"{oid}: 图谱边一致", len(jg["links"]) == len(ng["links"]),
              f"JSON={len(jg['links'])} Neo4j={len(ng['links'])}")

    # 3. 全局统计
    print()
    js = json_repo.get_stats()
    ns = neo4j_repo.get_stats()
    check("全局统计: total_ontologies", js["total_ontologies"] == ns["total_ontologies"])
    check("全局统计: total_entities", js["total_entities"] == ns["total_entities"])
    check("全局统计: total_relations", js["total_relations"] == ns["total_relations"])
    check("全局统计: total_concepts", js["total_concepts"] == ns["total_concepts"])

    print()
    print("=" * 70)
    if failures[0] == 0:
        print("✓ 所有契约测试通过")
    else:
        print(f"✗ {failures[0]} 项失败")
    print("=" * 70)
    sys.exit(1 if failures[0] else 0)
