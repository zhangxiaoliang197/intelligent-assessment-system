from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid
import json
import os
import urllib.request
import urllib.error
import ssl

app = FastAPI(
    title="智能问答服务",
    description="基于大模型的智能问答系统",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "llm_config.json")

def load_llm_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "type": "deepseek",
        "apiUrl": "https://api.deepseek.com/v1",
        "apiKey": "",
        "model": "deepseek-chat",
        "temperature": 0.7,
        "maxTokens": 2000,
        "topP": 0.9
    }

def save_llm_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:10252")

def search_knowledge(query, top_k=5):
    try:
        body = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
        req = urllib.request.Request(
            f"{KNOWLEDGE_SERVICE_URL}/knowledge/search",
            data=body, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("results", [])
    except Exception:
        return []

def call_llm_api(query, context=""):
    config = load_llm_config()
    api_key = config.get("apiKey", "")
    api_url = config.get("apiUrl", "https://api.deepseek.com/v1").rstrip("/")
    model = config.get("model", "deepseek-chat")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("maxTokens", 2000)

    if not api_key:
        return "大模型 API Key 未配置，请在「基础管理 → 大模型配置」中设置。", [], []

    knowledge_chunks = search_knowledge(query, top_k=5)
    knowledge_context = ""
    references = []
    sources = []

    if knowledge_chunks:
        for i, ch in enumerate(knowledge_chunks):
            knowledge_context += f"\n\n[参考资料{i + 1} - {ch.get('title', '未知')}]\n{ch.get('content', '')}"
            references.append(f"{ch.get('title', '未知')} (相关度: {ch.get('score', 0):.0%})")
            sources.append({
                "title": ch.get("title", "未知"),
                "category": ch.get("category", "未分类"),
                "score": ch.get("score", 0)
            })

    system_prompt = "你是一个专业的智能评估系统助手，擅长作战效能评估、指标体系分析、方案评估等领域。请用中文回答，回答要专业、准确、有条理。"

    if knowledge_context:
        system_prompt += f"\n\n以下是知识库中检索到的相关参考资料，请优先基于这些资料回答问题：{knowledge_context}"

    ctx = ""
    if context:
        ctx = f"\n\n历史对话上下文:\n{context}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query + ctx}
    ]

    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }).encode("utf-8")

    url = f"{api_url}/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    ssl_ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=120, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data["choices"][0]["message"]["content"]
            return answer, references, sources
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            err = json.loads(err_body)
            msg = err.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        return f"大模型调用失败 (HTTP {e.code}): {msg[:500]}", [], []
    except Exception as e:
        return f"大模型调用失败: {str(e)[:500]}", [], []

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

class LlmConfigRequest(BaseModel):
    type: str = "deepseek"
    apiUrl: str = "https://api.deepseek.com/v1"
    apiKey: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.7
    maxTokens: int = 2000
    topP: float = 0.9

sessions = {}
chat_history = []

@app.get("/")
async def root():
    return {"service": "qa-service", "version": "1.0.0", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/qa/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    context = ""
    for msg in sessions[session_id][-5:]:
        if msg.get("role") == "user":
            context += f"用户: {msg.get('content', '')}\n"
        elif msg.get("role") == "assistant":
            context += f"助手: {msg.get('content', '')}\n"

    answer, references, sources = call_llm_api(request.query, context)

    sessions[session_id].append({"role": "user", "content": request.query})
    sessions[session_id].append({"role": "assistant", "content": answer})

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
                "role": msg["role"],
                "content": msg["content"],
                "references": []
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

@app.get("/config/llm")
async def get_llm_config():
    config = load_llm_config()
    return {
        "success": True,
        "data": config
    }

@app.post("/config/llm")
async def save_llm_config_endpoint(config: LlmConfigRequest):
    save_llm_config(config.dict())
    return {
        "success": True,
        "message": "大模型配置保存成功"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10253)
