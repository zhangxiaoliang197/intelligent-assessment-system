"""v3 迁移脚本：ConceptType → EntityType（删除概念层）。

将 schema_version=2 的本体数据迁移到 schema_version=3：
- concepts 数组（ConceptType）→ entity_types 数组（EntityType，带层级+属性骨架）
- 丢弃旧 ontology.entity_types（本体模型粗分类 name+color），用迁移后的 EntityType 替代
- 颜色补偿：从旧 entity_types 的 name→color 映射，给无颜色的 EntityType 补色
- entities/relations 不变（Entity.instance_of 指向的 id 保留）
- 新增 entity_type_relations 空数组（无法从现有数据推导，留待 step1 返工补提）
- build_jobs：step1_concepts → step1_entity_types；已完成的旧任务标记 legacy

用法：
    cd python/ontology-service
    python migration_v3.py           # 迁移所有数据
    python migration_v3.py --dry     # 只检查不写入
"""
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 数据目录
BASE_DIR = Path(__file__).parent / "data"
USER_ONTOLOGIES_DIR = BASE_DIR / "user_ontologies"
BUILTIN_ONTOLOGIES_DIR = BASE_DIR  # 内置 ontology_ont_*.json 直接在 data/ 下
BUILD_JOBS_DIR = BASE_DIR / "build_jobs"
INDEX_FILE = BASE_DIR / "ontologies_index.json"

DRY_RUN = "--dry" in sys.argv


def backup_file(filepath: Path) -> None:
    """备份原文件为 .v2.bak（仅一次，不覆盖已有备份）。"""
    bak = filepath.with_suffix(filepath.suffix + ".v2.bak")
    if not bak.exists():
        shutil.copy2(filepath, bak)
        print(f"  备份: {bak.name}")


def migrate_concept_to_entity_type(concept: dict, color_map: dict) -> dict:
    """ConceptType dict → EntityType dict。

    Args:
        concept: ConceptType 原始 dict
        color_map: 旧 entity_types 的 {name: color} 映射，用于颜色补偿

    Returns:
        EntityType dict（v3 格式）
    """
    # 颜色补偿：concept 自带 color 优先；否则从 entity_type name 查旧本体模型颜色
    color = concept.get("color")
    if not color:
        et_name = concept.get("entity_type", "")
        color = color_map.get(et_name)

    return {
        "id": concept.get("id", ""),
        "ontology_id": concept.get("ontology_id", ""),
        "name": concept.get("name", ""),
        "description": concept.get("description", ""),
        "color": color,
        "property_schema": concept.get("property_schema", []) or [],
        "source_snippet": concept.get("source_snippet", ""),
        # parent_concept_id → parent_entity_type_id
        "parent_entity_type_id": concept.get("parent_concept_id"),
        "parent_entity_type_name": concept.get("parent_concept_name"),
        "create_time": concept.get("create_time", datetime.now().isoformat()),
        "update_time": concept.get("update_time", datetime.now().isoformat()),
    }


def migrate_ontology_file(filepath: Path) -> bool:
    """迁移单个 ontology JSON 文件（v2 → v3）。

    Returns:
        True 表示已迁移，False 表示无需迁移（已是 v3 或文件不存在）
    """
    if not filepath.exists():
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    ontology = data.get("ontology", {})
    sv = ontology.get("schema_version", 1)

    if sv >= 3:
        print(f"  跳过（已是 v3）: {filepath.name}")
        return False

    print(f"  迁移: {filepath.name} (v{sv} → v3)")

    if not DRY_RUN:
        backup_file(filepath)

    # 旧 entity_types（本体模型粗分类 name+color）→ 颜色映射
    old_entity_types = ontology.get("entity_types", []) or []
    color_map = {et.get("name", ""): et.get("color") for et in old_entity_types if et.get("name")}

    # concepts → entity_types（ConceptType → EntityType）
    concepts = data.get("concepts", []) or []
    new_entity_types = [migrate_concept_to_entity_type(c, color_map) for c in concepts]

    # 更新 ontology
    ontology["entity_types"] = new_entity_types
    ontology["schema_version"] = 3
    # 保留 relation_types 不变

    # 更新顶层结构：concepts → entity_types
    data["ontology"] = ontology
    data["entity_types"] = new_entity_types
    # 删除旧 concepts 字段
    data.pop("concepts", None)
    # 新增 entity_type_relations（空，无法从现有数据推导）
    data["entity_type_relations"] = []

    # entities/relations 不变（instance_of 指向的 id 保留）

    if not DRY_RUN:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  已写入: {filepath.name} ({len(new_entity_types)} 个 EntityType)")

    return True


