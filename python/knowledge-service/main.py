from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import os
import shutil
import uuid
import json
import re

app = FastAPI(
    title="知识库服务 - RAG",
    description="文档上传、解析、分片、检索",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
KNOWLEDGE_FILE = os.path.join(DATA_DIR, 'knowledge.json')
os.makedirs(DATA_DIR, exist_ok=True)

# ---------- Chunk 数据模型 ----------
class Chunk:
    def __init__(self, chunk_id, doc_id, text, title, category, tags, source_file):
        self.chunk_id = chunk_id
        self.doc_id = doc_id
        self.text = text
        self.title = title
        self.category = category
        self.tags = tags
        self.source_file = source_file

# ---------- 内存存储 ----------
def load_db():
    if os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            kdb = data.get('knowledge_db', [])
            cdb = [Chunk(**c) for c in data.get('chunks_db', [])]
            cats = data.get('categories_db', {})
            tags = data.get('tags_db', {})
            return kdb, cdb, cats, tags
    return [], [], {}, {}

def save_db():
    with open(KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'knowledge_db': knowledge_db,
            'chunks_db': [vars(c) for c in chunks_db],
            'categories_db': categories_db,
            'tags_db': tags_db
        }, f, ensure_ascii=False, indent=2, default=str)

knowledge_db, chunks_db, categories_db, tags_db = load_db()
DELIMITER = r'[。！？\n;；!?]'

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    if len(text) <= chunk_size:
        return [text]

    sentences = re.split(f'({DELIMITER})', text)
    merged = []
    buf = ""
    for s in sentences:
        buf += s
        if re.search(DELIMITER, s) and len(buf) >= chunk_size // 2:
            merged.append(buf.strip())
            buf = ""
    if buf.strip():
        merged.append(buf.strip())

    if not merged:
        merged = [text]

    chunks = []
    for seg in merged:
        if len(seg) <= chunk_size:
            chunks.append(seg)
        else:
            start = 0
            while start < len(seg):
                end = start + chunk_size
                chunks.append(seg[start:end])
                start = end - overlap
                if start >= len(seg):
                    break

    return [c for c in chunks if len(c) >= 20]

def read_txt(file_path: str) -> str:
    encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ""

def read_pdf(file_path: str) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        texts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texts.append(t)
        return "\n".join(texts)
    except Exception as e:
        return f"[PDF解析失败] {str(e)}"

def read_docx(file_path: str) -> str:
    try:
        from docx import Document
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        tables_text = []
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text for cell in row.cells if cell.text.strip()]
                if cells:
                    tables_text.append(" | ".join(cells))
        return "\n".join(paragraphs + tables_text)
    except Exception as e:
        return f"[DOCX解析失败] {str(e)}"

