"""一次性迁移脚本：将「元模型」相关磁盘数据迁移到「本体模型」命名。

迁移内容：
1. 目录重命名：data/ontology_templates/ → data/ontology_template_models/
2. 文件重命名：template_{tpl_id}.json → ontology_model_{tpl_id}.json
3. build_jobs JSON 字段重命名：
   - template_id → ontology_model_id
   - template_snapshot → ontology_model_snapshot
   - template_mode → ontology_model_mode
   （保留旧字段作向后兼容，避免历史快照丢失）

幂等：脚本可重复执行，已迁移项自动跳过。

使用方式：
    python -m scripts.migrate_template_to_ontology_model            # 执行迁移
    python -m scripts.migrate_template_to_ontology_model --dry-run   # 仅统计不写入
"""
import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_SERVICE_DIR = _SCRIPT_DIR.parent
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migrate_template_to_ontology_model")

DATA_DIR = _SERVICE_DIR / "data"
OLD_TEMPLATES_DIR = DATA_DIR / "ontology_templates"
NEW_TEMPLATES_DIR = DATA_DIR / "ontology_template_models"
BUILD_JOBS_DIR = DATA_DIR / "build_jobs"
BUILD_JOBS_INDEX = BUILD_JOBS_DIR / "index.json"

# 旧→新字段映射（build_jobs JSON）
FIELD_MAP = {
    "template_id": "ontology_model_id",
    "template_snapshot": "ontology_model_snapshot",
    "template_mode": "ontology_model_mode",
}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return default


