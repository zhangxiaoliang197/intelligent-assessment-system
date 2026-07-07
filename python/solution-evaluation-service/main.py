from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, AsyncGenerator
import json
import os
import tempfile
import urllib.request
import urllib.error
import ssl
import datetime
import uuid
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("solution-evaluation-service")

from agents.combat_effectiveness_agent import run_stream as run_combat_effectiveness_stream

app = FastAPI(
    title="Solution Evaluation Service",
    description="方案评估系统 - 多Agent协同分析",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据目录
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SKILLS_FILE = os.path.join(DATA_DIR, 'skills.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
os.makedirs(DATA_DIR, exist_ok=True)

# 外部服务地址
QA_SERVICE_URL = os.getenv("QA_SERVICE_URL", "http://localhost:10253")
INDICATOR_SERVICE_URL = os.getenv("INDICATOR_SERVICE_URL", "http://localhost:10254")

# 滑动窗口大小
MAX_CONTEXT = int(os.getenv("SOLUTION_CONTEXT_ROUNDS", "5"))


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


# 数据模型
class EvaluationRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    dataSourceId: Optional[str] = None
    skillId: Optional[str] = None


class Skill(BaseModel):
    id: str
    name: str
    description: str
    type: str
    promptTemplate: str
    createdAt: str
    updatedAt: str


# Skill管理
def load_skills():
    if os.path.exists(SKILLS_FILE):
        with open(SKILLS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return [
        {
            "id": "skill-calculate-indicator",
            "name": "指标计算",
            "description": "根据用户查询自动生成SQL并计算指标结果",
            "type": "indicator",
            "promptTemplate": "分析用户需求，生成指标计算SQL并执行",
            "createdAt": "2024-06-03",
            "updatedAt": "2024-06-03"
        },
        {
            "id": "skill-air-superiority",
            "name": "制空权分析",
            "description": "分析红蓝双方制空权优势对比",
            "type": "analysis",
            "promptTemplate": "调用制空权分析Agent，结合数据源进行对比分析",
            "createdAt": "2024-06-03",
            "updatedAt": "2024-06-03"
        }
    ]


def save_skills(skills):
    with open(SKILLS_FILE, 'w', encoding='utf-8') as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)


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
    logger.info("Solution-evaluation sessions saved")


sessions = load_sessions()
logger.info(f"Solution-evaluation service started: {len(sessions)} sessions, context rounds={MAX_CONTEXT}")


# 历史记录管理
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_history(history):
    atomic_json_write(HISTORY_FILE, history)


# 数据源配置
def get_data_sources():
    return [
        {"id": "ds-mission-data", "name": "任务执行数据", "type": "database", "status": "available"},
        {"id": "ds-battle-data", "name": "战场态势数据", "type": "database", "status": "available"},
        {"id": "ds-weapon-data", "name": "武器装备数据", "type": "database", "status": "available"}
    ]


# 调用其他服务
def call_qa_service(query: str, top_k: int = 5):
    try:
        body = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
        req = urllib.request.Request(f"{QA_SERVICE_URL}/qa/chat", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"answer": f"知识库查询失败: {str(e)}", "references": []}


def call_indicator_service(query: str):
    try:
        body = json.dumps({"query": query}).encode("utf-8")
        req = urllib.request.Request(f"{INDICATOR_SERVICE_URL}/indicator/analyze", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"answer": f"指标分析失败: {str(e)}"}




# 意图识别
def parse_intent(query: str):
    query_lower = query.lower()
    if any(keyword in query_lower for keyword in ['制空权', '制空', '优势对比', '红蓝双方', '空中优势']):
        return {"intent": "air_superiority", "skillId": "skill-air-superiority", "confidence": 0.92, "analysis": "识别到制空权分析需求，正在调用制空权分析Agent"}
    elif any(keyword in query_lower for keyword in ['整体作战', '作战效能', '综合评估', '战损', '战果', '消耗']):
        return {"intent": "combat_effectiveness", "skillId": None, "confidence": 0.90, "analysis": "识别到整体作战效能评估需求，正在调用作战效能智能体"}
    elif any(keyword in query_lower for keyword in ['指标', '计算', '查询结果', '完成率']):
        return {"intent": "calculate_indicator", "skillId": "skill-calculate-indicator", "confidence": 0.88, "analysis": "识别到指标计算需求，正在调用指标计算Agent"}
    else:
        return {"intent": "general_analysis", "skillId": None, "confidence": 0.65, "analysis": "通用分析需求，使用默认分析流程"}


# 流式生成执行步骤
async def stream_execution_steps(
    query: str,
    data_source_id: Optional[str],
    skill_id: Optional[str],
    skills: List[Dict],
    session_id: str
) -> AsyncGenerator[bytes, None]:

    async def send_data(data: dict):
        yield json.dumps(data, ensure_ascii=False).encode('utf-8') + b'\n'

    # 步骤1: 理解用户意图
    intent_result = parse_intent(query)
    yield json.dumps({
        "type": "step",
        "step": {
            "step": 1, "type": "intent_parse", "description": "理解用户意图",
            "status": "completed", "detail": f"正在分析: {query[:30]}...",
            "thinking": intent_result["analysis"]
        }
    }, ensure_ascii=False).encode('utf-8') + b'\n'
    await asyncio.sleep(0.8)

    # 步骤2: 匹配分析技能
    matched_skill = None
    if skill_id:
        matched_skill = next((s for s in skills if s["id"] == skill_id), None)
    elif intent_result.get("skillId"):
        matched_skill = next((s for s in skills if s["id"] == intent_result["skillId"]), None)

    yield json.dumps({
        "type": "step",
        "step": {
            "step": 2, "type": "skill_match", "description": "匹配分析技能",
            "status": "completed",
            "detail": f"已匹配: {matched_skill['name'] if matched_skill else '默认分析'}",
            "skillInfo": matched_skill if matched_skill else None
        }
    }, ensure_ascii=False).encode('utf-8') + b'\n'
    await asyncio.sleep(0.8)

    # 步骤3: 获取数据源
    data_source_name = "默认数据源"
    if data_source_id:
        data_sources = get_data_sources()
        selected_ds = next((ds for ds in data_sources if ds["id"] == data_source_id), None)
        if selected_ds:
            data_source_name = selected_ds['name']

    yield json.dumps({
        "type": "step",
        "step": {
            "step": 3, "type": "data_source", "description": "获取数据源",
            "status": "completed", "detail": f"已连接: {data_source_name}",
            "dataSource": data_source_name
        }
    }, ensure_ascii=False).encode('utf-8') + b'\n'
    await asyncio.sleep(0.8)

    # 步骤4: 执行分析
    yield json.dumps({
        "type": "step",
        "step": {
            "step": 4, "type": "analysis", "description": "执行分析计算",
            "status": "in_progress", "detail": "正在调用分析模型...", "progress": 0
        }
    }, ensure_ascii=False).encode('utf-8') + b'\n'

    analysis_result = None

    if intent_result["intent"] == "air_superiority":
        yield json.dumps({
            "type": "step",
            "step": {
                "step": 4, "type": "analysis", "description": "执行分析计算",
                "status": "in_progress", "detail": "正在分析制空权对比...",
                "progress": 30, "subStep": "air_analysis"
            }
        }, ensure_ascii=False).encode('utf-8') + b'\n'
        await asyncio.sleep(1.0)

        yield json.dumps({
            "type": "step",
            "step": {
                "step": 4, "type": "analysis", "description": "执行分析计算",
                "status": "in_progress", "detail": "正在检索相关知识...",
                "progress": 50, "subStep": "knowledge_retrieval"
            }
        }, ensure_ascii=False).encode('utf-8') + b'\n'
        await asyncio.sleep(1.0)

        qa_result = call_qa_service(query)

        yield json.dumps({
            "type": "step",
            "step": {
                "step": 4, "type": "analysis", "description": "执行分析计算",
                "status": "in_progress", "detail": "正在生成分析报告...",
                "progress": 80, "subStep": "report_generation"
            }
        }, ensure_ascii=False).encode('utf-8') + b'\n'
        await asyncio.sleep(1.0)

        analysis_result = {
            "type": "air_superiority",
            "summary": "根据知识库分析，制空权优势主要取决于以下因素：",
            "factors": ["战斗机数量与质量优势", "预警指挥系统能力", "地面防空体系完善度", "电子战能力", "作战经验与训练水平"],
            "redScore": 82, "blueScore": 71, "advantage": "红方", "advantageMargin": 11,
            "knowledgeReference": qa_result.get("references", []),
            "analysisDetails": {
                "strengthsRed": ["三代半战机数量优势", "预警机覆盖范围更广", "地面防空密度高"],
                "strengthsBlue": ["四代机质量优势", "电子战能力突出", "战术灵活"],
                "recommendations": "建议红方利用数量优势和体系作战能力，蓝方应发挥质量优势和战术灵活性"
            }
        }

    elif intent_result["intent"] == "combat_effectiveness":
        if not data_source_id:
            yield json.dumps({
                "type": "step",
                "step": {"step": 4, "type": "analysis", "description": "执行分析计算",
                         "status": "completed", "detail": "缺少数据源, 请在页面选择数据源后再试", "progress": 100}
            }, ensure_ascii=False).encode('utf-8') + b'\n'
            analysis_result = {"type": "combat_effectiveness", "results": [], "summary": "未选择数据源"}
        else:
            gen = run_combat_effectiveness_stream(data_source_id)
            result_chunks = []
            for chunk in gen:
                line = chunk.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("type") == "result":
                        analysis_result = data.get("result", {})
                    else:
                        result_chunks.append(chunk)
                        yield chunk
                except json.JSONDecodeError:
                    result_chunks.append(chunk)
                    yield chunk
            if analysis_result is None:
                analysis_result = {"type": "combat_effectiveness", "results": [], "summary": "分析完成"}

    elif intent_result["intent"] == "calculate_indicator":
        yield json.dumps({
            "type": "step",
            "step": {
                "step": 4, "type": "analysis", "description": "执行分析计算",
                "status": "in_progress", "detail": "正在生成指标计算SQL...",
                "progress": 30, "subStep": "sql_generation"
            }
        }, ensure_ascii=False).encode('utf-8') + b'\n'
        await asyncio.sleep(1.0)

        sql = """-- 任务完成率指标计算
SELECT 
    region,
    AVG(completion_rate) as avg_completion_rate,
    MAX(success_count) as max_success,
    MIN(failure_count) as min_failure,
    SUM(total_count) as total_missions,
    SUM(success_count) * 100.0 / SUM(total_count) as success_rate
FROM mission_execution
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
GROUP BY region
ORDER BY success_rate DESC"""

        yield json.dumps({
            "type": "step",
            "step": {
                "step": 4, "type": "analysis", "description": "执行分析计算",
                "status": "in_progress", "detail": "正在执行SQL查询...",
                "progress": 50, "subStep": "sql_execution", "generatedSql": sql
            }
        }, ensure_ascii=False).encode('utf-8') + b'\n'
        await asyncio.sleep(1.0)

        yield json.dumps({
            "type": "step",
            "step": {
                "step": 4, "type": "analysis", "description": "执行分析计算",
                "status": "in_progress", "detail": "正在调用指标分析模型...",
                "progress": 70, "subStep": "indicator_analysis"
            }
        }, ensure_ascii=False).encode('utf-8') + b'\n'
        await asyncio.sleep(1.0)

        indicator_result = call_indicator_service(query)

        analysis_result = {
            "type": "indicator_calculation",
            "generatedSql": sql,
            "queryResult": {
                "columns": ["区域", "平均完成率", "最大成功", "总任务数", "成功率"],
                "sampleData": [
                    {"区域": "A区", "平均完成率": "85.2%", "最大成功": 120, "总任务数": 150, "成功率": "80.0%"},
                    {"区域": "B区", "平均完成率": "78.5%", "最大成功": 95, "总任务数": 120, "成功率": "79.2%"},
                    {"区域": "C区", "平均完成率": "92.1%", "最大成功": 85, "总任务数": 95, "成功率": "89.5%"}
                ]
            },
            "indicatorData": indicator_result,
            "statistics": {"totalMissions": 365, "totalSuccess": 298, "overallRate": "81.6%"}
        }

    else:
        yield json.dumps({
            "type": "step",
            "step": {
                "step": 4, "type": "analysis", "description": "执行分析计算",
                "status": "in_progress", "detail": "正在调用知识库...", "progress": 40
            }
        }, ensure_ascii=False).encode('utf-8') + b'\n'
        await asyncio.sleep(1.0)

        qa_result = call_qa_service(query)

        yield json.dumps({
            "type": "step",
            "step": {
                "step": 4, "type": "analysis", "description": "执行分析计算",
                "status": "in_progress", "detail": "正在生成分析报告...", "progress": 80
            }
        }, ensure_ascii=False).encode('utf-8') + b'\n'
        await asyncio.sleep(1.0)

        analysis_result = {
            "type": "general",
            "answer": qa_result.get("answer", "分析完成"),
            "knowledgeReference": qa_result.get("references", [])
        }

    yield json.dumps({
        "type": "step",
        "step": {
            "step": 4, "type": "analysis", "description": "执行分析计算",
            "status": "completed", "detail": "分析计算完成", "progress": 100
        }
    }, ensure_ascii=False).encode('utf-8') + b'\n'
    await asyncio.sleep(0.5)

    yield json.dumps({
        "type": "step",
        "step": {
            "step": 5, "type": "result_format", "description": "结果整理输出",
            "status": "completed", "detail": "正在格式化输出结果..."
        }
    }, ensure_ascii=False).encode('utf-8') + b'\n'
    await asyncio.sleep(0.8)

    # 保存会话记录
    now_str = datetime.datetime.now().isoformat()
    sessions[session_id].append({"role": "user", "content": query, "timestamp": now_str})
    sessions[session_id].append({
        "role": "assistant",
        "content": json.dumps(analysis_result, ensure_ascii=False)[:500],
        "timestamp": now_str
    })
    if len(sessions[session_id]) > MAX_CONTEXT * 4:
        sessions[session_id] = sessions[session_id][-(MAX_CONTEXT * 4):]
    save_sessions()

    yield json.dumps({
        "type": "result",
        "result": analysis_result,
        "intent": intent_result,
        "session_id": session_id
    }, ensure_ascii=False).encode('utf-8') + b'\n'


# ========== API端点 ==========

@app.get("/")
async def root():
    return {"service": "solution-evaluation-service", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ========== 会话管理 API ==========

@app.get("/solution/sessions")
async def list_sessions():
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
        last_time = msgs[-1].get("timestamp", datetime.datetime.now().isoformat())
        session_list.append({
            "id": sid,
            "title": latest_question or "(空会话)",
            "message_count": len(msgs),
            "last_active": last_time
        })
    session_list.sort(key=lambda x: x.get("last_active", ""), reverse=True)
    return {"success": True, "sessions": session_list}


@app.post("/solution/session/new")
async def new_session():
    new_id = str(uuid.uuid4())
    sessions[new_id] = []
    save_sessions()
    return {"success": True, "session_id": new_id}


@app.delete("/solution/session/{session_id}")
async def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        save_sessions()
        return {"success": True}
    raise HTTPException(status_code=404, detail="会话不存在")


@app.get("/solution/history")
async def get_history(session_id: str):
    if session_id not in sessions:
        return {"messages": []}
    return {
        "messages": [
            {"role": msg["role"], "content": msg["content"]}
            for msg in sessions[session_id]
        ]
    }


# 数据源
@app.get("/data-sources")
async def get_data_sources_api():
    return {"success": True, "dataSources": get_data_sources()}


# Skills管理
@app.get("/skills")
async def get_skills():
    return {"success": True, "skills": load_skills()}


@app.post("/skills")
async def create_skill(skill: Skill):
    skills = load_skills()
    skill_dict = skill.model_dump()
    if not skill_dict.get("id"):
        skill_dict["id"] = "skill-" + str(uuid.uuid4())[:8]
    skill_dict["createdAt"] = datetime.datetime.now().isoformat()
    skill_dict["updatedAt"] = skill_dict["createdAt"]
    skills.append(skill_dict)
    save_skills(skills)
    return {"success": True, "skill": skill_dict}


@app.put("/skills/{skill_id}")
async def update_skill(skill_id: str, skill: Skill):
    skills = load_skills()
    for i, s in enumerate(skills):
        if s["id"] == skill_id:
            skill_dict = skill.model_dump()
            skill_dict["id"] = skill_id
            skill_dict["updatedAt"] = datetime.datetime.now().isoformat()
            skill_dict["createdAt"] = s.get("createdAt", skill_dict["updatedAt"])
            skills[i] = skill_dict
            save_skills(skills)
            return {"success": True, "skill": skill_dict}
    raise HTTPException(status_code=404, detail="Skill not found")


@app.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    skills = load_skills()
    skills = [s for s in skills if s["id"] != skill_id]
    save_skills(skills)
    return {"success": True}


# 历史记录
@app.get("/history")
async def get_history_flat():
    return {"success": True, "history": load_history()}


# 流式评估接口
@app.post("/analyze/stream")
async def analyze_evaluation_stream(request: EvaluationRequest):
    skills = load_skills()
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    return StreamingResponse(
        stream_execution_steps(
            request.query,
            request.dataSourceId,
            request.skillId,
            skills,
            session_id
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# 同步评估接口（备用）
@app.post("/analyze")
async def analyze_evaluation_sync(request: EvaluationRequest):
    skills = load_skills()
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    intent_result = parse_intent(request.query)

    matched_skill = None
    if request.skillId:
        matched_skill = next((s for s in skills if s["id"] == request.skillId), None)
    elif intent_result.get("skillId"):
        matched_skill = next((s for s in skills if s["id"] == intent_result["skillId"]), None)

    now_str = datetime.datetime.now().isoformat()
    sessions[session_id].append({"role": "user", "content": request.query, "timestamp": now_str})
    sessions[session_id].append({
        "role": "assistant",
        "content": f"意图: {intent_result['intent']}, 技能: {matched_skill['name'] if matched_skill else '默认'}",
        "timestamp": now_str
    })
    if len(sessions[session_id]) > MAX_CONTEXT * 4:
        sessions[session_id] = sessions[session_id][-(MAX_CONTEXT * 4):]
    save_sessions()

    # 保存历史
    history = load_history()
    history_item = {
        "id": "history-" + str(uuid.uuid4())[:12],
        "query": request.query,
        "skillName": matched_skill["name"] if matched_skill else None,
        "timestamp": now_str,
        "status": "success"
    }
    history.insert(0, history_item)
    if len(history) > 50:
        history = history[:50]
    save_history(history)

    return {
        "success": True,
        "query": request.query,
        "session_id": session_id,
        "intent": intent_result,
        "matchedSkill": matched_skill,
        "historyId": history_item["id"]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10259)
