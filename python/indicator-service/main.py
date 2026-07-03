from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import os
import tempfile
import urllib.request
import urllib.error
import ssl
import re
import uuid
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indicator-service")

app = FastAPI(
    title="指标分析服务",
    description="智能分析评估指标体系",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

QA_SERVICE_URL = os.getenv("QA_SERVICE_URL", "http://localhost:10253")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
os.makedirs(DATA_DIR, exist_ok=True)

# 滑动窗口大小
MAX_CONTEXT = int(os.getenv("INDICATOR_CONTEXT_ROUNDS", "5"))


def atomic_json_write(filepath, data):
    dirpath = os.path.dirname(filepath)
    fd, tmp_path = tempfile.mkstemp(dir=dirpath, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        bak_path = filepath + '.bak'
        if os.path.exists(filepath):
            try:
                import shutil
                shutil.copy2(filepath, bak_path)
            except Exception:
                pass
        if os.name == 'nt' and os.path.exists(filepath):
            os.remove(filepath)
        os.rename(tmp_path, filepath)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


class AnalyzeRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    depth: int = 3


# ========== 会话管理 ==========

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load sessions: {e}")
            bak = SESSIONS_FILE + '.bak'
            if os.path.exists(bak):
                try:
                    with open(bak, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    pass
    return {}


def save_sessions():
    atomic_json_write(SESSIONS_FILE, sessions)
    logger.info("Indicator sessions saved")


sessions = load_sessions()
logger.info(f"Indicator service started: {len(sessions)} sessions, context rounds={MAX_CONTEXT}")


# ========== LLM 调用 ==========

def call_llm_for_indicator_analysis(query: str, context: str = "") -> dict:
    try:
        ctx = ""
        if context:
            ctx = f"\n\n历史对话上下文:\n{context}"

        prompt = f"""请分析以下指标需求，并返回结构化的JSON数据：

需求：{query}{ctx}

请按照以下JSON格式返回分析结果（必须是可以被json.loads解析的JSON格式）：
{{
    "tree": {{
        "name": "根节点名称，如：作战效能指标体系",
        "source": "knowledge 或 llm",
        "children": [
            {{
                "name": "一级指标名称",
                "source": "knowledge 或 llm",
                "children": [
                    {{"name": "二级指标名称", "source": "knowledge 或 llm"}}
                ]
            }}
        ]
    }},
    "indicators": [
        {{
            "name": "指标名称",
            "type": "knowledge 或 llm",
            "definition": "指标定义",
            "formula": "计算公式",
            "criteria": "评估标准",
            "weight": "权重值"
        }}
    ],
    "summary": "分析总结说明"
}}

要求：
1. tree.children最多3层结构
2. indicators至少包含5个指标
3. 每个指标必须包含name, definition, formula
4. 只返回JSON数据，不要其他说明文字
"""

        body = json.dumps({
            "query": prompt,
            "top_k": 10
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{QA_SERVICE_URL}/qa/chat",
            data=body,
            method="POST"
        )
        req.add_header("Content-Type", "application/json")

        ctx_ssl = ssl.create_default_context()
        ctx_ssl.check_hostname = False
        ctx_ssl.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(req, timeout=120, context=ctx_ssl) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data.get("answer", "")

            result = parse_structured_response(answer)

            return result
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {
            "answer": f"调用大模型分析失败: {str(e)}",
            "tree": get_default_tree(),
            "indicators": get_default_indicators(),
            "references": [],
            "summary": ""
        }


def parse_structured_response(answer: str) -> dict:
    try:
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', answer)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'\{[\s\S]*\}', answer)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = answer

        json_str = json_str.strip()
        data = json.loads(json_str)

        if "tree" not in data:
            data["tree"] = get_default_tree()
        if "indicators" not in data:
            data["indicators"] = get_default_indicators()
        if "summary" not in data:
            data["summary"] = ""

        result = {
            "answer": answer,
            "tree": data.get("tree", get_default_tree()),
            "indicators": data.get("indicators", get_default_indicators()),
            "summary": data.get("summary", ""),
            "references": []
        }

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed: {e}")
        return {
            "answer": answer,
            "tree": get_default_tree(),
            "indicators": get_default_indicators(),
            "summary": "",
            "references": []
        }


def get_default_tree() -> Dict:
    return {
        "name": "作战效能指标体系",
        "source": "knowledge",
        "children": [
            {
                "name": "打击能力",
                "source": "knowledge",
                "children": [
                    {"name": "命中率", "source": "knowledge"},
                    {"name": "摧毁率", "source": "knowledge"},
                    {"name": "突防率", "source": "llm"}
                ]
            },
            {
                "name": "生存能力",
                "source": "knowledge",
                "children": [
                    {"name": "存活率", "source": "knowledge"},
                    {"name": "防护能力", "source": "llm"}
                ]
            },
            {
                "name": "保障能力",
                "source": "knowledge",
                "children": [
                    {"name": "补给效率", "source": "knowledge"},
                    {"name": "维护能力", "source": "llm"}
                ]
            }
        ]
    }


def get_default_indicators() -> List[Dict]:
    return [
        {
            "name": "命中率",
            "type": "knowledge",
            "definition": "武器系统命中目标的概率，反映精确打击能力。",
            "formula": "命中率 = 命中次数 / 射击次数 × 100%",
            "criteria": "优秀: ≥85%, 良好: ≥75%, 合格: ≥65%",
            "weight": "0.35"
        },
        {
            "name": "摧毁率",
            "type": "knowledge",
            "definition": "被命中目标中被摧毁的比例，反映毁伤效果。",
            "formula": "摧毁率 = 摧毁数量 / 命中数量 × 100%",
            "criteria": "优秀: ≥80%, 良好: ≥70%, 合格: ≥60%",
            "weight": "0.30"
        },
        {
            "name": "突防率",
            "type": "llm",
            "definition": "成功突破敌方防御系统的概率，反映突防能力。",
            "formula": "突防率 = 成功突防次数 / 总突防次数 × 100%",
            "criteria": "根据具体作战场景确定",
            "weight": "0.25"
        },
        {
            "name": "存活率",
            "type": "knowledge",
            "definition": "作战单元在作战环境中保持功能的概率，反映生存能力。",
            "formula": "存活率 = 存活数量 / 初始数量 × 100%",
            "criteria": "优秀: ≥90%, 良好: ≥80%, 合格: ≥70%",
            "weight": "0.20"
        },
        {
            "name": "防护能力",
            "type": "llm",
            "definition": "系统抵御外部威胁的能力，包括装甲防护、电子对抗等。",
            "formula": "防护能力评分 = Σ(防护分项得分 × 分项权重)",
            "criteria": "根据防护等级确定",
            "weight": "0.15"
        }
    ]


# ========== API 端点 ==========

@app.get("/")
async def root():
    return {
        "service": "indicator-service",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ========== 会话管理 API ==========

@app.get("/indicator/sessions")
async def list_sessions():
    """返回所有会话列表"""
    session_list = []
    for sid, msgs in sessions.items():
        if not msgs:
            continue
        latest_question = ""
        for msg in reversed(msgs):
            if msg.get("role") == "user":
                q = msg.get("content", "").strip()
                latest_question = q[:30] if len(q) > 30 else q
                break
        last_time = msgs[-1].get("timestamp", datetime.now().isoformat())
        session_list.append({
            "id": sid,
            "title": latest_question or "(空会话)",
            "message_count": len(msgs),
            "last_active": last_time
        })
    session_list.sort(key=lambda x: x.get("last_active", ""), reverse=True)
    return {"success": True, "sessions": session_list}


@app.post("/indicator/session/new")
async def new_session():
    new_id = str(uuid.uuid4())
    sessions[new_id] = []
    save_sessions()
    return {"success": True, "session_id": new_id}


@app.delete("/indicator/session/{session_id}")
async def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        save_sessions()
        return {"success": True}
    raise HTTPException(status_code=404, detail="会话不存在")


# ========== 分析 API ==========

@app.post("/indicator/analyze")
async def analyze_indicator(request: AnalyzeRequest):
    """分析指标请求"""
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    # 滑动窗口上下文
    recent = sessions[session_id][-(MAX_CONTEXT * 2):]
    context = ""
    for msg in recent:
        if msg.get("role") == "user":
            context += f"用户: {msg.get('content', '')}\n"
        elif msg.get("role") == "assistant":
            context += f"助手: {msg.get('content', '')[:200]}\n"

    result = call_llm_for_indicator_analysis(request.query, context)

    now_str = datetime.now().isoformat()
    sessions[session_id].append({"role": "user", "content": request.query, "timestamp": now_str})
    sessions[session_id].append({
        "role": "assistant",
        "content": result.get("summary", result.get("answer", "")[:200]),
        "timestamp": now_str
    })

    if len(sessions[session_id]) > MAX_CONTEXT * 4:
        sessions[session_id] = sessions[session_id][-(MAX_CONTEXT * 4):]

    save_sessions()

    return {
        "success": True,
        "query": request.query,
        "session_id": session_id,
        "answer": result.get("answer", ""),
        "summary": result.get("summary", ""),
        "tree": result.get("tree", get_default_tree()),
        "indicators": result.get("indicators", get_default_indicators()),
        "references": result.get("references", []),
        "message": "指标分析完成"
    }

@app.post("/indicator/analyze/stream")
async def analyze_indicator_stream(request: AnalyzeRequest):
    """流式指标分析"""
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    recent = sessions[session_id][-(MAX_CONTEXT * 2):]
    context = ""
    for msg in recent:
        if msg.get("role") == "user":
            context += f"用户: {msg.get('content', '')}\n"
        elif msg.get("role") == "assistant":
            context += f"助手: {msg.get('content', '')[:200]}\n"

    ctx_str = ""
    if context:
        ctx_str = f"\n\n历史对话上下文:\n{context}"

    prompt = f"""请分析以下指标需求，并返回结构化的JSON数据：

需求：{request.query}{ctx_str}

请按照以下JSON格式返回分析结果（必须是可以被json.loads解析的JSON格式）：
{{
    "tree": {{
        "name": "根节点名称，如：作战效能指标体系",
        "source": "knowledge 或 llm",
        "children": [...]
    }},
    "indicators": [
        {{"name": "指标名称", "type": "knowledge 或 llm", "definition": "定义", "formula": "公式", "criteria": "标准", "weight": "权重"}}
    ],
    "summary": "分析总结说明"
}}

要求：tree.children最多3层，indicators至少5个指标，每个指标须包含name/definition/formula"""

    def generate():
        full_text = ""
        now_str = datetime.now().isoformat()

        try:
            body = json.dumps({"query": prompt, "top_k": 10}).encode("utf-8")
            req = urllib.request.Request(
                f"{QA_SERVICE_URL}/qa/chat/stream",
                data=body, method="POST"
            )
            req.add_header("Content-Type", "application/json")
            ctx_ssl = ssl.create_default_context()
            ctx_ssl.check_hostname = False
            ctx_ssl.verify_mode = ssl.CERT_NONE

            with urllib.request.urlopen(req, timeout=180, context=ctx_ssl) as resp:
                for line in resp:
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("type") == "text":
                            chunk = data.get("content", "")
                            full_text += chunk
                            yield json.dumps({"type": "text", "content": chunk}, ensure_ascii=False) + "\n"
                        elif data.get("type") == "error":
                            yield json.dumps({"type": "text", "content": data.get("content", "")}, ensure_ascii=False) + "\n"
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            yield json.dumps({"type": "text", "content": f"分析失败: {str(e)[:200]}"}, ensure_ascii=False) + "\n"

        # 解析结构化结果
        result = parse_structured_response(full_text)
        tree = result.get("tree", get_default_tree())
        indicators = result.get("indicators", get_default_indicators())
        summary = result.get("summary", result.get("answer", full_text[:200]))

        yield json.dumps({
            "type": "result",
            "session_id": session_id,
            "tree": tree,
            "indicators": indicators,
            "summary": summary
        }, ensure_ascii=False, default=str) + "\n"

        # 保存会话
        sessions[session_id].append({"role": "user", "content": request.query, "timestamp": now_str})
        sessions[session_id].append({"role": "assistant", "content": summary, "timestamp": now_str})
        if len(sessions[session_id]) > MAX_CONTEXT * 4:
            sessions[session_id] = sessions[session_id][-(MAX_CONTEXT * 4):]
        save_sessions()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/indicator/history")
async def get_history(session_id: str):
    """获取指定会话的消息"""
    if session_id not in sessions:
        return {"messages": []}
    return {
        "messages": [
            {"role": msg["role"], "content": msg["content"]}
            for msg in sessions[session_id]
        ]
    }


@app.get("/indicator/tree")
async def get_indicator_tree():
    return get_default_tree()


@app.get("/indicator/detail/{indicator_name}")
async def get_indicator_detail(indicator_name: str):
    indicator_db = {
        "命中率": {
            "name": "命中率",
            "source": "knowledge",
            "definition": "武器系统命中目标的概率，反映精确打击能力。",
            "formula": "命中率 = 命中次数 / 射击次数 × 100%",
            "criteria": "优秀: ≥85%, 良好: ≥75%, 合格: ≥65%",
            "weight": 0.35
        },
        "摧毁率": {
            "name": "摧毁率",
            "source": "knowledge",
            "definition": "被命中目标中被摧毁的比例，反映毁伤效果。",
            "formula": "摧毁率 = 摧毁数量 / 命中数量 × 100%",
            "criteria": "优秀: ≥80%, 良好: ≥70%, 合格: ≥60%",
            "weight": 0.30
        }
    }

    if indicator_name in indicator_db:
        return indicator_db[indicator_name]

    return {
        "name": indicator_name,
        "source": "llm",
        "definition": "该指标由大模型基于知识库扩展生成，需要进一步验证。",
        "formula": "待定",
        "criteria": "待验证",
        "weight": 0.0
    }


@app.get("/indicator/algorithm/{indicator_name}")
async def get_indicator_algorithm(indicator_name: str):
    algorithms = {
        "作战效能": {
            "name": "作战效能综合评估",
            "formula": "作战效能 = Σ(指标值 × 权重) / Σ权重",
            "steps": [
                "1. 确定各级指标及其权重",
                "2. 收集各项指标数据",
                "3. 标准化指标值",
                "4. 加权计算综合得分",
                "5. 对照评估标准确定等级"
            ],
            "example": "打击能力(0.4) + 生存能力(0.3) + 保障能力(0.3)"
        }
    }

    return algorithms.get(indicator_name, {
        "message": "该指标暂无详细算法说明"
    })


@app.get("/indicator/list")
async def list_indicators():
    return {
        "indicators": [
            {"name": "作战效能", "category": "综合指标", "source": "knowledge"},
            {"name": "打击能力", "category": "性能指标", "source": "knowledge"},
            {"name": "生存能力", "category": "性能指标", "source": "knowledge"},
            {"name": "保障能力", "category": "性能指标", "source": "knowledge"}
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10254)
