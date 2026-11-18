"""Idempotent literature ingestion with explicit content levels and citations."""
import asyncio
from collections import defaultdict
from datetime import datetime
import hashlib
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


router = APIRouter(prefix="/knowledge/literature", tags=["文献知识库"])
import_lock = asyncio.Lock()


class LiteratureRecord(BaseModel):
    record_id: str = Field(pattern=r"^lit_[a-f0-9]{20}$")
    title: str = Field(min_length=1, max_length=2000)
    language: Literal["zh", "en"]
    content_level: Literal["fulltext", "abstract", "metadata"]
    text: str = Field(min_length=40, max_length=2_000_000)
    topic: str = Field(default="评估研究", max_length=100)
    source_url: str = Field(min_length=1, max_length=4000)
    openalex_id: str = ""
    doi: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    journal: str = ""
    license: str | None = None
    metadata_source: str = "OpenAlex (CC0)"
    pdf_url: str | None = None
    pdf_sha256: str = ""
    page_count: int | None = None
    fulltext_characters: int | None = None
    license_url: str = ""
    license_evidence: str = ""


class LiteratureBatch(BaseModel):
    records: list[LiteratureRecord] = Field(min_length=1, max_length=100)


def service():
    import main
    return main


@router.get("/stats")
async def literature_stats():
    records = [item for item in service().knowledge_db if item.get("literature")]
    return {"success": True, "data": {
        "total": len(records),
        "zh": sum(item["literature"].get("language") == "zh" for item in records),
        "en": sum(item["literature"].get("language") == "en" for item in records),
        "levels": {level: sum(item["literature"].get("content_level") == level for item in records) for level in ("fulltext", "abstract", "metadata")},
    }}


@router.get("/{record_id}/pdf")
async def literature_pdf(record_id: str):
    if not re.fullmatch(r"lit_[a-f0-9]{20}", record_id):
        raise HTTPException(404, "文献不存在")
    app = service()
    document = next((item for item in app.knowledge_db if item["id"] == "kb_" + record_id), None)
    if not document or (document.get("literature") or {}).get("content_level") != "fulltext":
        raise HTTPException(404, "该文献尚未收录全文")
    data_dir = Path(app.BASE_DIR) / "data"
    for corpus in ("literature-fulltext-100", "literature-1000"):
        path = data_dir / corpus / "fulltext" / (record_id + ".pdf")
        if path.is_file() and path.resolve().is_relative_to(data_dir.resolve()):
            return FileResponse(path, media_type="application/pdf", filename=document["title"] + ".pdf", content_disposition_type="inline")
    raise HTTPException(404, "全文 PDF 原件不存在")


