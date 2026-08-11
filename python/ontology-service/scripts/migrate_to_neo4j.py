"""一次性迁移脚本：将 JSON 存储的本体数据迁移到 Neo4j（Phase 3）。

使用方式：
    # 纯统计（不写入），先评估迁移规模
    python -m scripts.migrate_to_neo4j --dry-run

    # 迁移全部本体（自动调用 migration.py 升级 v1→v2）
    python -m scripts.migrate_to_neo4j --all

    # 迁移单个本体
    python -m scripts.migrate_to_neo4j --ontology ont_61daa626

    # 迁移并同时生成 OWL 快照（推荐首次切换时使用）
    python -m scripts.migrate_to_neo4j --all --generate-owl

    # 同时迁移模板和构建任务索引（可选，默认仅迁本体）
    python -m scripts.migrate_to_neo4j --all --include-templates --include-build-jobs

设计要点：
- 独立运行：直接读 JSON 文件 + 直接写 Neo4j，不依赖 FastAPI app 上下文
- 单本体事务：save_ontology_full 内部一个 session 写完整本体，失败不影响其他
- 幂等：save_ontology_full 先 DETACH DELETE 旧节点再写入，可重复执行
- 兼容 v1 数据：调用 migration.migrate_ontology_dict 升级 schema_version
- 失败明细：逐个本体 try/except，最后打印成功/失败汇总

环境变量：
- NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE（默认见 config.py）
- ONTOLOGY_REPOSITORY_BACKEND 不影响本脚本（脚本直接 new Neo4jRepository）
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# 将 ontology-service 根目录加入 sys.path，使脚本可独立运行
_SCRIPT_DIR = Path(__file__).resolve().parent
_SERVICE_DIR = _SCRIPT_DIR.parent
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

from models import (
    OntologyModel, ConceptType, Entity, Relation,
    TemplateModel, BuildJob,
)
from migration import migrate_ontology_dict, SCHEMA_VERSION
from repository.neo4j_repository import Neo4jRepository
from repository.neo4j_schema import init_schema, get_schema_info

# ── 日志配置 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("migrate_to_neo4j")

DATA_DIR = _SERVICE_DIR / "data"
INDEX_FILE = DATA_DIR / "ontologies_index.json"
USER_ONTOLOGIES_DIR = DATA_DIR / "user_ontologies"
# 模板/构建任务索引均位于各自目录下 index.json（与 main.py TEMPLATES_INDEX/BUILD_JOBS_INDEX 对齐）
TEMPLATES_DIR = DATA_DIR / "ontology_templates"
TEMPLATES_INDEX_FILE = TEMPLATES_DIR / "index.json"
BUILD_JOBS_DIR = DATA_DIR / "build_jobs"
BUILD_JOBS_INDEX_FILE = BUILD_JOBS_DIR / "index.json"


# ──────────────────────────────────────────────────────────────
# JSON 读取辅助
# ──────────────────────────────────────────────────────────────

def _load_json(path: Path, default: Any) -> Any:
    """读 JSON 文件，不存在/解析失败返回 default。"""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return default


def _resolve_ontology_file(ontology_id: str) -> Path:
    """定位本体数据文件：优先 user_ontologies 目录，兼容 data 根目录历史文件。"""
    new_path = USER_ONTOLOGIES_DIR / f"ontology_{ontology_id}.json"
    if new_path.exists():
        return new_path
    legacy_path = DATA_DIR / f"ontology_{ontology_id}.json"
    if legacy_path.exists():
        return legacy_path
    return new_path  # 返回新路径（即便不存在，调用方按 default 处理）


def _load_ontology_data(ontology_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """加载单个本体 JSON 数据，必要时执行 v1→v2 迁移。

    Returns:
        (data_dict, source_path)
        data_dict 含 ontology/concepts/entities/relations 四个 key
    """
    path = _resolve_ontology_file(ontology_id)
    data = _load_json(path, None)
    if data is None:
        return None, str(path)

    # 检查 schema_version，必要时迁移
    ont_meta = data.get("ontology", {}) if isinstance(data, dict) else {}
    sv = ont_meta.get("schema_version", 1) if isinstance(ont_meta, dict) else 1
    if sv < SCHEMA_VERSION:
        logger.info("本体 %s 为 v%d 数据，自动迁移到 v%d", ontology_id, sv, SCHEMA_VERSION)
        data = migrate_ontology_dict(data, ontology_id)
        # 回写迁移后的数据（避免下次重复迁移）
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str, indent=2)
            logger.info("已回写迁移后的本体文件: %s", path)
        except OSError as e:
            logger.warning("回写迁移文件失败 %s: %s（不影响迁移到 Neo4j）", path, e)

    return data, str(path)


def _parse_ontology(ont_dict: Dict[str, Any], index_item: Dict[str, Any]) -> OntologyModel:
    """从 index 条目 + data.ontology 合并构造 OntologyModel。"""
    merged = dict(index_item)  # index 中的 id/name/create_time 等
    onto_from_data = ont_dict.get("ontology", {}) if isinstance(ont_dict, dict) else {}
    if isinstance(onto_from_data, dict):
        merged.update(onto_from_data)
    return OntologyModel(**merged)


def _parse_concepts(data: Dict[str, Any]) -> List[ConceptType]:
    return [ConceptType(**c) for c in data.get("concepts", []) if isinstance(c, dict)]


def _parse_entities(data: Dict[str, Any]) -> List[Entity]:
    return [Entity(**e) for e in data.get("entities", []) if isinstance(e, dict)]


def _parse_relations(data: Dict[str, Any]) -> List[Relation]:
    return [Relation(**r) for r in data.get("relations", []) if isinstance(r, dict)]


# ──────────────────────────────────────────────────────────────
# OWL 生成
# ──────────────────────────────────────────────────────────────

def _generate_owl(ont: OntologyModel, concepts: List[ConceptType],
                  entities: List[Entity], relations: List[Relation]) -> Optional[str]:
    """生成 OWL 快照文件。失败返回 None（不影响迁移主流程）。"""
    try:
        from owl_builder import OwlBuilder
        out_dir = DATA_DIR / "ontologies"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"ontology_{ont.id}.owl"
        builder = OwlBuilder()
        builder.build_and_save(ont, concepts, entities, relations, str(out_path))
        logger.info("已生成 OWL 快照: %s", out_path)
        return str(out_path)
    except Exception as e:
        logger.warning("生成 OWL 失败（不影响迁移）: %s", e)
        return None


# ──────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────

def collect_ontologies(only_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """从 index 收集待迁移本体元信息。"""
    index = _load_json(INDEX_FILE, [])
    if not isinstance(index, list):
        return []
    if only_id:
        return [item for item in index if isinstance(item, dict) and item.get("id") == only_id]
    return [item for item in index if isinstance(item, dict) and item.get("id")]


def migrate_ontology_to_neo4j(repo: Neo4jRepository, index_item: Dict[str, Any],
                              generate_owl: bool = False) -> Dict[str, Any]:
    """迁移单个本体到 Neo4j。

    Returns:
        结果 dict：{id, name, status, concepts, entities, relations, owl_path, error}
    """
    ont_id = index_item["id"]
    name = index_item.get("name", "")
    result = {
        "id": ont_id, "name": name, "status": "pending",
        "concepts": 0, "entities": 0, "relations": 0,
        "owl_path": None, "error": None,
    }

    data, src_path = _load_ontology_data(ont_id)
    if data is None:
        result["status"] = "skipped"
        result["error"] = f"数据文件不存在或为空: {src_path}"
        return result

    try:
        ont = _parse_ontology(data, index_item)
        concepts = _parse_concepts(data)
        entities = _parse_entities(data)
        relations = _parse_relations(data)

        # 单事务写入 Neo4j
        repo.save_ontology_full(ont, concepts, entities, relations)

        result["status"] = "ok"
        result["concepts"] = len(concepts)
        result["entities"] = len(entities)
        result["relations"] = len(relations)

        # 可选：生成 OWL 快照
        if generate_owl:
            result["owl_path"] = _generate_owl(ont, concepts, entities, relations)

        logger.info(
            "本体 %s(%s) 迁移成功: %d 概念 / %d 实体 / %d 关系",
            ont_id, name, len(concepts), len(entities), len(relations)
        )
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        logger.error("本体 %s(%s) 迁移失败: %s", ont_id, name, e, exc_info=True)

    return result


def migrate_templates(repo: Neo4jRepository) -> Dict[str, int]:
    """迁移模板到 Neo4j。"""
    index = _load_json(TEMPLATES_INDEX_FILE, [])
    if not isinstance(index, list):
        return {"total": 0, "ok": 0, "failed": 0}

    total = ok = failed = 0
    for item in index:
        if not isinstance(item, dict):
            continue
        tpl_id = item.get("id")
        if not tpl_id:
            continue
        total += 1
        tpl_path = TEMPLATES_DIR / f"template_{tpl_id}.json"
        data = _load_json(tpl_path, None)
        if data is None:
            logger.warning("模板文件不存在: %s", tpl_path)
            failed += 1
            continue
        try:
            tpl = TemplateModel(**data)
            repo.upsert_template(tpl)
            ok += 1
            logger.info("模板 %s(%s) 迁移成功", tpl_id, tpl.name)
        except Exception as e:
            failed += 1
            logger.error("模板 %s 迁移失败: %s", tpl_id, e)

    return {"total": total, "ok": ok, "failed": failed}


def migrate_build_jobs(repo: Neo4jRepository) -> Dict[str, int]:
    """迁移构建任务到 Neo4j。"""
    index = _load_json(BUILD_JOBS_INDEX_FILE, [])
    if not isinstance(index, list):
        return {"total": 0, "ok": 0, "failed": 0}

    total = ok = failed = 0
    for item in index:
        if not isinstance(item, dict):
            continue
        job_id = item.get("id")
        if not job_id:
            continue
        total += 1
        # job_id 已含 job_ 前缀（与 main.py _build_job_file 命名规则一致）
        job_path = BUILD_JOBS_DIR / f"{job_id}.json"
        data = _load_json(job_path, None)
        if data is None:
            logger.warning("构建任务文件不存在: %s", job_path)
            failed += 1
            continue
        try:
            job = BuildJob(**data)
            repo.upsert_build_job(job)
            ok += 1
            logger.info("构建任务 %s(%s) 迁移成功", job_id, job.name)
        except Exception as e:
            failed += 1
            logger.error("构建任务 %s 迁移失败: %s", job_id, e)

    return {"total": total, "ok": ok, "failed": failed}


# ──────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="将 JSON 存储的本体数据迁移到 Neo4j（Phase 3）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="仅统计不写入，评估迁移规模")
    g.add_argument("--all", action="store_true",
                   help="迁移全部本体")
    g.add_argument("--ontology", metavar="ID",
                   help="迁移指定本体（如 ont_61daa626）")
    p.add_argument("--generate-owl", action="store_true",
                   help="迁移后同步生成 OWL 快照到 data/ontologies/")
    p.add_argument("--include-templates", action="store_true",
                   help="同时迁移模板索引")
    p.add_argument("--include-build-jobs", action="store_true",
                   help="同时迁移构建任务索引")
    p.add_argument("--reset", action="store_true",
                   help="迁移前清空 Neo4j 中本服务相关数据（DETACH DELETE 所有 Ontology/EntityType/Concept/Entity/Relation/Template/BuildJob 节点）")
    return p


def _print_summary(results: List[Dict[str, Any]]) -> None:
    """打印迁移汇总。"""
    print()
    print("=" * 80)
    print("迁移汇总")
    print("=" * 80)
    print(f"{'ID':<20} {'名称':<16} {'状态':<8} {'概念':>6} {'实体':>6} {'关系':>6}  备注")
    print("-" * 80)
    for r in results:
        note = ""
        if r["status"] != "ok":
            note = r.get("error") or ""
            if len(note) > 32:
                note = note[:32] + "..."
        name = r["name"][:14] + ".." if len(r["name"]) > 16 else r["name"]
        print(f"{r['id']:<20} {name:<16} {r['status']:<8} "
              f"{r['concepts']:>6} {r['entities']:>6} {r['relations']:>6}  {note}")
    print("-" * 80)
    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"成功: {ok}  失败: {failed}  跳过: {skipped}  总计: {len(results)}")
    print("=" * 80)


def _reset_neo4j(repo: Neo4jRepository) -> None:
    """清空 Neo4j 中本服务相关数据（谨慎使用）。"""
    with repo._session as s:
        # 按标签批量删除（DETACH DELETE 一并清除关系）
        for label in ("Relation", "Entity", "Concept", "EntityType",
                      "Ontology", "Template", "BuildJob"):
            r = s.run(f"MATCH (n:{label}) DETACH DELETE n RETURN count(*) AS c")
            count = r.single()["c"]
            if count:
                logger.info("已删除 %d 个 %s 节点", count, label)
    logger.warning("Neo4j 数据已清空")


def main() -> int:
    args = build_arg_parser().parse_args()

    # 仅 dry-run：纯读 JSON 统计
    if args.dry_run:
        items = collect_ontologies()
        print("=" * 80)
        print(f"Dry-run 统计（共 {len(items)} 个本体）")
        print("=" * 80)
        print(f"{'ID':<20} {'名称':<16} {'SV':>4} {'概念':>6} {'实体':>6} {'关系':>6}  文件")
        print("-" * 80)
        total_c = total_e = total_r = 0
        for item in items:
            ont_id = item["id"]
            data, src = _load_ontology_data(ont_id)
            if data is None:
                print(f"{ont_id:<20} {item.get('name','')[:14]:<16} "
                      f"{'?':>4} {'?':>6} {'?':>6} {'?':>6}  [文件缺失]")
                continue
            sv = (data.get("ontology", {}) or {}).get("schema_version", 1)
            cs = len(data.get("concepts", []))
            es = len(data.get("entities", []))
            rs = len(data.get("relations", []))
            total_c += cs
            total_e += es
            total_r += rs
            print(f"{ont_id:<20} {item.get('name','')[:14]:<16} "
                  f"{sv:>4} {cs:>6} {es:>6} {rs:>6}  {Path(src).name}")
        print("-" * 80)
        print(f"合计: 概念={total_c}  实体={total_e}  关系={total_r}")
        print("=" * 80)
        print("提示: 添加 --all 执行实际迁移")
        return 0

    # 实际迁移：连接 Neo4j
    only_id = args.ontology if args.ontology else None
    items = collect_ontologies(only_id=only_id)
    if not items:
        print(f"[ERROR] 未找到本体: {only_id or '(索引为空)'}")
        return 1

    print(f"待迁移本体数: {len(items)}")
    print(f"生成 OWL 快照: {'是' if args.generate_owl else '否'}")
    print(f"包含模板: {'是' if args.include_templates else '否'}")
    print(f"包含构建任务: {'是' if args.include_build_jobs else '否'}")
    print(f"清空旧数据: {'是' if args.reset else '否'}")
    print()

    try:
        repo = Neo4jRepository()
    except Exception as e:
        print(f"[ERROR] Neo4j 连接失败: {e}")
        print("请确认 Neo4j 已启动（默认 bolt://localhost:7687）")
        return 2

    try:
        # 初始化 schema（幂等）
        init_schema(repo._driver)
        logger.info("Neo4j schema 已初始化")

        if args.reset:
            _reset_neo4j(repo)

        # 迁移本体
        results: List[Dict[str, Any]] = []
        t0 = time.time()
        for item in items:
            r = migrate_ontology_to_neo4j(repo, item, generate_owl=args.generate_owl)
            results.append(r)

        _print_summary(results)

        # 验证 Neo4j 数据
        print()
        print("Neo4j 数据验证:")
        with repo._session as s:
            for label in ("Ontology", "EntityType", "Concept", "Entity", "Relation"):
                c = s.run(f"MATCH (n:{label}) RETURN count(*) AS c").single()["c"]
                print(f"  {label:<14} {c:>6}")

        # 可选：迁移模板
        if args.include_templates:
            print()
            print("模板迁移:")
            tpl_res = migrate_templates(repo)
            print(f"  总计: {tpl_res['total']}  成功: {tpl_res['ok']}  失败: {tpl_res['failed']}")

        # 可选：迁移构建任务
        if args.include_build_jobs:
            print()
            print("构建任务迁移:")
            job_res = migrate_build_jobs(repo)
            print(f"  总计: {job_res['total']}  成功: {job_res['ok']}  失败: {job_res['failed']}")

        # schema 信息
        print()
        print("Neo4j schema 状态:")
        si = get_schema_info(repo._driver)
        print(f"  约束数: {si['constraints_count']}  索引数: {si['indexes_count']}")

        elapsed = time.time() - t0
        print()
        print(f"迁移完成，耗时 {elapsed:.1f}s")

        # 任一失败返回非 0
        if any(r["status"] == "failed" for r in results):
            return 3
        return 0

    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
