"""Governance, versioning and catalog-product capability tests."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


QA_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(QA_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(QA_SERVICE_ROOT))

from agents import custom_skill_store  # noqa: E402
from agents.skill_catalog import (  # noqa: E402
    SkillPermissionError,
    create_custom_skill,
    create_skill_from_template,
    create_skill_share,
    duplicate_skill,
    export_skill,
    get_skill,
    import_skill_definitions,
    list_favorite_skill_ids,
    list_skill_templates,
    list_skill_versions,
    list_skills,
    publish_custom_skill,
    recommend_skills,
    resolve_skill_share,
    revoke_skill_share,
    rollback_custom_skill,
    set_skill_favorite,
    update_custom_skill,
)
from agents.skill_governance import (  # noqa: E402
    SkillActor,
    export_skill_bundle,
    parse_skill_import,
    skill_permissions,
)


def _payload(name: str = "治理能力评估") -> dict:
    return {
        "name": name,
        "description": "验证归属、权限、版本以及目录扩展能力。",
        "category": "治理测试",
        "triggers": ["治理评估"],
        "recommendedQuestions": ["请执行治理评估"],
        "steps": [
            {
                "name": "查询治理数据",
                "description": "读取治理测试数据集。",
                "datasetKeywords": ["governance_data"],
            }
        ],
        "outputInstruction": "输出治理评估结论。",
    }


class SkillGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = custom_skill_store._DB_PATH
        custom_skill_store._DB_PATH = str(Path(self.temp_dir.name) / "skills.sqlite3")
        self.owner = SkillActor("owner-1", "viewer", ("team-a",))
        self.teammate = SkillActor("editor-1", "editor", ("team-a",))
        self.publisher = SkillActor("publisher-1", "publisher", ("team-a",))
        self.outsider = SkillActor("outsider", "viewer", ("team-b",))

    def tearDown(self) -> None:
        custom_skill_store._DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_private_owner_and_team_permissions_are_enforced(self) -> None:
        private = create_custom_skill(_payload(), self.owner)

        self.assertEqual("owner-1", private["ownerId"])
        self.assertEqual("private", private["visibility"])
        self.assertEqual("draft", private["status"])
        self.assertIsNone(get_skill(private["id"], self.outsider))
        self.assertTrue(get_skill(private["id"], self.owner)["editable"])

        team_payload = _payload("团队治理 Skill")
        team_payload.update({"teamId": "team-a", "visibility": "team", "tags": ["治理", "测试"]})
        team_skill = create_custom_skill(team_payload, self.owner)
        teammate_view = get_skill(team_skill["id"], self.teammate)

        self.assertIsNotNone(teammate_view)
        self.assertTrue(teammate_view["editable"])
        self.assertFalse(teammate_view["publishable"])
        self.assertTrue(get_skill(team_skill["id"], self.publisher)["publishable"])
        self.assertIsNone(get_skill(team_skill["id"], self.outsider))

        with self.assertRaises(SkillPermissionError):
            publish_custom_skill(team_skill["id"], team_skill["revision"], self.teammate)

    def test_versions_publish_and_rollback_create_auditable_snapshots(self) -> None:
        created = create_custom_skill(_payload("版本一"), self.owner)
        changed_payload = _payload("版本二")
        updated = update_custom_skill(
            created["id"], changed_payload, created["revision"], self.owner
        )
        published = publish_custom_skill(
            created["id"], updated["revision"], self.owner
        )

        versions = list_skill_versions(created["id"], self.owner)
        self.assertEqual([3, 2, 1], [item["version"] for item in versions])
        self.assertEqual("publish", versions[0]["action"])
        self.assertEqual(3, published["publishedVersion"])
        self.assertEqual("published", published["status"])

        rolled_back = rollback_custom_skill(
            created["id"], 1, published["revision"], self.owner
        )
        self.assertEqual("版本一", rolled_back["name"])
        self.assertEqual("owner-1", rolled_back["ownerId"])
        self.assertEqual(4, rolled_back["revision"])
        self.assertEqual(4, rolled_back["version"])
        self.assertEqual("rollback:1", list_skill_versions(created["id"], self.owner)[0]["action"])

    def test_recommendation_explains_dataset_completeness(self) -> None:
        payload = _payload("可推荐治理 Skill")
        payload["status"] = "published"
        created = create_custom_skill(payload, self.owner)

        recommendations = recommend_skills(
            "请做治理评估",
            3,
            [
                {
                    "id": "governance",
                    "name": "治理数据",
                    "tableName": "governance_data",
                }
            ],
            self.owner,
        )

        recommendation = next(item for item in recommendations if item["id"] == created["id"])
        self.assertEqual(1.0, recommendation["dataCompleteness"])
        self.assertTrue(recommendation["availability"]["complete"])
        self.assertGreater(
            recommendation["recommendationScore"], recommendation["relevanceScore"]
        )

    def test_favorites_templates_copy_share_and_portable_import_export(self) -> None:
        created = create_custom_skill(_payload("产品化 Skill"), self.owner)
        favorite = set_skill_favorite(created["id"], True, self.owner)
        self.assertTrue(favorite["favorite"])
        self.assertIn(created["id"], list_favorite_skill_ids(self.owner))
        self.assertTrue(
            next(skill for skill in list_skills(self.owner) if skill["id"] == created["id"])[
                "favorite"
            ]
        )

        template = duplicate_skill(
            created["id"], {"name": "治理模板"}, self.owner, as_template=True
        )
        self.assertTrue(template["isTemplate"])
        self.assertIn(template["id"], [item["id"] for item in list_skill_templates(self.owner)])
        instance = create_skill_from_template(
            template["id"], {"name": "模板实例"}, self.owner
        )
        self.assertFalse(instance["isTemplate"])
        self.assertEqual("draft", instance["status"])

        share = create_skill_share(created["id"], self.owner)
        resolved = resolve_skill_share(share["token"])
        self.assertEqual(created["id"], resolved["skill"]["id"])
        revoked = revoke_skill_share(share["token"], self.owner)
        self.assertFalse(revoked["active"])

        document = export_skill(created["id"], self.owner)
        definitions = parse_skill_import(json.dumps(document, ensure_ascii=False))
        self.assertEqual("产品化 Skill", definitions[0]["name"])
        bundle = export_skill_bundle([created])
        imported = import_skill_definitions(bundle, self.owner, conflict_policy="rename")
        self.assertEqual(1, len(imported["created"]))
        self.assertNotEqual(created["name"], imported["created"][0]["name"])

    def test_legacy_database_is_migrated_with_shared_published_defaults(self) -> None:
        database = sqlite3.connect(custom_skill_store._DB_PATH)
        legacy = _payload("旧版 Skill")
        legacy["id"] = "custom-legacy"
        legacy["steps"][0]["id"] = "governance-data"
        try:
            database.execute(
                """
                CREATE TABLE custom_skills (
                    id TEXT PRIMARY KEY,
                    name_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                "INSERT INTO custom_skills VALUES (?, ?, ?, 1, ?, ?)",
                (
                    legacy["id"],
                    "旧版skill",
                    json.dumps(legacy, ensure_ascii=False),
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )
            database.commit()
        finally:
            database.close()

        migrated = get_skill("custom-legacy")
        self.assertEqual("local-admin", migrated["ownerId"])
        self.assertEqual("public", migrated["visibility"])
        self.assertEqual("published", migrated["status"])
        self.assertEqual(1, len(list_skill_versions("custom-legacy")))

    def test_policy_pure_function_rejects_outsider_mutations(self) -> None:
        governed = {
            "source": "custom",
            "ownerId": "owner-1",
            "teamId": "team-a",
            "visibility": "team",
            "status": "published",
        }
        permissions = skill_permissions(governed, self.outsider)
        self.assertFalse(permissions["visible"])
        self.assertFalse(permissions["editable"])


if __name__ == "__main__":
    unittest.main()