def _atomic_write_json(path: Path, data: Any) -> None:
    """原子写：先写 .tmp 再 rename，避免中断导致半写文件。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str, indent=2)
    os.replace(tmp, path)


def _migrate_template_fields(data: Any) -> Tuple[Any, bool]:
    """递归迁移 build_jobs 字典中的 template_* 字段。

    策略：旧字段存在但新字段不存在时，复制旧→新；旧字段保留作向后兼容。
    若新字段已存在，视为已迁移，跳过。

    Returns:
        (migrated_data, changed)
    """
    if isinstance(data, dict):
        changed = False
        new_data = dict(data)
        for old_key, new_key in FIELD_MAP.items():
            if old_key in new_data and new_key not in new_data:
                new_data[new_key] = new_data[old_key]
                changed = True
        # 递归处理嵌套字典/列表
        for k, v in list(new_data.items()):
            child, child_changed = _migrate_template_fields(v)
            if child_changed:
                new_data[k] = child
                changed = True
        return new_data, changed
    if isinstance(data, list):
        changed = False
        new_list = []
        for item in data:
            child, child_changed = _migrate_template_fields(item)
            new_list.append(child)
            if child_changed:
                changed = True
        return new_list, changed
    return data, False


def migrate_ontology_templates_dir(dry_run: bool) -> Dict[str, int]:
    """迁移本体模型目录与文件命名。"""
    stats = {"dir_renamed": 0, "files_renamed": 0, "skipped": 0}

    if not OLD_TEMPLATES_DIR.exists():
        # 旧目录不存在，检查新目录是否已就绪
        if NEW_TEMPLATES_DIR.exists():
            logger.info("目录已迁移至 %s，跳过", NEW_TEMPLATES_DIR)
            stats["skipped"] = 1
            return stats
        logger.warning("目录 %s 不存在，无内容可迁移", OLD_TEMPLATES_DIR)
        return stats

    if NEW_TEMPLATES_DIR.exists():
        # 两个目录都存在，合并：将旧目录残留文件移入新目录
        logger.warning("新旧目录均存在，将合并 %s 残留文件至 %s",
                       OLD_TEMPLATES_DIR, NEW_TEMPLATES_DIR)
        for item in OLD_TEMPLATES_DIR.iterdir():
            target = NEW_TEMPLATES_DIR / item.name
            if target.exists():
                logger.info("  跳过已存在: %s", target.name)
                stats["skipped"] += 1
                continue
            if not dry_run:
                shutil.move(str(item), str(target))
            logger.info("  移动: %s → %s", item.name, target)
            stats["files_renamed"] += 1
        # 删除空旧目录
        if not dry_run:
            try:
                OLD_TEMPLATES_DIR.rmdir()
                logger.info("已删除空旧目录: %s", OLD_TEMPLATES_DIR)
            except OSError as e:
                logger.warning("删除旧目录失败 %s: %s", OLD_TEMPLATES_DIR, e)
        return stats

    # 标准路径：旧目录存在、新目录不存在 → 重命名
    if not dry_run:
        os.rename(OLD_TEMPLATES_DIR, NEW_TEMPLATES_DIR)
    logger.info("目录重命名: %s → %s", OLD_TEMPLATES_DIR, NEW_TEMPLATES_DIR)
    stats["dir_renamed"] = 1

    # 重命名 template_*.json → ontology_model_*.json
    # dry-run 模式下目录未实际改名，需遍历旧目录
    scan_dir = NEW_TEMPLATES_DIR if NEW_TEMPLATES_DIR.exists() else OLD_TEMPLATES_DIR
    if scan_dir.exists():
        for item in scan_dir.iterdir():
            if item.is_file() and item.name.startswith("template_") and item.name.endswith(".json"):
                new_name = "ontology_model_" + item.name[len("template_"):]
                new_path = NEW_TEMPLATES_DIR / new_name
                if not dry_run:
                    os.rename(item, new_path)
                logger.info("文件重命名: %s → %s", item.name, new_name)
                stats["files_renamed"] += 1

    return stats


def migrate_build_jobs_files(dry_run: bool) -> Dict[str, int]:
    """迁移 build_jobs 目录下所有 JSON 文件（含 index.json 和 job_*.json）。"""
    stats = {"total": 0, "migrated": 0, "skipped": 0, "failed": 0}

    if not BUILD_JOBS_DIR.exists():
        logger.info("build_jobs 目录不存在，跳过")
        return stats

    json_files = sorted(BUILD_JOBS_DIR.glob("*.json"))
    stats["total"] = len(json_files)
    if not json_files:
        logger.info("build_jobs 目录无 JSON 文件")
        return stats

    for jf in json_files:
        data = _load_json(jf, None)
        if data is None:
            stats["failed"] += 1
            continue
        migrated, changed = _migrate_template_fields(data)
        if not changed:
            stats["skipped"] += 1
            continue
        if not dry_run:
            try:
                _atomic_write_json(jf, migrated)
            except OSError as e:
                logger.error("写入 %s 失败: %s", jf, e)
                stats["failed"] += 1
                continue
        logger.info("迁移字段: %s", jf.name)
        stats["migrated"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    args = parser.parse_args()

    print("=" * 70)
    print("元模型 → 本体模型 数据迁移")
    print("=" * 70)
    print(f"模式: {'dry-run（仅统计）' if args.dry_run else '执行迁移'}")
    print()

    # 1. 目录与文件迁移
    print("[1/2] 迁移本体模型目录与文件命名...")
    dir_stats = migrate_ontology_templates_dir(args.dry_run)
    print(f"  目录重命名: {dir_stats['dir_renamed']}")
    print(f"  文件重命名: {dir_stats['files_renamed']}")
    print(f"  跳过: {dir_stats['skipped']}")
    print()

    # 2. build_jobs 字段迁移
    print("[2/2] 迁移 build_jobs JSON 字段（template_* → ontology_model_*）...")
    job_stats = migrate_build_jobs_files(args.dry_run)
    print(f"  总文件: {job_stats['total']}")
    print(f"  已迁移: {job_stats['migrated']}")
    print(f"  跳过: {job_stats['skipped']}")
    print(f"  失败: {job_stats['failed']}")
    print()

    print("=" * 70)
    print("迁移完成")
    print("=" * 70)
    return 0 if job_stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
