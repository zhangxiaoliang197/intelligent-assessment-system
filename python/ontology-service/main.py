from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

from fastapi import FastAPI, HTTPException, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
import uuid
import json
import os

app = FastAPI(
    title="本体模型服务",
    description="本体构建与知识图谱展示",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Entity(BaseModel):
    id: str
    name: str
    type: str
    properties: Dict[str, str]
    create_time: datetime
    update_time: datetime

class Relation(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, str]
    weight: float
    create_time: datetime

class OntologyModel(BaseModel):
    id: str
    name: str
    description: str
    version: str
    entities_count: int
    relations_count: int
    create_time: datetime
    update_time: datetime
    status: str

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
ONTOLOGIES_FILE = os.path.join(DATA_DIR, 'ontologies.json')
ENTITIES_FILE = os.path.join(DATA_DIR, 'entities.json')
RELATIONS_FILE = os.path.join(DATA_DIR, 'relations.json')
os.makedirs(DATA_DIR, exist_ok=True)

def load_db():
    result = {'ontologies': [], 'entities': [], 'relations': []}
    if os.path.exists(ONTOLOGIES_FILE):
        with open(ONTOLOGIES_FILE, 'r', encoding='utf-8') as f:
            result['ontologies'] = [OntologyModel(**item) for item in json.load(f)]
    if os.path.exists(ENTITIES_FILE):
        with open(ENTITIES_FILE, 'r', encoding='utf-8') as f:
            result['entities'] = [Entity(**item) for item in json.load(f)]
    if os.path.exists(RELATIONS_FILE):
        with open(RELATIONS_FILE, 'r', encoding='utf-8') as f:
            result['relations'] = [Relation(**item) for item in json.load(f)]
    return result['ontologies'], result['entities'], result['relations']

def save_db():
    with open(ONTOLOGIES_FILE, 'w', encoding='utf-8') as f:
        json.dump([o.dict() for o in ontologies_db], f, ensure_ascii=False, indent=2, default=str)
    with open(ENTITIES_FILE, 'w', encoding='utf-8') as f:
        json.dump([e.dict() for e in entities_db], f, ensure_ascii=False, indent=2, default=str)
    with open(RELATIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump([r.dict() for r in relations_db], f, ensure_ascii=False, indent=2, default=str)

ontologies_db, entities_db, relations_db = load_db()

def get_graph_data():
    nodes = []
    links = []
    node_map = {}

    for entity in entities_db:
        nodes.append({
            "id": entity.id,
            "name": entity.name,
            "type": entity.type,
            "category": entity.type
        })
        node_map[entity.id] = entity.name

    for relation in relations_db:
        links.append({
            "source": relation.source_id,
            "target": relation.target_id,
            "relation": relation.relation_type,
            "weight": relation.weight
        })

    return {"nodes": nodes, "links": links}

@app.get("/")
async def root():
    return {
        "service": "本体模型服务",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ontology-service"}

@app.post("/ontology/create")
async def create_ontology(
    name: str = Form(...),
    description: str = Form("")
):
    ontology = OntologyModel(
        id=f"ont_{uuid.uuid4().hex[:8]}",
        name=name,
        description=description,
        version="1.0.0",
        entities_count=0,
        relations_count=0,
        create_time=datetime.now(),
        update_time=datetime.now(),
        status="活跃"
    )
    ontologies_db.append(ontology)

    save_db()
    return {
        "success": True,
        "message": "本体模型创建成功",
        "data": ontology.dict()
    }

@app.get("/ontology/list")
async def list_ontologies():
    return {
        "success": True,
        "total": len(ontologies_db),
        "items": [o.dict() for o in ontologies_db]
    }

@app.get("/ontology/{ontology_id}")
async def get_ontology(ontology_id: str):
    for ontology in ontologies_db:
        if ontology.id == ontology_id:
            return {
                "success": True,
                "data": ontology.dict()
            }

    raise HTTPException(status_code=404, detail="本体模型不存在")

@app.put("/ontology/{ontology_id}")
async def update_ontology(
    ontology_id: str,
    name: str = Form(...),
    description: str = Form("")
):
    for ontology in ontologies_db:
        if ontology.id == ontology_id:
            ontology.name = name
            ontology.description = description
            ontology.update_time = datetime.now()
            save_db()
            return {
                "success": True,
                "message": "本体模型更新成功"
            }

    raise HTTPException(status_code=404, detail="本体模型不存在")

@app.delete("/ontology/{ontology_id}")
async def delete_ontology(ontology_id: str):
    global entities_db, relations_db

    for i, ontology in enumerate(ontologies_db):
        if ontology.id == ontology_id:
            ontologies_db.pop(i)

            entity_ids = [e.id for e in entities_db]
            entities_db = [e for e in entities_db if e.id not in entity_ids]
            relations_db = [r for r in relations_db if r.source_id not in entity_ids and r.target_id not in entity_ids]

            save_db()
            return {
                "success": True,
                "message": "本体模型删除成功"
            }

    raise HTTPException(status_code=404, detail="本体模型不存在")

@app.post("/ontology/{ontology_id}/entity")
async def add_entity(
    ontology_id: str,
    name: str = Form(...),
    entity_type: str = Form(...),
    properties: str = Form("")
):
    properties_dict = {}
    if properties:
        for prop in properties.split(','):
            if ':' in prop:
                key, value = prop.split(':', 1)
                properties_dict[key.strip()] = value.strip()

    entity = Entity(
        id=f"ent_{uuid.uuid4().hex[:8]}",
        name=name,
        type=entity_type,
        properties=properties_dict,
        create_time=datetime.now(),
        update_time=datetime.now()
    )
    entities_db.append(entity)

    for ontology in ontologies_db:
        if ontology.id == ontology_id:
            ontology.entities_count = len(entities_db)
            ontology.update_time = datetime.now()

    save_db()
    return {
        "success": True,
        "message": "实体添加成功",
        "data": entity.dict()
    }

@app.get("/ontology/entity/list")
async def list_entities(
    entity_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    filtered = entities_db

    if entity_type:
        filtered = [e for e in filtered if e.type == entity_type]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [e.dict() for e in items]
    }

@app.get("/ontology/entity/{entity_id}")
async def get_entity(entity_id: str):
    for entity in entities_db:
        if entity.id == entity_id:
            return {
                "success": True,
                "data": entity.dict()
            }

    raise HTTPException(status_code=404, detail="实体不存在")

@app.put("/ontology/entity/{entity_id}")
async def update_entity(
    entity_id: str,
    name: str = Form(...),
    entity_type: str = Form(...),
    properties: str = Form("")
):
    properties_dict = {}
    if properties:
        for prop in properties.split(','):
            if ':' in prop:
                key, value = prop.split(':', 1)
                properties_dict[key.strip()] = value.strip()

    for entity in entities_db:
        if entity.id == entity_id:
            entity.name = name
            entity.type = entity_type
            entity.properties = properties_dict
            entity.update_time = datetime.now()
            save_db()
            return {
                "success": True,
                "message": "实体更新成功"
            }

    raise HTTPException(status_code=404, detail="实体不存在")

@app.delete("/ontology/entity/{entity_id}")
async def delete_entity(entity_id: str):
    global relations_db

    for i, entity in enumerate(entities_db):
        if entity.id == entity_id:
            entities_db.pop(i)

            relations_db = [
                r for r in relations_db
                if r.source_id != entity_id and r.target_id != entity_id
            ]

            for ontology in ontologies_db:
                ontology.entities_count = len(entities_db)
                ontology.relations_count = len(relations_db)

            save_db()
            return {
                "success": True,
                "message": "实体删除成功"
            }

    raise HTTPException(status_code=404, detail="实体不存在")

@app.post("/ontology/relation")
async def add_relation(
    source_id: str = Form(...),
    target_id: str = Form(...),
    relation_type: str = Form(...),
    weight: float = Form(1.0),
    properties: str = Form("")
):
    properties_dict = {}
    if properties:
        for prop in properties.split(','):
            if ':' in prop:
                key, value = prop.split(':', 1)
                properties_dict[key.strip()] = value.strip()

    source_exists = any(e.id == source_id for e in entities_db)
    target_exists = any(e.id == target_id for e in entities_db)

    if not source_exists or not target_exists:
        raise HTTPException(status_code=400, detail="源实体或目标实体不存在")

    relation = Relation(
        id=f"rel_{uuid.uuid4().hex[:8]}",
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        properties=properties_dict,
        weight=weight,
        create_time=datetime.now()
    )
    relations_db.append(relation)

    for ontology in ontologies_db:
        ontology.relations_count = len(relations_db)

    save_db()
    return {
        "success": True,
        "message": "关系添加成功",
        "data": relation.dict()
    }

@app.get("/ontology/relation/list")
async def list_relations(
    source_id: Optional[str] = None,
    target_id: Optional[str] = None,
    relation_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    filtered = relations_db

    if source_id:
        filtered = [r for r in filtered if r.source_id == source_id]
    if target_id:
        filtered = [r for r in filtered if r.target_id == target_id]
    if relation_type:
        filtered = [r for r in filtered if r.relation_type == relation_type]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    enriched_items = []
    for r in items:
        source_name = next((e.name for e in entities_db if e.id == r.source_id), "未知")
        target_name = next((e.name for e in entities_db if e.id == r.target_id), "未知")
        enriched_items.append({
            **r.dict(),
            "source_name": source_name,
            "target_name": target_name
        })

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": enriched_items
    }

@app.delete("/ontology/relation/{relation_id}")
async def delete_relation(relation_id: str):
    for i, relation in enumerate(relations_db):
        if relation.id == relation_id:
            relations_db.pop(i)

            for ontology in ontologies_db:
                ontology.relations_count = len(relations_db)

            save_db()
            return {
                "success": True,
                "message": "关系删除成功"
            }

    raise HTTPException(status_code=404, detail="关系不存在")

@app.get("/ontology/graph")
async def get_graph():
    return {
        "success": True,
        "data": get_graph_data()
    }

@app.get("/ontology/stats")
async def get_stats():
    entity_types = {}
    for entity in entities_db:
        entity_types[entity.type] = entity_types.get(entity.type, 0) + 1

    relation_types = {}
    for relation in relations_db:
        relation_types[relation.relation_type] = relation_types.get(relation.relation_type, 0) + 1

    return {
        "success": True,
        "data": {
            "total_entities": len(entities_db),
            "total_relations": len(relations_db),
            "total_ontologies": len(ontologies_db),
            "entity_types": entity_types,
            "relation_types": relation_types,
            "avg_relations_per_entity": len(relations_db) / len(entities_db) if entities_db else 0
        }
    }

@app.post("/ontology/import")
async def import_ontology(file: UploadFile = File(...)):
    try:
        content = await file.read()
        data = json.loads(content)

        ontology = OntologyModel(
            id=f"ont_{uuid.uuid4().hex[:8]}",
            name=data.get("name", "导入本体"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            entities_count=len(data.get("entities", [])),
            relations_count=len(data.get("relations", [])),
            create_time=datetime.now(),
            update_time=datetime.now(),
            status="活跃"
        )
        ontologies_db.append(ontology)

        for entity_data in data.get("entities", []):
            entity = Entity(
                id=f"ent_{uuid.uuid4().hex[:8]}",
                name=entity_data.get("name"),
                type=entity_data.get("type", "概念"),
                properties=entity_data.get("properties", {}),
                create_time=datetime.now(),
                update_time=datetime.now()
            )
            entities_db.append(entity)

        for relation_data in data.get("relations", []):
            relation = Relation(
                id=f"rel_{uuid.uuid4().hex[:8]}",
                source_id=relation_data.get("source_id"),
                target_id=relation_data.get("target_id"),
                relation_type=relation_data.get("type", "关联"),
                properties=relation_data.get("properties", {}),
                weight=relation_data.get("weight", 1.0),
                create_time=datetime.now()
            )
            relations_db.append(relation)

        save_db()
        return {
            "success": True,
            "message": "本体模型导入成功",
            "data": {
                "ontology_id": ontology.id,
                "entities_imported": len(data.get("entities", [])),
                "relations_imported": len(data.get("relations", []))
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")

@app.get("/ontology/export/{ontology_id}")
async def export_ontology(ontology_id: str):
    for ontology in ontologies_db:
        if ontology.id == ontology_id:
            data = {
                "name": ontology.name,
                "description": ontology.description,
                "version": ontology.version,
                "entities": [e.dict() for e in entities_db],
                "relations": [r.dict() for r in relations_db]
            }
            return {
                "success": True,
                "data": data
            }

    raise HTTPException(status_code=404, detail="本体模型不存在")

@app.post("/ontology/search")
async def search_ontology(query: str = Form(...)):
    results = {
        "entities": [],
        "relations": []
    }

    query_lower = query.lower()

    for entity in entities_db:
        if query_lower in entity.name.lower() or query_lower in entity.type.lower():
            results["entities"].append(entity.dict())

    for relation in relations_db:
        if query_lower in relation.relation_type.lower():
            results["relations"].append(relation.dict())

    return {
        "success": True,
        "query": query,
        "total": len(results["entities"]) + len(results["relations"]),
        "data": results
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10256)
