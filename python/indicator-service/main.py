from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict

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

class IndicatorNode(BaseModel):
    name: str
    source: str
    children: Optional[List["IndicatorNode"]] = None

class AnalyzeRequest(BaseModel):
    query: str
    depth: int = 3

class IndicatorDetail(BaseModel):
    name: str
    source: str
    definition: str
    formula: str
    criteria: str
    weight: float

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
    tree_data = {
        "name": "作战效能",
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

    return {
        "query": request.query,
        "tree": tree_data,
        "message": "指标分析完成"
    }

@app.get("/indicator/tree")
async def get_indicator_tree():
    return {
        "name": "作战效能",
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
    uvicorn.run(app, host="0.0.0.0", port=8003)
