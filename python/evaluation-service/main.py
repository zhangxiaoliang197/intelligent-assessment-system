from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid

app = FastAPI(
    title="方案评估服务",
    description="评估方案的构建与管理",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class EvaluationScheme(BaseModel):
    id: str
    name: str
    description: str
    indicators: List[str]
    status: str
    create_time: datetime
    update_time: datetime

class CreateSchemeRequest(BaseModel):
    name: str
    description: str
    indicators: List[str]

schemes_db = []

@app.get("/")
async def root():
    return {
        "service": "evaluation-service",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/evaluation/scheme", response_model=EvaluationScheme)
async def create_scheme(request: CreateSchemeRequest):
    scheme = EvaluationScheme(
        id=str(uuid.uuid4()),
        name=request.name,
        description=request.description,
        indicators=request.indicators,
        status="待评估",
        create_time=datetime.now(),
        update_time=datetime.now()
    )
    schemes_db.append(scheme)
    return scheme

@app.get("/evaluation/scheme/list")
async def list_schemes():
    return {
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "indicators": s.indicators,
                "status": s.status,
                "create_time": s.create_time.isoformat(),
                "update_time": s.update_time.isoformat()
            }
            for s in schemes_db
        ]
    }

@app.get("/evaluation/scheme/{scheme_id}")
async def get_scheme(scheme_id: str):
    for scheme in schemes_db:
        if scheme.id == scheme_id:
            return {
                "id": scheme.id,
                "name": scheme.name,
                "description": scheme.description,
                "indicators": scheme.indicators,
                "status": scheme.status,
                "create_time": scheme.create_time.isoformat(),
                "update_time": scheme.update_time.isoformat()
            }

    raise HTTPException(status_code=404, detail="评估方案不存在")

@app.post("/evaluation/scheme/{scheme_id}/execute")
async def execute_scheme(scheme_id: str):
    for scheme in schemes_db:
        if scheme.id == scheme_id:
            scheme.status = "评估中"
            scheme.update_time = datetime.now()

            result = {
                "scheme_id": scheme_id,
                "status": "completed",
                "score": 85.5,
                "grade": "优秀",
                "details": [
                    {"indicator": "打击能力", "score": 88, "weight": 0.4},
                    {"indicator": "生存能力", "score": 82, "weight": 0.3},
                    {"indicator": "保障能力", "score": 85, "weight": 0.3}
                ],
                "recommendations": [
                    "打击能力表现优秀，建议保持",
                    "生存能力有提升空间，建议加强防护",
                    "保障能力良好，建议优化补给流程"
                ]
            }

            scheme.status = "已完成"
            scheme.update_time = datetime.now()

            return result

    raise HTTPException(status_code=404, detail="评估方案不存在")

@app.delete("/evaluation/scheme/{scheme_id}")
async def delete_scheme(scheme_id: str):
    for i, scheme in enumerate(schemes_db):
        if scheme.id == scheme_id:
            schemes_db.pop(i)
            return {"message": "评估方案已删除"}

    raise HTTPException(status_code=404, detail="评估方案不存在")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
