from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import os
import shutil
import uuid
import json

app = FastAPI(
    title="知识库服务",
    description="管理知识的上传、解析、检索和管理",
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
    parse_time: Optional[datetime]
    content: str
    vector_ids: List[str]

class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    category: Optional[str] = None

class KnowledgeSearchResult(BaseModel):
    id: str
    title: str
    content: str
    score: float
    category: str
    tags: List[str]

class KnowledgeStats(BaseModel):
    total_documents: int
    total_size: int
    categories: int
    tags: int
    parsed_documents: int
    pending_documents: int
    recent_uploads: int

class CategoryInfo(BaseModel):
    name: str
    count: int
    documents: List[str]

knowledge_db: List[KnowledgeDocument] = []
categories_db: dict = {}
tags_db: dict = {}

def get_file_type(filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower()
    type_map = {
        'pdf': 'PDF文档',
        'doc': 'Word文档',
        'docx': 'Word文档',
        'xls': 'Excel表格',
        'xlsx': 'Excel表格',
        'txt': '文本文件',
        'md': 'Markdown文档',
        'csv': 'CSV数据'
    }
    return type_map.get(ext, '未知类型')

@app.get("/")
async def root():
    return {
        "service": "知识库服务",
        "version": "1.0.0",
        "status": "running"
    }

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
        file_path = os.path.join(UPLOAD_DIR, f"{file_id}_{file.filename}")

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = os.path.getsize(file_path)

        tag_list = [t.strip() for t in tags.split(',') if t.strip()]

        knowledge_item = KnowledgeDocument(
            id=file_id,
            title=file.filename.rsplit('.', 1)[0],
            filename=file.filename,
            file_path=file_path,
            file_size=file_size,
            file_type=get_file_type(file.filename),
            category=category,
            tags=tag_list,
            status="待解析",
            upload_time=datetime.now(),
            parse_time=None,
            content="",
            vector_ids=[]
        )
        knowledge_db.append(knowledge_item)

        if category not in categories_db:
            categories_db[category] = []
        categories_db[category].append(file_id)

        for tag in tag_list:
            if tag not in tags_db:
                tags_db[tag] = []
            tags_db[tag].append(file_id)

        return {
            "success": True,
            "message": "文件上传成功",
            "data": {
                "id": knowledge_item.id,
                "title": knowledge_item.title,
                "filename": knowledge_item.filename,
                "file_size": knowledge_item.file_size,
                "file_type": knowledge_item.file_type,
                "category": knowledge_item.category,
                "status": knowledge_item.status
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
    for file in files:
        try:
            result = await upload_knowledge(file=file, category=category, tags="")
            results.append(result)
        except Exception as e:
            results.append({
                "success": False,
                "filename": file.filename,
                "error": str(e)
            })

    return {
        "success": True,
        "total": len(files),
        "results": results
    }

@app.post("/knowledge/parse/{knowledge_id}")
async def parse_knowledge(knowledge_id: str):
    for item in knowledge_db:
        if item.id == knowledge_id:
            item.status = "解析中"
            item.content = f"这是知识文档的内容摘要：{item.title}..."
            item.parse_time = datetime.now()
            item.status = "已完成"
            item.vector_ids = [f"vec_{uuid.uuid4().hex[:8]}"]

            return {
                "success": True,
                "message": "文档解析完成",
                "data": {
                    "id": item.id,
                    "status": item.status,
                    "parse_time": item.parse_time.isoformat(),
                    "content_preview": item.content[:200]
                }
            }

    raise HTTPException(status_code=404, detail="知识文档不存在")

@app.post("/knowledge/parse/all")
async def parse_all_knowledge():
    count = 0
    for item in knowledge_db:
        if item.status in ["待解析", "解析失败"]:
            item.status = "解析中"
            item.content = f"这是知识文档的内容摘要：{item.title}..."
            item.parse_time = datetime.now()
            item.status = "已完成"
            item.vector_ids = [f"vec_{uuid.uuid4().hex[:8]}"]
            count += 1

    return {
        "success": True,
        "message": f"批量解析完成，共处理 {count} 个文档"
    }

@app.post("/knowledge/search")
async def search_knowledge(request: KnowledgeSearchRequest):
    results = []
    for item in knowledge_db:
        if item.status != "已完成":
            continue
        if request.category and item.category != request.category:
            continue

        score = 0.0
        query_lower = request.query.lower()
        if query_lower in item.title.lower():
            score = 0.95
        elif query_lower in item.content.lower():
            score = 0.85
        elif any(query_lower in tag.lower() for tag in item.tags):
            score = 0.75

        if score > 0:
            results.append(KnowledgeSearchResult(
                id=item.id,
                title=item.title,
                content=item.content[:200],
                score=score,
                category=item.category,
                tags=item.tags
            ))

    results.sort(key=lambda x: x.score, reverse=True)
    return {
        "success": True,
        "query": request.query,
        "total": len(results),
        "results": [r.dict() for r in results[:request.top_k]]
    }

@app.get("/knowledge/list")
async def list_knowledge(
    category: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    filtered = knowledge_db

    if category:
        filtered = [k for k in filtered if k.category == category]
    if status:
        filtered = [k for k in filtered if k.status == status]

    filtered.sort(key=lambda x: x.upload_time, reverse=True)

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": k.id,
                "title": k.title,
                "filename": k.filename,
                "file_size": k.file_size,
                "file_type": k.file_type,
                "category": k.category,
                "tags": k.tags,
                "status": k.status,
                "upload_time": k.upload_time.isoformat(),
                "parse_time": k.parse_time.isoformat() if k.parse_time else None
            }
            for k in items
        ]
    }

@app.get("/knowledge/{knowledge_id}")
async def get_knowledge(knowledge_id: str):
    for item in knowledge_db:
        if item.id == knowledge_id:
            return {
                "success": True,
                "data": item.dict()
            }

    raise HTTPException(status_code=404, detail="知识文档不存在")

@app.put("/knowledge/{knowledge_id}")
async def update_knowledge(knowledge_id: str, category: str = Form(...), tags: str = Form("")):
    for item in knowledge_db:
        if item.id == knowledge_id:
            old_category = item.category
            item.category = category
            item.tags = [t.strip() for t in tags.split(',') if t.strip()]

            if old_category != category:
                if old_category in categories_db:
                    categories_db[old_category].remove(knowledge_id)
                if category not in categories_db:
                    categories_db[category] = []
                categories_db[category].append(knowledge_id)

            return {
                "success": True,
                "message": "知识文档更新成功"
            }

    raise HTTPException(status_code=404, detail="知识文档不存在")

@app.delete("/knowledge/{knowledge_id}")
async def delete_knowledge(knowledge_id: str):
    for i, item in enumerate(knowledge_db):
        if item.id == knowledge_id:
            if os.path.exists(item.file_path):
                os.remove(item.file_path)

            if item.category in categories_db:
                categories_db[item.category].remove(knowledge_id)

            for tag in item.tags:
                if tag in tags_db:
                    tags_db[tag].remove(knowledge_id)

            knowledge_db.pop(i)

            return {
                "success": True,
                "message": "知识文档删除成功"
            }

    raise HTTPException(status_code=404, detail="知识文档不存在")

@app.get("/knowledge/stats")
async def get_stats():
    total_documents = len(knowledge_db)
    total_size = sum(k.file_size for k in knowledge_db)
    categories = len(categories_db)
    tags = len(tags_db)
    parsed_documents = len([k for k in knowledge_db if k.status == "已完成"])
    pending_documents = len([k for k in knowledge_db if k.status in ["待解析", "解析中"]])
    recent_uploads = len([k for k in knowledge_db if (datetime.now() - k.upload_time).days < 7])

    return {
        "success": True,
        "data": {
            "total_documents": total_documents,
            "total_size": total_size,
            "total_size_formatted": f"{total_size / (1024*1024):.2f} MB",
            "categories": categories,
            "tags": tags,
            "parsed_documents": parsed_documents,
            "pending_documents": pending_documents,
            "recent_uploads": recent_uploads
        }
    }

@app.get("/knowledge/categories")
async def get_categories():
    categories = []
    for name, doc_ids in categories_db.items():
        categories.append({
            "name": name,
            "count": len(doc_ids),
            "documents": doc_ids
        })

    return {
        "success": True,
        "total": len(categories),
        "categories": categories
    }

@app.post("/knowledge/category")
async def create_category(name: str = Form(...)):
    if name in categories_db:
        raise HTTPException(status_code=400, detail="分类已存在")

    categories_db[name] = []

    return {
        "success": True,
        "message": f"分类 '{name}' 创建成功"
    }

@app.delete("/knowledge/category/{category_name}")
async def delete_category(category_name: str):
    if category_name not in categories_db:
        raise HTTPException(status_code=404, detail="分类不存在")

    for item in knowledge_db:
        if item.category == category_name:
            item.category = "未分类"
            categories_db["未分类"].append(item.id)

    del categories_db[category_name]

    return {
        "success": True,
        "message": f"分类 '{category_name}' 删除成功"
    }

@app.get("/knowledge/tags")
async def get_tags():
    tags = []
    for name, doc_ids in tags_db.items():
        tags.append({
            "name": name,
            "count": len(doc_ids),
            "documents": doc_ids
        })

    return {
        "success": True,
        "total": len(tags),
        "tags": tags
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
