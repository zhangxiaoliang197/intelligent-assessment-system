from __future__ import annotations

import os
import hashlib
import hmac
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


def _actor_headers(user_id: str, role: str) -> dict:
    payload = f"{user_id}||{role}".encode("utf-8")
    signature = hmac.new(
        config.INTERNAL_SERVICE_TOKEN.encode("utf-8"), payload, hashlib.sha256,
    ).hexdigest()
    return {"X-User-Id": user_id, "X-User-Role": role, "X-Actor-Signature": signature}


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

    def test_builtin_markdown_is_editable_by_any_user(self) -> None:
        viewer_headers = _actor_headers("viewer", "viewer")
        initial = self.client.get(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=viewer_headers,
        ).json()["data"]
        self.assertTrue(initial["editable"])
        self.assertEqual("catalog", initial["storage"])

        description = "通过态势 Skill Markdown 在线编辑更新的说明。"
        changed = _replace_metadata(initial["content"], description=description)
        saved_response = self.client.put(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=viewer_headers,
            json={"content": changed, "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(200, saved_response.status_code, saved_response.text)
        saved = saved_response.json()["data"]
        self.assertEqual("override", saved["storage"])
        self.assertTrue(saved["overridden"])
        self.assertEqual(description, get_skill(BUILTIN_ID)["description"])

        stale = self.client.put(
            f"/situation/skills/{BUILTIN_ID}/markdown",
            headers=viewer_headers,
            json={"content": initial["content"], "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(409, stale.status_code)

    def test_custom_markdown_round_trip_increments_revision(self) -> None:
        headers = _actor_headers("alice", "editor")
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

    def test_custom_markdown_is_editable_by_other_users(self) -> None:
        alice_headers = _actor_headers("alice", "editor")
        created_response = self.client.post(
            "/situation/skills",
            headers=alice_headers,
            json={"definition": _custom_definition()},
        )
        self.assertEqual(200, created_response.status_code, created_response.text)
        created = created_response.json()["data"]
        publish_response = self.client.post(
            f"/situation/skills/{created['id']}/publish",
            headers=alice_headers,
            json={"changeNote": "发布"},
        )
        self.assertEqual(200, publish_response.status_code, publish_response.text)

        bob_headers = _actor_headers("bob", "viewer")
        initial = self.client.get(
            f"/situation/skills/{created['id']}/markdown",
            headers=bob_headers,
        ).json()["data"]
        self.assertTrue(initial["editable"])

        description = "Bob 修改了 Alice 的自定义 Skill Markdown。"
        changed = _replace_metadata(initial["content"], description=description)
        saved = self.client.put(
            f"/situation/skills/{created['id']}/markdown",
            headers=bob_headers,
            json={"content": changed, "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(initial["revision"] + 1, saved.json()["data"]["revision"])
        self.assertEqual(description, get_skill(created["id"], "alice")["description"])

    def test_unsafe_markdown_is_rejected_without_changing_catalog(self) -> None:
        headers = _actor_headers("admin", "admin")
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
