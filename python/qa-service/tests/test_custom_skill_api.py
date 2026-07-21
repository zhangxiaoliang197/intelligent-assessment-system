"""HTTP contract tests for custom Skill CRUD endpoints."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


QA_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(QA_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(QA_SERVICE_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agents import custom_skill_store  # noqa: E402
from evaluation_api import evaluation_router  # noqa: E402
from skill_api import skill_api_router  # noqa: E402


def _payload() -> dict:
    return {
        "name": "HTTP 自定义 Skill",
        "description": "通过 HTTP 接口验证按步骤编写 Skill。",
        "category": "自定义",
        "triggers": ["HTTP Skill"],
        "recommendedQuestions": ["运行 HTTP 自定义 Skill"],
        "steps": [
            {
                "name": "查询战果",
                "description": "查询战果数据并核验目标完成情况。",
                "datasetKeywords": ["combat_result", "战果"],
                "allowReuse": False,
            }
        ],
        "outputInstruction": "按证据、结论和缺口输出。",
    }


class CustomSkillApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = custom_skill_store._DB_PATH
        custom_skill_store._DB_PATH = str(Path(self.temp_dir.name) / "skills.sqlite3")
        app = FastAPI()
        app.include_router(evaluation_router)
        app.include_router(skill_api_router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        custom_skill_store._DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_crud_revision_and_immutable_builtins(self) -> None:
        created_response = self.client.post("/evaluation/skills", json=_payload())
        self.assertEqual(201, created_response.status_code)
        created = created_response.json()["skill"]

        catalog = self.client.get("/evaluation/skills").json()
        self.assertEqual(16, catalog["total"])
        self.assertEqual(15, catalog["builtInTotal"])
        self.assertEqual(1, catalog["customTotal"])

        update_payload = _payload()
        update_payload["name"] = "HTTP 自定义 Skill 已更新"
        update_payload["expectedRevision"] = created["revision"]
        updated_response = self.client.put(
            f"/evaluation/skills/{created['id']}", json=update_payload
        )
        self.assertEqual(200, updated_response.status_code)
        updated = updated_response.json()["skill"]
        self.assertEqual(2, updated["revision"])

        stale_response = self.client.put(
            f"/evaluation/skills/{created['id']}", json=update_payload
        )
        self.assertEqual(409, stale_response.status_code)

        built_in_response = self.client.put(
            "/evaluation/skills/combat-effectiveness-overview",
            json={**_payload(), "expectedRevision": 1},
        )
        self.assertEqual(403, built_in_response.status_code)

        deleted_response = self.client.delete(
            f"/evaluation/skills/{created['id']}",
            params={"expectedRevision": updated["revision"]},
        )
        self.assertEqual(200, deleted_response.status_code)
        self.assertEqual(15, self.client.get("/evaluation/skills").json()["total"])

    def test_client_cannot_submit_sql_or_table_name(self) -> None:
        payload = copy.deepcopy(_payload())
        payload["steps"][0]["sql"] = "SELECT * FROM secret"
        payload["steps"][0]["tableName"] = "secret"

        response = self.client.post("/evaluation/skills", json=payload)

        self.assertEqual(422, response.status_code)

    def test_recommendation_reports_zero_completeness_for_empty_data_source(self) -> None:
        with patch("agents.tools.fetch_datasets_for_database", return_value=[]):
            response = self.client.post(
                "/evaluation/skills/recommend",
                json={
                    "query": "请评估整体作战效能",
                    "dataSourceId": "empty-source",
                    "limit": 3,
                },
            )

        self.assertEqual(200, response.status_code, response.text)
        recommendations = response.json()["skills"]
        self.assertTrue(recommendations)
        self.assertEqual(0, recommendations[0]["availability"]["matchedSteps"])
        self.assertEqual(0.0, recommendations[0]["availability"]["completeness"])
        self.assertFalse(recommendations[0]["availability"]["available"])

    def test_governance_routes_publish_share_export_clone_and_import(self) -> None:
        created_response = self.client.post("/evaluation/skills", json=_payload())
        self.assertEqual(201, created_response.status_code, created_response.text)
        created = created_response.json()["skill"]
        self.assertEqual(1, created["version"])

        favorite = self.client.put(f"/evaluation/skills/{created['id']}/favorite")
        self.assertEqual(200, favorite.status_code, favorite.text)
        self.assertTrue(favorite.json()["favorite"])

        published_response = self.client.post(
            f"/evaluation/skills/{created['id']}/publish",
            json={"expectedRevision": created["revision"], "changeNote": "首次发布"},
        )
        self.assertEqual(200, published_response.status_code, published_response.text)
        published = published_response.json()["skill"]
        self.assertEqual("published", published["status"])
        self.assertEqual(2, published["version"])

        versions = self.client.get(f"/evaluation/skills/{created['id']}/versions")
        self.assertEqual(200, versions.status_code, versions.text)
        self.assertGreaterEqual(versions.json()["total"], 2)
        self.assertEqual("首次发布", versions.json()["versions"][0]["changeNote"])

        shared = self.client.post(f"/evaluation/skills/{created['id']}/share", json={})
        self.assertEqual(201, shared.status_code, shared.text)
        self.assertTrue(shared.json()["url"].startswith("/api/evaluation/shared-skills/"))
        shared_view = self.client.get(
            f"/evaluation/shared-skills/{shared.json()['token']}"
        )
        self.assertEqual(200, shared_view.status_code, shared_view.text)
        self.assertEqual(created["id"], shared_view.json()["skill"]["id"])

        exported = self.client.get(f"/evaluation/skills/{created['id']}/export")
        self.assertEqual(200, exported.status_code, exported.text)
        document = exported.json()["document"]

        cloned = self.client.post(
            f"/evaluation/skills/{created['id']}/clone",
            json={"name": "HTTP Skill 副本", "asTemplate": True},
        )
        self.assertEqual(201, cloned.status_code, cloned.text)
        self.assertNotEqual(created["id"], cloned.json()["skill"]["id"])
        self.assertTrue(cloned.json()["skill"]["isTemplate"])

        imported = self.client.post(
            "/evaluation/skills/import",
            json={"document": document, "conflictPolicy": "rename"},
        )
        self.assertEqual(201, imported.status_code, imported.text)
        self.assertEqual(1, imported.json()["imported"])

        rolled_back = self.client.post(
            f"/evaluation/skills/{created['id']}/rollback",
            json={"version": 1, "expectedRevision": published["revision"]},
        )
        self.assertEqual(200, rolled_back.status_code, rolled_back.text)
        self.assertGreater(rolled_back.json()["skill"]["revision"], published["revision"])


if __name__ == "__main__":
    unittest.main()