def migrate_build_job_file(filepath: Path) -> bool:
    """迁移单个 build_job JSON 文件（v2 五阶段 → v3 四阶段）。

    策略：
    - step1_concepts → step1_entity_types（字段名 + 内容格式不变，仅改名）
    - step3_relations → step2_relations（合并到 step2）
    - step4_verification → step3_verification
    - step4_report → step3_report
    - 已完成的旧任务（status=completed）→ 标记 legacy，保留旧字段不删
    - 进行中的旧任务（status=draft）→ 标记 abandoned，保留旧字段

    Returns:
        True 表示已迁移，False 表示无需迁移
    """
    if not filepath.exists():
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    sv = data.get("schema_version")
    # build_job 没有 schema_version 字段，通过 step1_concepts 判断
    has_legacy_concepts = "step1_concepts" in data and data["step1_concepts"]

    if not has_legacy_concepts and "step1_entity_types" in data:
        print(f"  跳过（已是 v3）: {filepath.name}")
        return False

    print(f"  迁移: {filepath.name}")

    if not DRY_RUN:
        backup_file(filepath)

    # step1_concepts → step1_entity_types（内容是 ConceptType dict，需转 EntityType dict）
    old_color_map = {}
    for et in (data.get("meta_entity_types") or []):
        if et.get("name"):
            old_color_map[et["name"]] = et.get("color")

    if has_legacy_concepts:
        step1_entity_types = [
            migrate_concept_to_entity_type(c, old_color_map)
            for c in data["step1_concepts"]
        ]
        data["step1_entity_types"] = step1_entity_types
        # 保留 step1_concepts 作为 legacy 备份（不删，向后兼容）

    # step3_relations → step2_relations（实例间关系合并到 step2）
    if data.get("step3_relations"):
        # 如果 step2_relations 已有内容，合并；否则直接迁移
        existing = data.get("step2_relations", []) or []
        data["step2_relations"] = existing + data["step3_relations"]

    # step4_verification/report → step3_verification/report
    if data.get("step4_verification") is not None:
        data["step3_verification"] = data["step4_verification"]
    if data.get("step4_report") is not None:
        data["step3_report"] = data["step4_report"]

    # 任务状态：已完成的旧任务标记 legacy
    if data.get("status") == "completed":
        data["status"] = "legacy"

    # step 字段映射（旧五阶段 → 新四阶段）
    old_step = data.get("step", 0)
    # 旧: 0=待开始,1=概念,2=实体,3=关系,4=验证,5=完成
    # 新: 0=待开始,1=实体类型,2=实体+关系,3=验证,4=完成
    step_map = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 5: 4}
    data["step"] = step_map.get(old_step, 0)

    # template_mode 默认值
    if "template_mode" not in data:
        data["template_mode"] = "soft_constraint"

    # rework_history 默认值
    if "rework_history" not in data:
        data["rework_history"] = []

    if not DRY_RUN:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  已写入: {filepath.name}")

    return True


def migrate_index_file() -> bool:
    """迁移索引文件 ontologies_index.json（更新 schema_version）。"""
    if not INDEX_FILE.exists():
        return False

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 索引文件是 {ontology_id: {summary...}} 结构，检查是否需要迁移
    modified = False
    if isinstance(data, dict):
        for oid, ont_summary in data.items():
            if isinstance(ont_summary, dict):
                sv = ont_summary.get("schema_version", 1)
                if sv < 3:
                    if not DRY_RUN:
                        ont_summary["schema_version"] = 3
                    modified = True

    if modified:
        print(f"  迁移索引: {INDEX_FILE.name}")
        if not DRY_RUN:
            backup_file(INDEX_FILE)
            with open(INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  已写入: {INDEX_FILE.name}")

    return modified


def main():
    print("=" * 60)
    print(f"v3 迁移脚本（删除概念层，ConceptType → EntityType）")
    print(f"模式: {'DRY RUN（只检查不写入）' if DRY_RUN else '执行迁移'}")
    print("=" * 60)

    total = 0

    # 1. 用户本体
    print("\n[1] 用户本体数据 (user_ontologies/)")
    if USER_ONTOLOGIES_DIR.exists():
        for f in sorted(USER_ONTOLOGIES_DIR.glob("ontology_*.json")):
            if migrate_ontology_file(f):
                total += 1

    # 2. 内置本体
    print("\n[2] 内置本体数据 (data/ontology_*.json)")
    for f in sorted(BUILTIN_ONTOLOGIES_DIR.glob("ontology_ont_*.json")):
        if f.is_file() and f.suffix == ".json":
            if migrate_ontology_file(f):
                total += 1

    # 3. 构建任务
    print("\n[3] 构建任务 (build_jobs/)")
    if BUILD_JOBS_DIR.exists():
        for f in sorted(BUILD_JOBS_DIR.glob("job_*.json")):
            if migrate_build_job_file(f):
                total += 1

    # 4. 索引文件
    print("\n[4] 索引文件")
    migrate_index_file()

    print("\n" + "=" * 60)
    print(f"迁移完成: {total} 个文件")
    if DRY_RUN:
        print("（DRY RUN 模式，未实际写入。去掉 --dry 参数执行迁移）")
    else:
        print("原文件已备份为 .v2.bak")
    print("=" * 60)


if __name__ == "__main__":
    main()
