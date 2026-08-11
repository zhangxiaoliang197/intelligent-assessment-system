"""HTTP contract tests for viewing and editing evaluation SKILL.md files."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


QA_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(QA_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(QA_SERVICE_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agents import custom_skill_store  # noqa: E402
from agents.skill_catalog import clear_catalog_cache  # noqa: E402
from evaluation_api import evaluation_router  # noqa: E402
from skill_api import skill_api_router  # noqa: E402


BUILTIN_ID = "combat-effectiveness-overview"


def _custom_payload() -> dict:
    return {
        "name": "Markdown 往返测试 Skill",
        "description": "验证自定义技能 Markdown 在线编辑。",
        "category": "测试",
        "triggers": ["Markdown 测试"],
        "recommendedQuestions": ["运行 Markdown 测试"],
        "steps": [{
            "name": "核验数据",
            "description": "查询测试数据并形成证据。",
            "datasetKeywords": ["test_data", "测试数据"],
        }],
        "outputInstruction": "输出证据和结论。",
    }


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


class SkillMarkdownApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_db_path = custom_skill_store._DB_PATH
        custom_skill_store._DB_PATH = str(root / "custom_skills.sqlite3")
        self.environment = patch.dict(
            os.environ,
            {"EVALUATION_SKILL_MD_OVERRIDE_DIR": str(root / "overrides")},
        )
        self.environment.start()
        clear_catalog_cache()
        app = FastAPI()
        app.include_router(evaluation_router)
        app.include_router(skill_api_router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        clear_catalog_cache()
        self.environment.stop()
        custom_skill_store._DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_builtin_markdown_is_visible_and_admin_can_save_an_override(self) -> None:
        initial_response = self.client.get(f"/evaluation/skills/{BUILTIN_ID}/markdown")
        self.assertEqual(200, initial_response.status_code, initial_response.text)
        initial = initial_response.json()["document"]
        self.assertTrue(initial["content"].startswith("---\n"))
        self.assertEqual("catalog", initial["storage"])
        self.assertTrue(initial["editable"])

        description = "由 Markdown 在线编辑接口更新的综合效能说明。"
        changed = _replace_metadata(initial["content"], description=description)
        saved_response = self.client.put(
            f"/evaluation/skills/{BUILTIN_ID}/markdown",
            json={"content": changed, "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(200, saved_response.status_code, saved_response.text)
        saved = saved_response.json()["document"]
        self.assertEqual("override", saved["storage"])
        self.assertTrue(saved["overridden"])
        self.assertNotEqual(initial["contentHash"], saved["contentHash"])

        catalog = self.client.get("/evaluation/skills").json()["skills"]
        current = next(skill for skill in catalog if skill["id"] == BUILTIN_ID)
        self.assertEqual(description, current["description"])

        stale_response = self.client.put(
            f"/evaluation/skills/{BUILTIN_ID}/markdown",
            json={"content": initial["content"], "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(409, stale_response.status_code)

    def test_builtin_markdown_is_read_only_for_viewers(self) -> None:
        headers = {"X-User-Id": "reader", "X-User-Role": "viewer"}
        response = self.client.get(
            f"/evaluation/skills/{BUILTIN_ID}/markdown",
            headers=headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        document = response.json()["document"]
        self.assertFalse(document["editable"])

        update = self.client.put(
            f"/evaluation/skills/{BUILTIN_ID}/markdown",
            headers=headers,
            json={"content": document["content"], "expectedHash": document["contentHash"]},
        )
        self.assertEqual(403, update.status_code)

    def test_invalid_or_unsafe_markdown_is_rejected_without_changing_catalog(self) -> None:
        initial = self.client.get(
            f"/evaluation/skills/{BUILTIN_ID}/markdown"
        ).json()["document"]

        for changes, message in (
            ({"id": "different-skill"}, "id"),
            ({"sql": "SELECT * FROM secret_table"}, "sql"),
        ):
            with self.subTest(message=message):
                response = self.client.put(
                    f"/evaluation/skills/{BUILTIN_ID}/markdown",
                    json={
                        "content": _replace_metadata(initial["content"], **changes),
                        "expectedHash": initial["contentHash"],
                    },
                )
                self.assertEqual(400, response.status_code, response.text)

        current = self.client.get(
            f"/evaluation/skills/{BUILTIN_ID}/markdown"
        ).json()["document"]
        self.assertEqual(initial["contentHash"], current["contentHash"])

    def test_custom_skill_markdown_round_trip_creates_a_revision(self) -> None:
        created_response = self.client.post("/evaluation/skills", json=_custom_payload())
        self.assertEqual(201, created_response.status_code, created_response.text)
        created = created_response.json()["skill"]

        initial_response = self.client.get(
            f"/evaluation/skills/{created['id']}/markdown"
        )
        self.assertEqual(200, initial_response.status_code, initial_response.text)
        initial = initial_response.json()["document"]
        self.assertEqual("custom", initial["storage"])
        self.assertTrue(initial["editable"])

        description = "自定义技能已通过 Markdown 源码更新。"
        changed = _replace_metadata(initial["content"], description=description)
        changed = changed.rstrip() + "\n\n## 维护说明\n\n该段正文会被完整保留。\n"
        saved_response = self.client.put(
            f"/evaluation/skills/{created['id']}/markdown",
            json={"content": changed, "expectedHash": initial["contentHash"]},
        )
        self.assertEqual(200, saved_response.status_code, saved_response.text)
        saved = saved_response.json()["document"]
        self.assertEqual(2, saved["revision"])
        self.assertIn("该段正文会被完整保留", saved["content"])

        skill = self.client.get(f"/evaluation/skills/{created['id']}").json()["skill"]
        self.assertEqual(description, skill["description"])
        versions = self.client.get(
            f"/evaluation/skills/{created['id']}/versions"
        ).json()["versions"]
        self.assertEqual("在线编辑 SKILL.md", versions[0]["changeNote"])


if __name__ == "__main__":
    unittest.main()