@router.post("/import")
async def import_literature(batch: LiteratureBatch):
    app = service()
    async with import_lock:
        existing = {item["id"]: item for item in app.knowledge_db}
        items, chunks, results, seen, upgraded, reused = [], [], [], set(), set(), set()
        levels = {"fulltext": "开放全文", "abstract": "论文摘要", "metadata": "仅题录"}
        for record in batch.records:
            doc_id = "kb_" + record.record_id
            previous = existing.get(doc_id)
            text_digest = hashlib.sha256(record.text.encode("utf-8")).hexdigest()
            promote = bool(previous and record.content_level == "fulltext" and (previous.get("literature", {}).get("content_level") != "fulltext" or previous.get("literature", {}).get("text_sha256") != text_digest))
            if previous and not promote and record.content_level == "fulltext" and record.pdf_sha256:
                citation = record.model_dump(exclude={"text"})
                stored = previous.get("literature", {})
                if stored.get("pdf_sha256") in (None, "", record.pdf_sha256) and any(stored.get(key) != value for key, value in citation.items()):
                    stored.update(citation)
                    app.save_db()
            if (previous and not promote) or doc_id in seen:
                results.append({"id": doc_id, "record_id": record.record_id, "status": "already-imported"})
                continue
            seen.add(doc_id)
            if promote:
                upgraded.add(doc_id)
            tags = [record.topic, "中文" if record.language == "zh" else "英文", levels[record.content_level], "学术文献"]
            filename = record.title[:160].replace("/", "_").replace("\\", "_") + ".md"
            document_path = Path(app.UPLOAD_DIR) / f"{doc_id}.md"
            text_chunks = app.chunk_text(record.text, chunk_size=400, overlap=100)
            if not text_chunks:
                raise HTTPException(422, f"文献“{record.title}”没有可检索文本")
            text_version = text_digest[:12]
            reusable = defaultdict(list)
            for old_chunk in app.chunks_db:
                if old_chunk.doc_id == doc_id and old_chunk.title == record.title and old_chunk.category == record.topic and old_chunk.tags == tags and old_chunk.source_file == filename:
                    reusable[old_chunk.text].append(old_chunk.chunk_id)
            new_chunks = [app.Chunk(
                chunk_id=f"{doc_id}_{text_version}_c{index}", doc_id=doc_id, text=text,
                title=record.title, category=record.topic, tags=tags, source_file=filename,
            ) for index, text in enumerate(text_chunks)]
            for chunk in new_chunks:
                if reusable[chunk.text]:
                    chunk.chunk_id = reusable[chunk.text].pop()
                    reused.add(chunk.chunk_id)
            citation = record.model_dump(exclude={"text"})
            citation["chunk_size"] = 400
            citation["text_sha256"] = text_digest
            items.append({
                "id": doc_id, "title": record.title, "filename": filename,
                "file_path": str(document_path), "file_size": len(record.text.encode("utf-8")),
                "file_type": "MD", "category": record.topic, "tags": tags,
                "status": "已完成", "upload_time": previous["upload_time"] if previous else datetime.now().isoformat(),
                "content_length": len(record.text), "chunk_count": len(new_chunks),
                "literature": citation,
            })
            chunks.extend(new_chunks)
            results.append({"id": doc_id, "record_id": record.record_id, "status": "upgraded" if promote else "imported", "content_level": record.content_level, "chunk_count": len(new_chunks)})
        if chunks:
            try:
                vector_chunks = [chunk for chunk in chunks if chunk.chunk_id not in reused]
                if vector_chunks:
                    await asyncio.to_thread(app.upsert_chunks_to_qdrant, vector_chunks)
            except Exception as error:
                raise HTTPException(503, f"文献向量索引失败，本批未入库，可安全重试：{str(error)[:300]}") from error
            by_id = {"kb_" + record.record_id: record for record in batch.records}
            retired_chunks = [chunk for chunk in app.chunks_db if chunk.doc_id in upgraded]
            for item in items:
                Path(item["file_path"]).write_text(by_id[item["id"]].text, encoding="utf-8")
                if item["id"] in upgraded:
                    position = next(i for i, old in enumerate(app.knowledge_db) if old["id"] == item["id"])
                    app.knowledge_db[position] = item
                    for mapping in (app.categories_db, app.tags_db):
                        for values in mapping.values():
                            values[:] = [value for value in values if value != item["id"]]
                else:
                    app.knowledge_db.append(item)
                app.categories_db.setdefault(item["category"], []).append(item["id"])
                for tag in item["tags"]:
                    app.tags_db.setdefault(tag, []).append(item["id"])
            app.chunks_db[:] = [chunk for chunk in app.chunks_db if chunk.doc_id not in upgraded] + chunks
            app._bm25_index = None
            app.save_db()
            current_ids = {chunk.chunk_id for chunk in chunks}
            retired_chunks = [chunk for chunk in retired_chunks if chunk.chunk_id not in current_ids]
            if retired_chunks:
                from qdrant_client.models import PointIdsList
                await asyncio.to_thread(app.get_qdrant_client().delete, collection_name=app.QDRANT_COLLECTION,
                    points_selector=PointIdsList(points=[app.chunk_id_to_int(chunk.chunk_id) for chunk in retired_chunks]))
    return {"success": True, "items": results, "imported": len(items), "skipped": len(results) - len(items)}


@router.post("/reindex")
async def reindex_literature():
    """Stage new 400-character chunks before replacing only literature indices."""
    app = service()
    async with import_lock:
        documents = [item for item in app.knowledge_db if item.get("literature")]
        ids = {item["id"] for item in documents}
        old_chunks = [chunk for chunk in app.chunks_db if chunk.doc_id in ids]
        staged, counts = [], {}
        for item in documents:
            path = Path(item["file_path"])
            text = path.read_text(encoding="utf-8")
            texts = app.chunk_text(text, chunk_size=400, overlap=100)
            counts[item["id"]] = len(texts)
            staged.extend(app.Chunk(
                chunk_id=f"{item['id']}_v2_c{index}", doc_id=item["id"], text=text,
                title=item["title"], category=item["category"], tags=item["tags"], source_file=item["filename"],
            ) for index, text in enumerate(texts))
        try:
            for offset in range(0, len(staged), 128):
                await asyncio.to_thread(app.upsert_chunks_to_qdrant, staged[offset:offset + 128])
        except Exception as error:
            raise HTTPException(503, f"新索引尚未完成，原知识分片仍保留：{str(error)[:200]}") from error
        app.chunks_db[:] = [chunk for chunk in app.chunks_db if chunk.doc_id not in ids] + staged
        for item in documents:
            item["chunk_count"] = counts[item["id"]]
            item["literature"]["chunk_size"] = 400
        app._bm25_index = None
        app.save_db()
        from qdrant_client.models import PointIdsList
        current_ids = {chunk.chunk_id for chunk in staged}
        retired = [app.chunk_id_to_int(chunk.chunk_id) for chunk in old_chunks if chunk.chunk_id not in current_ids]
        if retired:
            await asyncio.to_thread(app.get_qdrant_client().delete, collection_name=app.QDRANT_COLLECTION, points_selector=PointIdsList(points=retired))
    return {"success": True, "data": {"documents": len(documents), "chunks": len(staged), "chunk_size": 400}}
