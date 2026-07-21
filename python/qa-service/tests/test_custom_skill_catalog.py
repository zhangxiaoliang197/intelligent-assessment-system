"""Persistence and lifecycle tests for user-authored evaluation Skills."""

from __future__ import annotations

import sys
import tempfile
import unittest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


QA_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(QA_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(QA_SERVICE_ROOT))

from agents import custom_skill_store  # noqa: E402
from agents.skill_catalog import (  # noqa: E402
    SkillConflictError,
    SkillReadOnlyError,
    create_custom_skill,
    delete_custom_skill,
    get_custom_catalog_warning,
    get_skill,
    list_builtin_skills,
    list_skills,
    recommend_skills,
    resolve_skill_datasets,
    update_custom_skill,
)


def _payload(name: str = "自定义保障评估") -> dict:
    return {
        "name": name,
        "description": "先核验库存，再分析消耗，形成用户自定义保障结论。",
        "category": "自定义",
        "triggers": ["我的保障评估"],
        "recommendedQuestions": ["按自定义顺序评估保障能力"],
        "steps": [
            {
                "name": "核验库存",
                "description": "查询当前关键物资库存。",
                "datasetKeywords": ["inventory", "库存"],
                "datasetId": "dataset-inventory",
            },
            {
                "name": "分析消耗",
                "description": "查询资源消耗速度。",
                "datasetKeywords": ["resource_consume", "消耗"],
            },
        ],
        "outputInstruction": "按库存、消耗和保障风险三部分输出，并标注数据缺口。",
    }


class CustomSkillCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = custom_skill_store._DB_PATH
        custom_skill_store._DB_PATH = str(Path(self.temp_dir.name) / "custom_skills.sqlite3")

    def tearDown(self) -> None:
        custom_skill_store._DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_create_update_recommend_and_delete_custom_skill(self) -> None:
        created = create_custom_skill(_payload())

        self.assertTrue(created["id"].startswith("custom-"))
        self.assertEqual("custom", created["source"])
        self.assertTrue(created["editable"])
        self.assertEqual(1, created["revision"])
        self.assertEqual(16, len(list_skills()))
        self.assertEqual(created["id"], get_skill(created["id"])["id"])
        self.assertEqual(created["id"], recommend_skills("请做我的保障评估", 1)[0]["id"])

        changed_payload = _payload("自定义保障风险复盘")
        changed_payload["steps"] = list(reversed(changed_payload["steps"]))
        updated = update_custom_skill(created["id"], changed_payload, created["revision"])

        self.assertEqual(2, updated["revision"])
        self.assertEqual("分析消耗", updated["steps"][0]["name"])
        with self.assertRaises(SkillConflictError):
            update_custom_skill(created["id"], changed_payload, created["revision"])

        deleted = delete_custom_skill(created["id"], updated["revision"])
        self.assertEqual(created["id"], deleted["id"])
        self.assertIsNone(get_skill(created["id"]))
        self.assertEqual(15, len(list_skills()))

    def test_built_in_skills_are_immutable(self) -> None:
        built_in = list_builtin_skills()[0]

        with self.assertRaises(SkillReadOnlyError):
            update_custom_skill(built_in["id"], _payload(), 1)
        with self.assertRaises(SkillReadOnlyError):
            delete_custom_skill(built_in["id"], 1)
        self.assertEqual(15, len(list_builtin_skills()))

    def test_exact_dataset_id_wins_over_conflicting_keywords(self) -> None:
        skill = _payload()
        skill["steps"] = [
            {
                "id": "exact",
                "name": "精确绑定",
                "description": "验证精确绑定优先级",
                "datasetId": "wanted",
                "datasetKeywords": ["wrong_table"],
            }
        ]
        datasets = [
            {"id": "keyword", "name": "错误候选", "tableName": "wrong_table"},
            {"id": "wanted", "name": "指定数据集", "tableName": "actual_table"},
        ]

        plan = resolve_skill_datasets(skill, datasets)

        self.assertEqual("wanted", plan[0]["dataset"]["id"])
        self.assertEqual(1000, plan[0]["score"])

        missing_plan = resolve_skill_datasets(skill, datasets[:1])
        self.assertIsNone(missing_plan[0]["dataset"])

    def test_corrupt_custom_database_does_not_hide_builtins(self) -> None:
        Path(custom_skill_store._DB_PATH).write_bytes(b"not a sqlite database")

        skills = list_skills()

        self.assertEqual(15, len(skills))
        self.assertTrue(all(skill["source"] == "builtin" for skill in skills))
        self.assertTrue(get_custom_catalog_warning())

    def test_concurrent_creates_cannot_duplicate_a_skill_name(self) -> None:
        list_skills()  # initialize the SQLite schema before racing writers

        def create_once(_: int) -> str:
            try:
                return create_custom_skill(_payload("并发同名 Skill"))["id"]
            except SkillConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(create_once, range(12)))

        self.assertEqual(1, sum(result != "conflict" for result in results))
        same_name = [skill for skill in list_skills() if skill["name"] == "并发同名 Skill"]
        self.assertEqual(1, len(same_name))

    def test_malformed_row_is_reported_and_can_still_be_deleted(self) -> None:
        list_skills()
        connection = sqlite3.connect(custom_skill_store._DB_PATH)
        try:
            connection.execute(
                """
                INSERT INTO custom_skills
                    (id, name_key, payload_json, revision, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                ("custom-broken", "broken", "{not-json", "2026-01-01", "2026-01-01"),
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(15, len(list_skills()))
        self.assertIn("custom-broken", get_custom_catalog_warning())

        deleted = delete_custom_skill("custom-broken", 1)
        self.assertEqual("custom-broken", deleted["id"])

    def test_filesystem_error_does_not_hide_builtins(self) -> None:
        parent_file = Path(self.temp_dir.name) / "not-a-directory"
        parent_file.write_text("occupied", encoding="utf-8")
        custom_skill_store._DB_PATH = str(parent_file / "skills.sqlite3")

        skills = list_skills()

        self.assertEqual(15, len(skills))
        self.assertTrue(get_custom_catalog_warning())


if __name__ == "__main__":
    unittest.main()
