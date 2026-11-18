"""Persist the real Ontosphere editor while keeping the existing v3 APIs usable."""
from __future__ import annotations
import hashlib
from datetime import datetime
import json
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from rdflib import Dataset, Graph

import workbench as wb
from models import OntologyModel, EntityType, Entity, Relation, EntityTypeRelation
from examples.wargame import DEMO_DESCRIPTION, DEMO_ID, DEMO_NAME, demo_payload, make_graph, update_demo_literals, update_demo_metadata

router = APIRouter(prefix="/ontology", tags=["Ontosphere 原生编辑器"])


class EditorSave(BaseModel):
    turtle: str = Field(default="", max_length=5_000_000)
    dataset: str = Field(default="", max_length=12_000_000)
    expected_revision: str = Field(min_length=64, max_length=64)
    layouts: dict[str, Any] = Field(default_factory=dict)
    namespaces: dict[str, str] = Field(default_factory=dict)
    note: str = Field(default="Ontosphere 画布编辑", max_length=300)


def install_models(service, document):
    identifier = document["ontology"]["id"]
    types = [EntityType.model_validate(value) for value in document["entity_types"]]
    service.ontologies_db[identifier] = OntologyModel.model_validate({**document["ontology"], "entity_types": types})
    service.entity_types_db[identifier] = types
    service.entities_db[identifier] = [Entity.model_validate(value) for value in document["entities"]]
    service.relations_db[identifier] = [Relation.model_validate(value) for value in document["relations"]]
    service.entity_type_relations_db[identifier] = [EntityTypeRelation.model_validate(value) for value in document["entity_type_relations"]]


def normalized_demo_dataset(dataset, seed, original):
    changed = False
    for named_graph in dataset.graphs():
        changed = update_demo_literals(named_graph, seed) or changed
    return dataset.serialize(format="nquads") if changed else original


def editor_graph(document):
    ontology = document["ontology"]
    graph, _ = wb.rdf_graph(document)
    cache_valid = ontology.get("rdf_projection_hash") == wb.projection_fingerprint(document)
    dataset_text = ontology.get("rdf_dataset", "") if cache_valid else ""
    if ontology["id"] == DEMO_ID:
        current_seed = make_graph(3)
        update_demo_literals(graph, current_seed)
        if dataset_text:
            dataset = Dataset().parse(data=dataset_text, format="nquads")
            dataset_text = normalized_demo_dataset(dataset, current_seed, dataset_text)
    return graph, dataset_text


def editor_payload(identifier):
    snapshot = wb.snapshot(identifier)
    document = snapshot["document"]
    ontology = document["ontology"]
    update_demo_metadata(ontology)
    graph, dataset_text = editor_graph(document)
    return {"id": identifier, "name": ontology["name"], "revision": snapshot["revision"],
        "turtle": graph.serialize(format="turtle"),
        "dataset": dataset_text,
        "layouts": ontology.get("canvas_layouts") or {}, "namespaces": ontology.get("namespaces") or {},
        "is_demo": identifier == DEMO_ID, "triple_count": len(graph),
        "types": len(document["entity_types"]), "entities": len(document["entities"])}


def reconcile_projection(document, previous):
    """Retain v3 identifiers, bindings and source evidence for unchanged IRIs."""
    _, old_iris = wb.rdf_graph(previous)
    type_ids = {str(old_iris[item["id"]]): item for item in previous["entity_types"]}
    entity_ids = {str(old_iris[item["id"]]): item for item in previous["entities"]}
    remap = {}
    for collection, existing in (("entity_types", type_ids), ("entities", entity_ids)):
        for item in document[collection]:
            old = existing.get(item.get("iri"))
            if not old:
                continue
            remap[item["id"]] = old["id"]
            fresh = dict(item)
            if collection == "entity_types":
                fresh["property_schema"] = old.get("property_schema") or []
            else:
                base = f"https://assessment.local/ontology/{previous['ontology']['id']}#"
                properties = {prop.get("iri") or base + "property_" + hashlib.sha1(prop["name"].encode()).hexdigest()[:12]: prop for prop in old.get("properties") or []}
                merged = []
                for prop in item.get("properties") or []:
                    original = properties.get(prop.get("iri"), {})
                    merged.append({**original, **prop, "id": original.get("id", prop["id"]), "entity_id": old["id"], "create_time": original.get("create_time", prop["create_time"])})
                fresh["properties"] = merged
            item.update({**old, **fresh, "id": old["id"], "create_time": old.get("create_time", fresh.get("create_time"))})
    for item in document["entity_types"]:
        item["parent_entity_type_id"] = remap.get(item.get("parent_entity_type_id"), item.get("parent_entity_type_id"))
    for item in document["entities"]:
        item["instance_of"] = remap.get(item.get("instance_of"), item.get("instance_of"))
    for collection, fields in (("relations", ("source_id", "target_id")), ("entity_type_relations", ("source_entity_type_id", "target_entity_type_id"))):
        old_edges = {(item[fields[0]], item["relation_type"], item[fields[1]]): item for item in previous[collection]}
        for item in document[collection]:
            for field in fields:
                item[field] = remap.get(item[field], item[field])
            old = old_edges.get((item[fields[0]], item["relation_type"], item[fields[1]]))
            if old:
                item.update({**old, **item, "id": old["id"]})
    # OWL permits cyclic subclass axioms. Keep those in the authoritative RDF,
    # and expose a finite spanning hierarchy to the legacy tree-based services.
    types = {item["id"]: item for item in document["entity_types"]}
    for item in types.values():
        seen, current = {item["id"]}, item.get("parent_entity_type_id")
        while current and current in types:
            if current in seen:
                item["parent_entity_type_id"] = None
                break
            seen.add(current)
            current = types[current].get("parent_entity_type_id")
    return document


