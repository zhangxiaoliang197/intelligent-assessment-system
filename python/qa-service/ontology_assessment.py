"""本体驱动评估：把本体从"展示层"接入评估分析主链路。

一次请求内完成：
1. 读取本体类型/实例/关系（类型层 + 实例层）；
2. 按属性上登记的数据字段绑定，从演示数据聚合基础指标；
3. 按口径版本计算三级指标链与制空权指数；
4. 运行质量门禁（缺值/值域/关系完整性/口径一致性/可溯源）；
5. 将指标链、本体依据与门禁结论交给大模型生成评估结论（要求逐条标注依据）；
6. 结论回写为本体实例，并把旧指标值写入属性历史。
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from airpower_metrics import (
    DATA_DIR,
    PROFILES,
    build_chain,
    compute_side,
    conclusion,
    data_gate,
    gate_summary,
    load_rows,
)

ONTOLOGY_SERVICE_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://localhost:10256").rstrip("/")

router = APIRouter(prefix="/evaluation", tags=["本体驱动评估"])

DEFAULT_ONTOLOGY = "ont_ede9d116"
TYPE_NAMES = {
    "battle": "战场",
    "base": "空军基地",
    "radar": "雷达站",
    "conclusion": "评估结论",
}


class OntologyAssessmentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ontology_id: str = Field(default="", alias="ontologyId")
    profile: str = Field(default="v1.2")
    write_back: bool = Field(default=True, alias="writeBack")
    question: str = Field(default="")


# ── ontology-service HTTP ──────────────────────────────────
def _get(path: str) -> dict:
    req = urllib.request.Request(f"{ONTOLOGY_SERVICE_URL}{path}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"本体服务返回 {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"无法访问本体服务：{exc}") from exc


def _post_form(path: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(f"{ONTOLOGY_SERVICE_URL}{path}", data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _put_form(path: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(f"{ONTOLOGY_SERVICE_URL}{path}", data=body, method="PUT")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_ontology(ontology_id: str) -> dict:
    meta = (_get(f"/ontology/{ontology_id}/meta").get("data") or {})
    entities = (_get(f"/ontology/{ontology_id}/entity/list?page=1&page_size=500").get("items") or [])
    relations = (_get(f"/ontology/{ontology_id}/relation/list?page=1&page_size=500").get("items") or [])
    types = {t["id"]: t for t in meta.get("entity_types", [])}
    for entity in entities:
        entity["_type"] = types.get(entity.get("instance_of"), {}).get("name", "")
    return {"meta": meta, "entities": entities, "relations": relations, "types": types}


def _pick(entities: list[dict], type_name: str, keyword: str = "") -> dict | None:
    for entity in entities:
        if entity.get("_type") != type_name:
            continue
        if keyword and keyword not in entity.get("name", ""):
            continue
        return entity
    return None


def _props(entity: dict) -> dict[str, dict]:
    return {p.get("name"): p for p in entity.get("properties", [])}


def _int_ontology_gate(data: dict, battle: dict, profile: str, computed_index: float) -> list[dict]:
    findings: list[dict] = []
    bases = [e for e in data["entities"] if e.get("_type") == TYPE_NAMES["base"]]
    relations = data["relations"]

    for base in bases:
        supported = any(
            r.get("relation_type") == "保障" and r.get("target_id") == base["id"] for r in relations
        )
        if not supported:
            findings.append({
                "level": "risk",
                "rule": "关系完整性",
                "message": f"「{base['name']}」没有雷达保障关系，该基地的体系支撑能力可能被低估",
                "evidence": f"{base['name']} ←(保障) 雷达站 · 缺失",
            })

    props = _props(battle)
    for name in ("制空权指数", "出动强度", "任务完成率", "战备完好率", "交换比"):
        prop = props.get(name)
        if not prop:
            findings.append({
                "level": "warning",
                "rule": "指标可溯源",
                "message": f"战场实例缺少指标属性「{name}」",
                "evidence": f"{battle['name']}.{name}",
            })
        elif not prop.get("bindings"):
            findings.append({
                "level": "warning",
                "rule": "字段绑定",
                "message": f"指标属性「{name}」未绑定数据字段，无法自动取数",
                "evidence": f"{battle['name']}.{name}",
            })

    stored = (props.get("制空权指数") or {}).get("value")
    stored_profile = ((props.get("制空权指数") or {}).get("bindings") or {}).get("profile", "")
    try:
        stored_value = float(stored) if stored is not None else None
    except (TypeError, ValueError):
        stored_value = None
    if stored_value is not None and stored_profile != profile and abs(stored_value - computed_index) > 0.3:
        findings.append({
            "level": "warning",
            "rule": "口径一致性",
            "message": (
                f"实例值 {stored_value} 分来自口径 {stored_profile or '未知'}，"
                f"当前口径 {profile} 重算为 {computed_index} 分，需回写更新"
            ),
            "evidence": f"制空权指数 · profile {stored_profile or '?'} → {profile}",
        })
    elif stored_value is not None and abs(stored_value - computed_index) > 0.3:
        findings.append({
            "level": "warning",
            "rule": "口径一致性",
            "message": f"实例值 {stored_value} 分与当前口径重算值 {computed_index} 分不一致",
            "evidence": "制空权指数",
        })
    return findings


def _gate(findings: list[dict]) -> dict:
    errors = sum(1 for f in findings if f["level"] == "error")
    warnings = sum(1 for f in findings if f["level"] == "warning")
    risks = sum(1 for f in findings if f["level"] == "risk")
    confidence = max(0.5, round(0.95 - 0.10 * errors - 0.03 * warnings - 0.05 * risks, 2))
    status = "未通过" if errors else ("有条件通过" if warnings or risks else "通过")
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "risks": risks,
        "confidence": confidence,
        "items": findings,
    }


def _evidence(data: dict, battle: dict) -> list[dict]:
    """把本体的类型-关系路径整理为可展示的"本体依据"。"""
    entities = data["entities"]
    relations = data["relations"]
    bases = [e for e in entities if e.get("_type") == TYPE_NAMES["base"]]
    radars = [e for e in entities if e.get("_type") == TYPE_NAMES["radar"]]
    base_ids = {b["id"] for b in bases}
    radar_links = [r for r in relations if r.get("relation_type") == "保障" and r.get("target_id") in base_ids]
    contains = [r for r in relations if r.get("relation_type") == "包含" and r.get("source_id") == battle["id"]]
    items = [
        {
            "typeName": "战场",
            "attribute": "制空权指数",
            "relationPath": f"战场「{battle['name']}」←包含— 空军基地 ×{len(contains)}",
        },
        {
            "typeName": "雷达站",
            "attribute": "开机时长",
            "relationPath": f"雷达站 →保障→ 空军基地（已建立 {len(radar_links)} 条保障关系）",
        },
        {
            "typeName": "作战飞机",
            "attribute": "可用率",
            "relationPath": "空军基地 →部署→ 作战飞机（战备完好率来源）",
        },
        {
            "typeName": "出动架次",
            "attribute": "架次数",
            "relationPath": "出动架次 →起飞于→ 空军基地（出动强度来源）",
        },
    ]
    missing = [r for r in radars if not any(x.get("source_id") == r["id"] for x in radar_links)]
    for radar in missing:
        items.append({
            "typeName": "雷达站",
            "attribute": "保障关系",
            "relationPath": f"雷达站「{radar['name']}」未关联任何空军基地",
        })
    return items


def _prompt(battle: dict, red: dict, blue: dict, chain: list[dict], gate: dict,
            evidence: list[dict], profile: str, question: str) -> tuple[str, str]:
    system = (
        "你是军事评估分析专家。必须严格依据给定本体事实与指标计算值作答，不得引入外部数据或编造数字。"
        "每一项判断后都要用【依据：类型.属性/关系链】标注本体来源。"
        "如果质量门禁存在缺口，必须说明它对结论置信度的影响。"
        "输出使用中文 Markdown，结构固定为四个小节：## 评估结论、## 优势与风险、## 建议、## 本体依据。"
        "全文 500 字以内，语言克制，避免空话。"
    )
    payload = {
        "评估对象": battle.get("name"),
        "口径版本": PROFILES[profile]["name"],
        "口径说明": PROFILES[profile]["note"],
        "红方指数": red["index"],
        "蓝方指数": blue["index"],
        "指标链": [
            {
                "层级": item["level"], "指标": item["name"], "值": item["value"], "单位": item["unit"],
                "公式": item["formula"], "本体属性": f"{item['typeName']}.{item['attribute']}",
            }
            for item in chain
        ],
        "质量门禁": {
            "状态": gate["status"], "置信度": gate["confidence"],
            "问题": [f"[{i['level']}] {i['message']}" for i in gate["items"]],
        },
        "本体依据": evidence,
    }
    if question.strip():
        payload["补充问题"] = question.strip()
    return system, json.dumps(payload, ensure_ascii=False, indent=2)


async def _narrate(system: str, user: str) -> str:
    import evaluation_api

    try:
        return await asyncio.to_thread(evaluation_api._sync_llm_call, system, user)
    except Exception as exc:  # noqa: BLE001
        return f"（大模型调用失败，以下为规则结论）{exc}"


def _write_back(data: dict, battle: dict, profile: str, red: dict, gate: dict, level: str, narrative: str) -> dict:
    """结论回写：新增评估结论实例 + 更新战场指标属性（旧值自动进入 history）。"""
    result: dict = {}
    props = _props(battle)
    index_prop = props.get("制空权指数") or {}
    if index_prop.get("id"):
        _put_form(
            f"/ontology/{battle['ontology_id']}/entity/{battle['id']}/property/{index_prop['id']}",
            {
                "value": str(red["index"]),
                "bindings": json.dumps({**(index_prop.get("bindings") or {}), "profile": profile}, ensure_ascii=False),
                "source_snippet": f"口径 {profile} 重算，门禁 {gate['status']}",
            },
        )
        result["indexPropertyId"] = index_prop["id"]
        result["indexValue"] = red["index"]

    level_prop = props.get("结论等级") or {}
    if level_prop.get("id"):
        _put_form(
            f"/ontology/{battle['ontology_id']}/entity/{battle['id']}/property/{level_prop['id']}",
            {"value": level},
        )

    created = _post_form(
        f"/ontology/{battle['ontology_id']}/entity",
        {
            "name": f"制空权评估结论 · {profile} · {datetime.now():%m-%d %H:%M}",
            "entity_type": TYPE_NAMES["conclusion"],
            "properties": json.dumps([
                {"name": "结论等级", "value": level, "category": "descriptive", "data_type": "string"},
                {"name": "置信度", "value": gate["confidence"], "category": "metric", "data_type": "number"},
                {
                    "name": "评估依据",
                    "value": f"口径 {profile}；红方 {red['index']} 分；门禁 {gate['status']}；{(narrative or '')[:180]}",
                    "category": "descriptive",
                    "data_type": "string",
                },
            ], ensure_ascii=False),
        },
    )
    entity_id = (created.get("data") or {}).get("id")
    result["conclusionEntityId"] = entity_id
    if entity_id:
        _post_form(
            f"/ontology/{battle['ontology_id']}/relation",
            {"source_id": entity_id, "target_id": battle["id"], "relation_type": "依据"},
        )
    return result


def _type_list(data: dict) -> list[dict]:
    """类型层摘要：属性数量与实例数量。"""
    counts: dict[str, int] = {}
    for entity in data["entities"]:
        counts[entity.get("_type", "")] = counts.get(entity.get("_type", ""), 0) + 1
    items = []
    for entity_type in data["meta"].get("entity_types", []):
        items.append({
            "name": entity_type.get("name"),
            "color": entity_type.get("color") or "#64748b",
            "instances": counts.get(entity_type.get("name"), 0),
            "attributes": [p.get("name") for p in entity_type.get("property_schema", [])],
        })
    return items


def _graph_sample(data: dict) -> list[dict]:
    """实例层关系样例：源实体 → 关系 → 目标实体。"""
    names = {e["id"]: e.get("name", "") for e in data["entities"]}
    samples = []
    for relation in data["relations"]:
        source = names.get(relation.get("source_id"), "")
        target = names.get(relation.get("target_id"), "")
        if source and target:
            samples.append({
                "source": source,
                "target": target,
                "relation": relation.get("relation_type", ""),
            })
    priority = {"包含": 0, "保障": 1, "部署": 2, "起飞于": 3, "依据": 4}
    samples.sort(key=lambda item: priority.get(item["relation"], 9))
    return samples[:8]


@router.get("/ontology-assess/default")
async def default_ontology() -> dict:
    """返回演示本体 ID（供前端默认选中）。"""
    path = DATA_DIR / "ontology_id.txt"
    ontology_id = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    return {"success": True, "data": {"ontologyId": ontology_id or DEFAULT_ONTOLOGY}}


@router.post("/ontology-assess")
async def assess(request: OntologyAssessmentRequest) -> dict:
    profile = request.profile if request.profile in PROFILES else "v1.2"
    ontology_id = request.ontology_id.strip()
    if not ontology_id:
        default_path = DATA_DIR / "ontology_id.txt"
        ontology_id = default_path.read_text(encoding="utf-8").strip() if default_path.exists() else DEFAULT_ONTOLOGY

    data = _load_ontology(ontology_id)
    battle = _pick(data["entities"], TYPE_NAMES["battle"], "红方")
    if not battle:
        raise HTTPException(400, "该本体中没有「战场」类型实例，无法执行本体驱动评估")
    blue_battle = _pick(data["entities"], TYPE_NAMES["battle"], "蓝方")

    rows = load_rows()
    red = compute_side(rows, "red", profile)
    blue = compute_side(rows, "blue", profile)
    chain = build_chain(red, blue, profile, ontology_id, battle["id"])
    level, meaning = conclusion(red["index"], blue["index"])

    findings = data_gate(rows) + _int_ontology_gate(data, battle, profile, red["index"])
    gate = _gate(findings)
    evidence = _evidence(data, battle)

    comparisons = {}
    for key in PROFILES:
        r = compute_side(rows, "red", key)
        b = compute_side(rows, "blue", key)
        lv, _ = conclusion(r["index"], b["index"])
        comparisons[key] = {
            "name": PROFILES[key]["name"], "note": PROFILES[key]["note"],
            "weights": PROFILES[key]["weights"], "red": r["index"], "blue": b["index"],
            "level": lv,
        }

    system, user = _prompt(battle, red, blue, chain, gate, evidence, profile, request.question)
    narrative = await _narrate(system, user)

    write_result = {}
    if request.write_back:
        try:
            write_result = _write_back(data, battle, profile, red, gate, level, narrative)
        except Exception as exc:  # noqa: BLE001
            write_result = {"error": str(exc)}

    return {
        "success": True,
        "data": {
            "ontology": {
                "id": ontology_id,
                "name": (data["meta"].get("name") if data["meta"].get("name") else "红蓝对抗制空权评估本体"),
                "types": len(data["types"]),
                "entities": len(data["entities"]),
                "relations": len(data["relations"]),
                "relationTypes": [r.get("name") for r in data["meta"].get("relation_types", [])],
                "typeRelations": data["meta"].get("entity_type_relations", []),
                "typeList": _type_list(data),
                "graph": _graph_sample(data),
            },
            "battle": {"id": battle["id"], "name": battle.get("name"), "blueId": (blue_battle or {}).get("id", "")},
            "profile": {
                "key": profile,
                "name": PROFILES[profile]["name"],
                "note": PROFILES[profile]["note"],
                "weights": PROFILES[profile]["weights"],
            },
            "metrics": {
                "red": red, "blue": blue, "level": level, "meaning": meaning,
                "indexDelta": round(red["index"] - blue["index"], 1),
            },
            "chain": chain,
            "gate": gate,
            "evidence": evidence,
            "narrative": narrative,
            "comparisons": comparisons,
            "writeBack": write_result,
            "dataSource": {"file": "airbase_daily.csv", "rows": len(rows), "bindingMode": "本体属性绑定数据字段"},
        },
    }
