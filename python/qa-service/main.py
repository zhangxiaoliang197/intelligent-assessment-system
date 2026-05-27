from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid

app = FastAPI(
    title="智能问答服务",
    description="基于RAG的智能问答系统",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatMessage(BaseModel):
    role: str
    content: str
    references: Optional[List[str]] = []

class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    top_k: int = 5

class ChatResponse(BaseModel):
    answer: str
    references: List[str]
    session_id: str
    sources: List[dict]

class HistoryItem(BaseModel):
    id: str
    query: str
    answer: str
    timestamp: datetime

sessions = {}
chat_history = []

@app.get("/")
async def root():
    return {
        "service": "qa-service",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/qa/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    context = "\n".join([msg.content for msg in sessions[session_id][-5:]])

    answer = f"""基于RAG知识库检索，关于"{request.query}"的分析结果如下：

1. **指标定义**
   该指标用于评估作战效能的关键参数。

2. **计算方法**
   公式：X = (A + B) / C × 100%
   其中A、B、C为各项子指标。

3. **评估标准**
   - 优秀: ≥90分
   - 良好: ≥80分
   - 合格: ≥70分

4. **应用场景**
   适用于各类作战任务的效能评估。

详细内容请参考相关文献和标准。"""

    references = [
        "文献1: 《作战效能评估标准》2025版",
        "文献2: 《指标体系构建方法论》",
        "文献3: 《评估模型应用指南》"
    ]

    sources = [
        {"title": "作战效能评估标准.pdf", "type": "knowledge", "relevance": 0.95},
        {"title": "指标体系构建.docx", "type": "ontology", "relevance": 0.88}
    ]

    sessions[session_id].append(ChatMessage(role="user", content=request.query))
    sessions[session_id].append(ChatMessage(role="assistant", content=answer, references=references))

    chat_history.append(HistoryItem(
        id=str(uuid.uuid4()),
        query=request.query,
        answer=answer,
        timestamp=datetime.now()
    ))

    return ChatResponse(
        answer=answer,
        references=references,
        session_id=session_id,
        sources=sources
    )

@app.get("/qa/history")
async def get_history(session_id: str):
    if session_id not in sessions:
        return {"messages": []}

    return {
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "references": msg.references or []
            }
            for msg in sessions[session_id]
        ]
    }

@app.get("/qa/history/list")
async def list_history():
    return {
        "items": [
            {
                "id": item.id,
                "query": item.query,
                "timestamp": item.timestamp.isoformat()
            }
            for item in chat_history[-20:]
        ]
    }

@app.delete("/qa/history/{session_id}")
async def clear_history(session_id: str):
    if session_id in sessions:
        sessions[session_id] = []
        return {"message": "历史记录已清空"}

    raise HTTPException(status_code=404, detail="会话不存在")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