def extract_text(file_path: str, filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext == 'txt' or ext == 'md' or ext == 'csv':
        return read_txt(file_path)
    elif ext == 'pdf':
        return read_pdf(file_path)
    elif ext in ('docx', 'doc'):
        return read_docx(file_path)
    else:
        return read_txt(file_path)

def build_index():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    if not chunks_db:
        return None, None, None

    texts = [c.text for c in chunks_db]
    vectorizer = TfidfVectorizer(max_features=5000, analyzer='char_wb', ngram_range=(2, 4))
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return None, None, None

    return vectorizer, matrix, texts

# ---------- Pydantic Models ----------
class KnowledgeDocument(BaseModel):
    id: str
    title: str
    filename: str
    file_path: str
    file_size: int
    file_type: str
    category: str
    tags: List[str]
    status: str
    upload_time: datetime
    content_length: int = 0
    chunk_count: int = 0

class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    category: Optional[str] = None

def get_file_type(filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower()
    return {
        'pdf': 'PDF文档', 'doc': 'Word文档', 'docx': 'Word文档',
        'xls': 'Excel表格', 'xlsx': 'Excel表格',
        'txt': '文本文件', 'md': 'Markdown文档', 'csv': 'CSV数据'
    }.get(ext, '未知类型')

# ---------- API ----------
@app.get("/")
async def root():
    return {"service": "知识库服务", "version": "1.0.0", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "knowledge-service"}

@app.post("/knowledge/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    category: str = Form("未分类"),
    tags: str = Form("")
):
    try:
        file_id = f"kb_{uuid.uuid4().hex[:8]}"
        safe_name = f"{file_id}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = os.path.getsize(file_path)
        tag_list = [t.strip() for t in tags.split(',') if t.strip()]

        raw_text = extract_text(file_path, file.filename)
        text_chunks = chunk_text(raw_text)

        if not text_chunks:
            text_chunks = ["[无法解析文档内容]"]

        doc_chunks = []
        for i, ctext in enumerate(text_chunks):
            ch = Chunk(
                chunk_id=f"{file_id}_c{i}",
                doc_id=file_id,
                text=ctext,
                title=file.filename.rsplit('.', 1)[0],
                category=category,
                tags=tag_list,
                source_file=file.filename
            )
            chunks_db.append(ch)
            doc_chunks.append(ch)

        item = {
            "id": file_id,
            "title": file.filename.rsplit('.', 1)[0],
            "filename": file.filename,
            "file_path": file_path,
            "file_size": file_size,
            "file_type": get_file_type(file.filename),
            "category": category,
            "tags": tag_list,
            "status": "已完成",
            "upload_time": datetime.now().isoformat(),
            "content_length": len(raw_text),
            "chunk_count": len(text_chunks)
        }
        knowledge_db.append(item)

        if category not in categories_db:
            categories_db[category] = []
        categories_db[category].append(file_id)

        for tag in tag_list:
            if tag not in tags_db:
                tags_db[tag] = []
            tags_db[tag].append(file_id)

        save_db()
        return {
            "success": True,
            "message": f"上传并解析完成 ({len(text_chunks)} 个分片)",
            "data": {
                "id": item["id"],
                "title": item["title"],
                "filename": item["filename"],
                "file_size": item["file_size"],
                "file_type": item["file_type"],
                "category": item["category"],
                "status": item["status"],
                "content_length": item["content_length"],
                "chunk_count": item["chunk_count"]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/knowledge/batch-upload")
async def batch_upload_knowledge(
    files: List[UploadFile] = File(...),
    category: str = Form("未分类")
):
    results = []
    for f in files:
        try:
            result = await upload_knowledge(file=f, category=category, tags="")
            results.append(result)
        except Exception as e:
            results.append({"success": False, "filename": f.filename, "error": str(e)})
    return {"success": True, "total": len(files), "results": results}

@app.post("/knowledge/parse/{knowledge_id}")
async def parse_knowledge(knowledge_id: str):
    for item in knowledge_db:
        if item["id"] == knowledge_id:
            if item["status"] == "已完成":
                return {"success": True, "message": "文档已解析", "data": {"id": knowledge_id, "status": "已完成"}}

            raw_text = extract_text(item["file_path"], item["filename"])
            text_chunks = chunk_text(raw_text)

            chunks_db[:] = [c for c in chunks_db if c.doc_id != knowledge_id]

            for i, ctext in enumerate(text_chunks):
                ch = Chunk(
                    chunk_id=f"{knowledge_id}_c{i}", doc_id=knowledge_id,
                    text=ctext, title=item["title"], category=item["category"],
                    tags=item["tags"], source_file=item["filename"]
                )
                chunks_db.append(ch)

            item["status"] = "已完成"
            item["content_length"] = len(raw_text)
            item["chunk_count"] = len(text_chunks)
            save_db()
            return {"success": True, "message": f"解析完成 ({len(text_chunks)} 个分片)", "data": {"id": knowledge_id, "status": "已完成"}}
    raise HTTPException(status_code=404, detail="文档不存在")

@app.post("/knowledge/parse/all")
async def parse_all_knowledge():
    count = 0
    for item in knowledge_db:
        if item["status"] != "已完成":
            raw_text = extract_text(item["file_path"], item["filename"])
            text_chunks = chunk_text(raw_text)

            chunks_db[:] = [c for c in chunks_db if c.doc_id != item["id"]]

            for i, ctext in enumerate(text_chunks):
                ch = Chunk(
                    chunk_id=f'{item["id"]}_c{i}', doc_id=item["id"],
                    text=ctext, title=item["title"], category=item["category"],
                    tags=item["tags"], source_file=item["filename"]
                )
                chunks_db.append(ch)

            item["status"] = "已完成"
            item["content_length"] = len(raw_text)
            item["chunk_count"] = len(text_chunks)
            count += 1

    save_db()
    return {"success": True, "message": f"批量解析完成，共处理 {count} 个文档"}

@app.post("/knowledge/search")
async def search_knowledge(request: KnowledgeSearchRequest):
    if not chunks_db:
        return {"success": True, "query": request.query, "total": 0, "results": []}

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    filtered_chunks = chunks_db
    if request.category:
        filtered_chunks = [c for c in chunks_db if c.category == request.category]

    if not filtered_chunks:
        return {"success": True, "query": request.query, "total": 0, "results": []}

    texts = [c.text for c in filtered_chunks]
    try:
        vectorizer = TfidfVectorizer(max_features=10000, analyzer='char_wb', ngram_range=(2, 4))
        matrix = vectorizer.fit_transform(texts)
        query_vec = vectorizer.transform([request.query])
        similarities = cosine_similarity(query_vec, matrix)[0]
    except Exception:
        query_lower = request.query.lower()
        similarities = []
        for c in filtered_chunks:
            score = 0.0
            if query_lower in c.text.lower():
                score = 0.8
            elif any(qw in c.text.lower() for qw in query_lower.split()):
                score = 0.6
            similarities.append(score)

    top_indices = sorted(range(len(similarities)), key=lambda i: similarities[i], reverse=True)
    top_k = min(request.top_k, len(top_indices))

    results = []
    seen_docs = set()
    for idx in top_indices:
        if similarities[idx] < 0.05:
            break
        chunk = filtered_chunks[idx]
        if chunk.doc_id not in seen_docs:
            seen_docs.add(chunk.doc_id)
        results.append({
            "id": chunk.doc_id,
            "chunk_id": chunk.chunk_id,
            "title": chunk.title,
            "content": chunk.text,
            "score": float(similarities[idx]),
            "category": chunk.category,
            "tags": chunk.tags
        })
        if len(results) >= top_k:
            break

    return {"success": True, "query": request.query, "total": len(results), "results": results}

@app.get("/knowledge/list")
async def list_knowledge(
    category: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    filtered = [k for k in knowledge_db]
    if category:
        filtered = [k for k in filtered if k["category"] == category]
    if status:
        filtered = [k for k in filtered if k["status"] == status]
    filtered.sort(key=lambda k: k.get("upload_time", ""), reverse=True)
    total = len(filtered)
    start = (page - 1) * page_size
    items = filtered[start:start + page_size]
    return {"success": True, "total": total, "page": page, "page_size": page_size, "items": items}

@app.get("/knowledge/stats")
async def get_stats():
    total_size = sum(k.get("file_size", 0) for k in knowledge_db)
    return {
        "success": True,
        "data": {
            "total_documents": len(knowledge_db),
            "total_size": total_size,
            "total_size_formatted": f"{total_size / (1024*1024):.2f} MB",
            "total_chunks": len(chunks_db),
            "categories": len(categories_db),
            "tags": len(tags_db),
            "parsed_documents": len([k for k in knowledge_db if k["status"] == "已完成"]),
            "pending_documents": len([k for k in knowledge_db if k["status"] != "已完成"]),
            "recent_uploads": len([k for k in knowledge_db if (datetime.now() - datetime.fromisoformat(k["upload_time"])).days < 7])
        }
    }

@app.get("/knowledge/categories")
async def get_categories():
    return {"success": True, "total": len(categories_db), "categories": [{"name": n, "count": len(ds), "documents": ds} for n, ds in categories_db.items()]}

@app.post("/knowledge/category")
async def create_category(name: str = Form(...)):
    if name in categories_db:
        raise HTTPException(status_code=400, detail="分类已存在")
    categories_db[name] = []
    save_db()
    return {"success": True, "message": f"分类 '{name}' 创建成功"}

@app.delete("/knowledge/category/{category_name}")
async def delete_category(category_name: str):
    if category_name not in categories_db:
        raise HTTPException(status_code=404, detail="分类不存在")
    for item in knowledge_db:
        if item["category"] == category_name:
            item["category"] = "未分类"
            if "未分类" not in categories_db:
                categories_db["未分类"] = []
            categories_db["未分类"].append(item["id"])
    del categories_db[category_name]
    save_db()
    return {"success": True, "message": f"分类 '{category_name}' 删除成功"}

@app.get("/knowledge/tags")
async def get_tags():
    return {"success": True, "total": len(tags_db), "tags": [{"name": n, "count": len(ds), "documents": ds} for n, ds in tags_db.items()]}

@app.get("/knowledge/{knowledge_id}")
async def get_knowledge(knowledge_id: str):
    for item in knowledge_db:
        if item["id"] == knowledge_id:
            return {"success": True, "data": item}
    raise HTTPException(status_code=404, detail="文档不存在")

@app.put("/knowledge/{knowledge_id}")
async def update_knowledge(knowledge_id: str, category: str = Form(...), tags: str = Form("")):
    for item in knowledge_db:
        if item["id"] == knowledge_id:
            old_cat = item["category"]
            item["category"] = category
            item["tags"] = [t.strip() for t in tags.split(',') if t.strip()]
            if old_cat != category:
                if old_cat in categories_db:
                    categories_db[old_cat].remove(knowledge_id)
                if category not in categories_db:
                    categories_db[category] = []
                categories_db[category].append(knowledge_id)
            for ch in chunks_db:
                if ch.doc_id == knowledge_id:
                    ch.category = category
                    ch.tags = item["tags"]
            save_db()
            return {"success": True, "message": "更新成功"}
    raise HTTPException(status_code=404, detail="文档不存在")

@app.delete("/knowledge/{knowledge_id}")
async def delete_knowledge(knowledge_id: str):
    global chunks_db
    for i, item in enumerate(knowledge_db):
        if item["id"] == knowledge_id:
            path = item.get("file_path", "")
            if path and os.path.exists(path):
                os.remove(path)
            cat = item.get("category", "")
            if cat in categories_db and knowledge_id in categories_db[cat]:
                categories_db[cat].remove(knowledge_id)
            for t in item.get("tags", []):
                if t in tags_db and knowledge_id in tags_db[t]:
                    tags_db[t].remove(knowledge_id)
            knowledge_db.pop(i)
            chunks_db = [c for c in chunks_db if c.doc_id != knowledge_id]
            save_db()
            return {"success": True, "message": "删除成功"}
    raise HTTPException(status_code=404, detail="文档不存在")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10252)