@router.post("/{ontology_id}/workbench/editor/preview")
async def preview_revision(ontology_id: str, request: wb.DocumentRequest):
    wb.snapshot(ontology_id)
    document = request.document
    if not document or document.get("ontology", {}).get("id") != ontology_id:
        raise HTTPException(400, "历史快照不属于当前本体")
    graph, dataset_text = editor_graph(document)
    metadata = document["ontology"]
    return {"success": True, "data": {"id": ontology_id, "triple_count": len(graph), "turtle": graph.serialize(format="turtle"),
        "dataset": dataset_text,
        "layouts": metadata.get("canvas_layouts") or {}, "namespaces": metadata.get("namespaces") or {}}}


def asserted_graph(request, *, demo_seed=None):
    if not request.dataset:
        graph = wb.parse_rdf(request.turtle, "turtle") if request.turtle.strip() else Graph()
        if demo_seed is not None:
            update_demo_literals(graph, demo_seed)
        return graph, ""
    try:
        dataset = Dataset().parse(data=request.dataset, format="nquads")
    except Exception as error:
        raise HTTPException(400, f"N-Quads 数据集解析失败：{str(error)[:200]}") from error
    if len(dataset) > 75000:
        raise HTTPException(400, "单次保存最多 75000 个四元组")
    dataset_text = normalized_demo_dataset(dataset, demo_seed, request.dataset) if demo_seed is not None else request.dataset
    graph = Graph()
    for subject, predicate, obj, context in dataset.quads():
        name = str(context)
        if name in {"urn:vg:inferred", "urn:vg:shapes", "urn:vg:workflows"} or "provenance" in name:
            continue
        graph.add((subject, predicate, obj))
    for prefix, namespace in request.namespaces.items():
        graph.bind(prefix, namespace)
    return graph, dataset_text


@router.get("/{ontology_id}/workbench/editor")
async def get_editor(ontology_id: str):
    return {"success": True, "data": editor_payload(ontology_id)}


@router.put("/{ontology_id}/workbench/editor")
async def save_editor(ontology_id: str, request: EditorSave):
    if len(json.dumps(request.layouts, ensure_ascii=False)) > 2_000_000:
        raise HTTPException(400, "画布布局数据不能超过 2 MB")
    previous = wb.snapshot(ontology_id)
    if previous["revision"] != request.expected_revision:
        raise HTTPException(409, "本体已被更新，请重新载入后合并修改")
    graph, dataset_text = asserted_graph(request, demo_seed=make_graph(3) if ontology_id == DEMO_ID else None)
    document, _ = wb.rdf_to_document(graph, previous["document"]["ontology"])
    document = reconcile_projection(document, previous["document"])
    update_demo_metadata(document["ontology"])
    document["ontology"].update({"rdf_document": graph.serialize(format="turtle"), "rdf_dataset": dataset_text,
        "canvas_layouts": request.layouts, "namespaces": {**document["ontology"].get("namespaces", {}), **request.namespaces}})
    saved = await wb.persist_document(ontology_id, wb.SaveRequest(document=document, expected_revision=request.expected_revision, note=request.note), rdf_mode=True)
    return {"success": True, "data": {**editor_payload(ontology_id), "legacy_validation_warnings": saved["data"].get("legacy_validation_warnings", [])}}


@router.post("/examples/wargame")
async def ensure_wargame():
    service = wb.host()
    async with service.db_lock:
        created = DEMO_ID not in service.ontologies_db
        if created:
            now = datetime.now().isoformat()
            graph = make_graph(0)
            metadata = {"id": DEMO_ID, "name": DEMO_NAME, "description": DEMO_DESCRIPTION, "version": "1.0.0", "status": "活跃", "create_time": now, "update_time": now}
            document, _ = wb.rdf_to_document(graph, metadata)
            document["ontology"]["rdf_document"] = graph.serialize(format="turtle")
            install_models(service, document)
            service.ontologies_db[DEMO_ID].rdf_projection_hash = wb.projection_fingerprint(wb.snapshot(DEMO_ID)["document"])
            service.save_ontology(DEMO_ID)
            service.save_index()
    return {"success": True, "data": {**editor_payload(DEMO_ID), "created": created, "scenario": demo_payload(0)}}


@router.get("/examples/wargame/turns/{turn}")
async def wargame_turn(turn: int):
    if turn not in range(4):
        raise HTTPException(400, "示例支持回合 0–3")
    return {"success": True, "data": demo_payload(turn)}
