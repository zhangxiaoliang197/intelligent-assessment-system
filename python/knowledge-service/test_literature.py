import copy
from dataclasses import dataclass
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
import literature


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    title: str = ""
    category: str = ""
    tags: list | None = None
    source_file: str = ""


class LiteratureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.identifier = "kb_lit_" + "a" * 20
        self.old = {"id": self.identifier, "title": "评估方法研究", "upload_time": "2026-11-17T10:00:00", "literature": {"content_level": "abstract"}}
        self.vector_client = SimpleNamespace(delete=Mock())
        self.app = SimpleNamespace(knowledge_db=[copy.deepcopy(self.old), {"id": "other"}],
            chunks_db=[Chunk("old", self.identifier, "摘要"), Chunk("other", "other", "其他知识")],
            categories_db={"评估": [self.identifier]}, tags_db={"摘要": [self.identifier]},
            UPLOAD_DIR=self.temp.name, Chunk=Chunk, chunk_text=lambda text, **kwargs: [text],
            upsert_chunks_to_qdrant=Mock(), save_db=Mock(), _bm25_index=None,
            get_qdrant_client=lambda: self.vector_client, QDRANT_COLLECTION="test", chunk_id_to_int=lambda identifier: 123)
        self.patch = patch.object(literature, "service", return_value=self.app)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def batch(self):
        return literature.LiteratureBatch(records=[literature.LiteratureRecord(
            record_id="lit_" + "a" * 20, title="评估方法研究", language="zh", content_level="fulltext",
            text="完整论文正文。" * 20, source_url="https://example.org/paper", pdf_url="https://example.org/paper.pdf",
            page_count=5, pdf_sha256="b" * 64, license="cc-by")])

    async def test_promote_abstract_to_fulltext_then_skip_repeat(self):
        result = await literature.import_literature(self.batch())
        self.assertEqual(result["items"][0]["status"], "upgraded")
        self.assertEqual(len(self.app.knowledge_db), 2)
        self.assertEqual(self.app.knowledge_db[0]["literature"]["page_count"], 5)
        self.assertEqual(self.app.knowledge_db[0]["upload_time"], self.old["upload_time"])
        self.assertEqual(len(self.app.chunks_db), 2)
        self.assertTrue(any(chunk.chunk_id == "other" for chunk in self.app.chunks_db))
        self.vector_client.delete.assert_called_once()
        self.assertTrue((Path(self.temp.name) / (self.identifier + ".md")).is_file())
        second = await literature.import_literature(self.batch())
        self.assertEqual(second["skipped"], 1)
        self.app.upsert_chunks_to_qdrant.assert_called_once()

    async def test_index_failure_preserves_original_document_and_chunks(self):
        self.app.upsert_chunks_to_qdrant.side_effect = RuntimeError("unavailable")
        with self.assertRaises(HTTPException) as context:
            await literature.import_literature(self.batch())
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(self.app.knowledge_db[0], self.old)
        self.assertEqual(self.app.chunks_db[0].chunk_id, "old")
        self.app.save_db.assert_not_called()
        self.vector_client.delete.assert_not_called()

    async def test_source_correction_reuses_unchanged_body_vectors(self):
        tags = ["评估研究", "中文", "开放全文", "学术文献"]
        self.app.knowledge_db[0]["literature"] = {"content_level": "fulltext", "text_sha256": "old"}
        self.app.chunks_db = [
            Chunk("body", self.identifier, "已有正文", "评估方法研究", "评估研究", tags, "评估方法研究.md"),
            Chunk("header", self.identifier, "旧来源", "评估方法研究", "评估研究", tags, "评估方法研究.md"),
        ]
        self.app.chunk_text = lambda text, **kwargs: ["新来源", "已有正文"]
        result = await literature.import_literature(self.batch())
        self.assertEqual(result["items"][0]["status"], "upgraded")
        inserted = self.app.upsert_chunks_to_qdrant.call_args.args[0]
        self.assertEqual([chunk.text for chunk in inserted], ["新来源"])
        self.assertIn("body", [chunk.chunk_id for chunk in self.app.chunks_db])
        self.assertNotIn("header", [chunk.chunk_id for chunk in self.app.chunks_db])


if __name__ == "__main__":
    unittest.main()
