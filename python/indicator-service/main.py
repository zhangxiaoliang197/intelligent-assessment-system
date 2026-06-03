from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import os
import urllib.request
import urllib.error
import ssl
import re

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

class AnalyzeRequest(BaseModel):
    query: str
    depth: int = 3

def call_llm_for_indicator_analysis(query: str) -> dict:
    """调用QA服务获取指标分析结果，要求返回结构化JSON"""
    try:
        prompt = f"""请分析以下指标需求，并返回结构化的JSON数据：

需求：{query}

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
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data.get("answer", "")
            
            # 尝试从回答中提取JSON
            result = parse_structured_response(answer)
            
            return result
    except Exception as e:
        return {
            "answer": f"调用大模型分析失败: {str(e)}",
            "tree": get_default_tree(),
            "indicators": get_default_indicators(),
            "references": [],
            "summary": ""
        }

def parse_structured_response(answer: str) -> dict:
    """从大模型回答中解析结构化JSON"""
    try:
        # 尝试提取JSON代码块
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', answer)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接查找JSON对象
            json_match = re.search(r'\{[\s\S]*\}', answer)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = answer
        
        # 清理JSON字符串
        json_str = json_str.strip()
        
        # 尝试解析JSON
        data = json.loads(json_str)
        
        # 验证必要字段
        if "tree" not in data:
            data["tree"] = get_default_tree()
        if "indicators" not in data:
            data["indicators"] = get_default_indicators()
        if "summary" not in data:
            data["summary"] = ""
            
        # 转换为前端需要的格式
        result = {
            "answer": answer,  # 保留原始回答
            "tree": data.get("tree", get_default_tree()),
            "indicators": data.get("indicators", get_default_indicators()),
            "summary": data.get("summary", ""),
            "references": []
        }
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        print(f"原始回答: {answer}")
        # 返回默认结构
        return {
            "answer": answer,
            "tree": get_default_tree(),
            "indicators": get_default_indicators(),
            "summary": "",
            "references": []
        }

def get_default_tree() -> Dict:
    """获取默认的指标树状结构"""
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
    """获取默认的指标详情"""
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

@app.post("/indicator/analyze")
async def analyze_indicator(request: AnalyzeRequest):
    """分析指标请求"""
    # 调用大模型获取结构化分析结果
    result = call_llm_for_indicator_analysis(request.query)
    
    return {
        "success": True,
        "query": request.query,
        "answer": result.get("answer", ""),
        "summary": result.get("summary", ""),
        "tree": result.get("tree", get_default_tree()),
        "indicators": result.get("indicators", get_default_indicators()),
        "references": result.get("references", []),
        "message": "指标分析完成"
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
