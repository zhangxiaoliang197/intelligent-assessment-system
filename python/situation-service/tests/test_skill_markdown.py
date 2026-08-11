from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

import config
import skills.store as skill_store
from main import app
from skills.catalog import clear_catalog_cache, get_skill


BUILTIN_ID = "force-readiness"


def _replace_metadata(content: str, **changes) -> str:
    lines = content.splitlines()
    closing_index = lines[1:].index("---") + 1
    metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    metadata.update(changes)
    body = "\n".join(lines[closing_index + 1:]).strip()
    if "name" in changes:
        body_lines = body.splitlines()
        body_lines[0] = f"# {changes['name']}"
        body = "\n".join(body_lines)
    front_matter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    ).strip()
    return f"---\n{front_matter}\n---\n\n{body}\n"


def _custom_definition() -> dict:
    source = get_skill(BUILTIN_ID)
    assert source is not None
    fields = {
        "name", "description", "category", "triggers", "recommendedQuestions",
        "inputHints", "steps", "dataSources", "chartTypes", "mapLayerTypes",
        "focusMetrics", "analysisGoal", "featured",
    }
    definition = {key: source[key] for key in fields if key in source}
    definition["name"] = "态势 Markdown 自定义测试"
    definition["featured"] = False
    return definition


class SituationSkillMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_db = config.SITUATION_SKILL_DB
        config.SITUATION_SKILL_DB = str(root / "skills.sqlite3")
        skill_store._SCHEMA_READY = False
        self.environment = patch.dict(
            os.environ,
            {"SITUATION_SKILL_MD_OVERRIDE_DIR": str(root / "overrides")},
        )
        self.environment.start()
        clear_catalog_cache()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        clear_catalog_cache()
        self.environment.stop()
        config.SITUATION_SKILL_DB = self.original_db
        skill_store._SCHEMA_READY = False
        self.temp_dir.cleanup()

    def test_builtin_markdown_permissions_override_and_conflict(self) -> None:
        viewer_headers = {"X-User-Id": "viewer", "X-User-Role": "viewer"}
        viewer_response = self.client.get(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=viewer_headers,
        )
        self.assertEqual(200, viewer_response.status_code, viewer_response.text)
        self.assertFalse(viewer_response.json()["data"]["editable"])

        admin_headers = {"X-User-Id": "admin", "X-User-Role": "admin"}
        initial = self.client.get(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=admin_headers,
        ).json()["data"]
        self.assertTrue(initial["editable"])
        self.assertEqual("catalog", initial["storage"])

        description = "通过态势 Skill Markdown 在线编辑更新的说明。"
        changed = _replace_metadata(initial["content"], description=description)
        saved_response = self.client.put(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=admin_headers,
            json={"content": changed, "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(200, saved_response.status_code, saved_response.text)
        saved = saved_response.json()["data"]
        self.assertEqual("override", saved["storage"])
        self.assertTrue(saved["overridden"])
        self.assertEqual(description, get_skill(BUILTIN_ID)["description"])

        stale = self.client.put(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=admin_headers,
            json={"content": initial["content"], "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(409, stale.status_code)

    def test_custom_markdown_round_trip_increments_revision(self) -> None:
        headers = {"X-User-Id": "alice", "X-User-Role": "editor"}
        created_response = self.client.post(
            "/situation/skills",
            headers=headers,
            json={"definition": _custom_definition()},
        )
        self.assertEqual(200, created_response.status_code, created_response.text)
        created = created_response.json()["data"]

        initial = self.client.get(
            f"/situation/skills/{created['id']}/markdown",
            headers=headers,
        ).json()["data"]
        self.assertTrue(initial["editable"])
        description = "自定义态势 Skill 已通过 Markdown 修改。"
        changed = _replace_metadata(initial["content"], description=description)
        changed = changed.rstrip() + "\n\n## 维护说明\n\n该正文需要完整保留。\n"
        saved_response = self.client.put(
            f"/situation/skills/{created['id']}/markdown",
            headers=headers,
            json={"content": changed, "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(200, saved_response.status_code, saved_response.text)
        saved = saved_response.json()["data"]
        self.assertEqual(2, saved["revision"])
        self.assertIn("该正文需要完整保留", saved["content"])
        self.assertEqual(description, get_skill(created["id"], "alice")["description"])

    def test_unsafe_markdown_is_rejected_without_changing_catalog(self) -> None:
        headers = {"X-User-Id": "admin", "X-User-Role": "admin"}
        initial = self.client.get(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=headers,
        ).json()["data"]
        unsafe = _replace_metadata(initial["content"], sql="SELECT * FROM secret")
        response = self.client.put(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=headers,
            json={"content": unsafe, "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(400, response.status_code, response.text)
        current = self.client.get(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=headers,
        ).json()["data"]
        self.assertEqual(initial["contentHash"], current["contentHash"])


if __name__ == "__main__":
    unittest.main()
