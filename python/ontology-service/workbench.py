"""Dynamic ontology workbench: revisioned authoring, RDF, OWL-RL and SHACL.

The editing/exploration workflow is inspired by Ontosphere. This implementation
uses the application's existing v3 domain model and persistence, rather than
embedding an unrelated client-side store that downstream evaluation cannot see.
"""
from __future__ import annotations

from collections import Counter
import copy
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from filelock import FileLock
from pydantic import BaseModel, Field, field_validator

from models import Entity, EntityType, EntityTypeRelation, OntologyModel, Relation


router = APIRouter(prefix="/ontology", tags=["动态本体工作台"])


def host():
    """返回正在运行的 main 模块。

    main.py 以 `python main.py` 启动时模块名是 `__main__`，此时 `import main`
    会再次执行模块级 `load_db()`，产生一份与线上不一致的第二份内存数据，
    表现为列表/元数据正常但工作台报“本体不存在”。优先复用入口模块。
    """
    import sys
    running = sys.modules.get("__main__")
    if running is not None and hasattr(running, "ontologies_db"):
        return running
    import main
    return main


def fingerprint(document):
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def projection_fingerprint(document):
    projection = {key: document.get(key) or [] for key in ("entity_types", "entities", "relations", "entity_type_relations")}
    projection["relation_types"] = (document.get("ontology") or {}).get("relation_types") or []
    return fingerprint(projection)


def snapshot(ontology_id):
    service = host()
    ontology = service._get_ontology_or_404(ontology_id)
    document = {
        "ontology": ontology.model_dump(mode="json"),
        "entity_types": [item.model_dump(mode="json") for item in service.entity_types_db.get(ontology_id, [])],
        "entity_type_relations": [item.model_dump(mode="json") for item in service.entity_type_relations_db.get(ontology_id, [])],
        "entities": [item.model_dump(mode="json") for item in service.entities_db.get(ontology_id, [])],
        "relations": [item.model_dump(mode="json") for item in service.relations_db.get(ontology_id, [])],
    }
    return {"document": document, "revision": fingerprint(document)}


class DocumentRequest(BaseModel):
    document: dict[str, Any]

    @field_validator("document")
    @classmethod
    def check_document_shape(cls, value):
        if not isinstance(value.get("ontology"), dict):
            raise ValueError("ontology 必须是对象")
        for key in ("entity_types", "entities", "relations", "entity_type_relations"):
            items = value.get(key, [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError(f"{key} 必须是对象数组")
        for key, child in (("entity_types", "property_schema"), ("entities", "properties")):
            for item in value.get(key, []):
                fields = item.get(child) or []
                if not isinstance(fields, list) or any(not isinstance(field, dict) for field in fields):
                    raise ValueError(f"{child} 必须是对象数组")
        return value


class SaveRequest(DocumentRequest):
    expected_revision: str = Field(min_length=64, max_length=64)
    note: str = Field(default="工作台编辑", max_length=300)


class RdfRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5_000_000)
    format: str = "turtle"


class QueryRequest(DocumentRequest):
    query: str = Field(min_length=1, max_length=20_000)


class ValidationRequest(DocumentRequest):
    shapes: str = Field(default="", max_length=2_000_000)


def validate_document(document):
    issues = []
    types = document.get("entity_types") or []
    entities = document.get("entities") or []
    relations = document.get("relations") or []
    type_relations = document.get("entity_type_relations") or []

    def issue(code, message, node_id="", severity="error", property_name=""):
        issues.append({"code": code, "message": message, "node_id": node_id, "severity": severity, "property_name": property_name})

    for group, items in (("类型", types), ("实体", entities), ("关系", relations), ("类型关系", type_relations)):
        ids = [str(item.get("id") or "") for item in items]
        for identifier, count in Counter(ids).items():
            if not identifier or count > 1:
                issue("duplicate-id", f"{group} ID 为空或重复：{identifier or '未设置'}", identifier)
        if group in ("类型", "实体"):
            for item in items:
                if not str(item.get("name") or "").strip():
                    issue("missing-name", f"{group}名称不能为空", item.get("id", ""))
    for name, count in Counter(str(item.get("name") or "").strip() for item in types).items():
        if name and count > 1:
            resources = [item for item in types if str(item.get("name") or "").strip() == name]
            distinct_iris = all(item.get("iri") for item in resources) and len({item["iri"] for item in resources}) == len(resources)
            issue("duplicate-type", f"类型名称重复：{name}", severity="warning" if distinct_iris else "error")
    type_map = {item.get("id"): item for item in types}
    entity_map = {item.get("id"): item for item in entities}
    overlap = set(type_map) & set(entity_map)
    for identifier in overlap:
        issue("cross-layer-id", "类型与实体不能使用相同 ID", identifier)
    for item in types:
        identifier = item.get("id")
        parent = item.get("parent_entity_type_id")
        if parent and parent not in type_map:
            issue("missing-parent", f"类型“{item.get('name')}”的父类型不存在", identifier)
        visited = {identifier}
        current = parent
        while current and current in type_map:
            if current in visited:
                issue("hierarchy-cycle", f"类型“{item.get('name')}”存在循环继承", identifier)
                break
            visited.add(current)
            current = type_map[current].get("parent_entity_type_id")
    for item in entities:
        identifier = item.get("id")
        type_id = item.get("instance_of")
        if type_id not in type_map:
            issue("missing-type", f"实体“{item.get('name')}”未绑定有效类型", identifier)
            continue
        schemas, visited, current = {}, set(), type_id
        while current and current in type_map and current not in visited:
            visited.add(current)
            for field in type_map[current].get("property_schema") or []:
                schemas.setdefault(field.get("name"), field)
            current = type_map[current].get("parent_entity_type_id")
        properties = {prop.get("name"): prop for prop in item.get("properties") or []}
        for name, schema in schemas.items():
            value = (properties.get(name) or {}).get("value")
            if schema.get("required") and (value is None or value == ""):
                issue("required-property", f"实体“{item.get('name')}”缺少必填属性“{name}”", identifier, property_name=name)
            if value is not None and value != "" and schema.get("data_type") == "number":
                try:
                    float(value)
                    if isinstance(value, bool):
                        raise ValueError()
                except (ValueError, TypeError):
                    issue("datatype", f"“{item.get('name')}”的“{name}”必须为数值", identifier)
    for item in relations:
        if item.get("source_id") not in entity_map or item.get("target_id") not in entity_map:
            issue("dangling-relation", "实例关系的起点或终点不存在", item.get("id", ""))
    for item in type_relations:
        if item.get("source_entity_type_id") not in type_map or item.get("target_entity_type_id") not in type_map:
            issue("dangling-type-relation", "类型关系的起点或终点不存在", item.get("id", ""))
    if not types:
        issue("empty-schema", "尚未定义实体类型，可从添加类型或 RDF 导入开始", severity="info")
    return {"conforms": not any(item["severity"] == "error" for item in issues), "issues": issues}


def rdf_graph(document):
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import RDF, RDFS, OWL, XSD
    graph = Graph()
    ont = document.get("ontology") or {}
    base = Namespace(f"https://assessment.local/ontology/{ont.get('id', 'workspace')}#")
    graph.bind("ass", base)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    for prefix, namespace in (ont.get("namespaces") or {}).items():
        graph.bind(prefix, Namespace(namespace))
    node_map = {}
    for item in [*(document.get("entity_types") or []), *(document.get("entities") or [])]:
        node_map[item["id"]] = URIRef(item.get("iri") or str(base[item["id"]]))
    if ont.get("rdf_document") and ont.get("rdf_projection_hash") == projection_fingerprint(document):
        # Preserve exact OWL semantics while the v3 projection is unchanged.
        # Legacy CRUD edits invalidate this cache by changing its fingerprint.
        return parse_rdf(ont["rdf_document"], "turtle"), node_map
    for item in document.get("entity_types") or []:
        subject = node_map[item["id"]]
        graph.add((subject, RDF.type, OWL.Class))
        graph.add((subject, RDFS.label, Literal(item["name"], lang="zh")))
        if item.get("description"):
            graph.add((subject, RDFS.comment, Literal(item["description"])))
        parent = node_map.get(item.get("parent_entity_type_id"))
        if parent:
            graph.add((subject, RDFS.subClassOf, parent))
        for field in item.get("property_schema") or []:
            predicate = base["property_" + hashlib.sha1(field["name"].encode()).hexdigest()[:12]]
            graph.add((predicate, RDF.type, OWL.DatatypeProperty))
            graph.add((predicate, RDFS.label, Literal(field["name"], lang="zh")))
    predicates = {item["name"]: URIRef(item.get("iri") or str(base["relation_" + hashlib.sha1(item["name"].encode()).hexdigest()[:12]])) for item in ont.get("relation_types") or []}
    for name, predicate in predicates.items():
        graph.add((predicate, RDF.type, OWL.ObjectProperty))
        graph.add((predicate, RDFS.label, Literal(name, lang="zh")))
    for item in document.get("entity_type_relations") or []:
        predicate = predicates.get(item.get("relation_type"))
        if predicate:
            graph.add((predicate, RDFS.domain, node_map[item["source_entity_type_id"]]))
            graph.add((predicate, RDFS.range, node_map[item["target_entity_type_id"]]))
    for item in document.get("entities") or []:
        subject = node_map[item["id"]]
        graph.add((subject, RDF.type, OWL.NamedIndividual))
        graph.add((subject, RDFS.label, Literal(item["name"], lang="zh")))
        if item.get("instance_of") in node_map:
            graph.add((subject, RDF.type, node_map[item["instance_of"]]))
        for prop in item.get("properties") or []:
            predicate = URIRef(prop.get("iri") or str(base["property_" + hashlib.sha1(prop["name"].encode()).hexdigest()[:12]]))
            graph.add((predicate, RDFS.label, Literal(prop["name"], lang="zh")))
            value = prop.get("value")
            if value is not None:
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                datatype = URIRef(prop["rdf_datatype"]) if prop.get("rdf_datatype") else (XSD.decimal if prop.get("data_type") == "number" else None)
                language = prop.get("rdf_language") or None
                graph.add((subject, predicate, Literal(value, datatype=None if language else datatype, lang=language, normalize=False)))
    for item in document.get("relations") or []:
        name = item.get("relation_type") or "关联"
        predicate = predicates.get(name) or base["relation_" + hashlib.sha1(name.encode()).hexdigest()[:12]]
        if item.get("source_id") in node_map and item.get("target_id") in node_map:
            graph.add((node_map[item["source_id"]], predicate, node_map[item["target_id"]]))
            graph.add((predicate, RDFS.label, Literal(name, lang="zh")))
    if ont.get("rdf_extensions"):
        extra = parse_rdf(ont["rdf_extensions"], "turtle")
        removed = {URIRef(iri) for iri in ont.get("rdf_extension_nodes") or []} - set(node_map.values())
        for subject, predicate, obj in extra:
            if subject not in removed and obj not in removed:
                graph.add((subject, predicate, obj))
    return graph, node_map


def parse_rdf(content, format_name):
    from rdflib import Graph
    formats = {"ttl": "turtle", "turtle": "turtle", "rdf": "xml", "owl": "xml", "xml": "xml", "nt": "nt", "jsonld": "json-ld", "json-ld": "json-ld"}
    if format_name not in formats:
        raise HTTPException(400, "支持 Turtle、RDF/XML、OWL、N-Triples、JSON-LD")
    if re.search(r"<!DOCTYPE|<!ENTITY", content, re.I):
        raise HTTPException(400, "RDF/XML 不允许外部实体或 DTD")
    if formats[format_name] == "json-ld":
        def check_context(value):
            if isinstance(value, dict):
                context = value.get("@context")
                if isinstance(context, str) or (isinstance(context, list) and any(isinstance(item, str) for item in context)) or "@import" in value:
                    raise HTTPException(400, "JSON-LD 请使用内联 @context，不自动请求远程上下文")
                for child in value.values():
                    check_context(child)
            elif isinstance(value, list):
                for child in value:
                    check_context(child)
        try:
            check_context(json.loads(content))
        except json.JSONDecodeError as error:
            raise HTTPException(400, f"JSON-LD 解析失败：{str(error)[:250]}") from error
    try:
        graph = Graph().parse(data=content, format=formats[format_name])
    except Exception as error:
        raise HTTPException(400, f"RDF 解析失败：{str(error)[:250]}") from error
    if len(graph) > 50000:
        raise HTTPException(400, "单次导入最多 50000 个三元组")
    return graph


def rdf_to_document(graph, ontology):
    from rdflib import URIRef, Literal
    from rdflib.namespace import RDF, RDFS, OWL
    now = datetime.now().isoformat()

    def identifier(prefix, iri):
        return prefix + hashlib.sha256(str(iri).encode()).hexdigest()[:16]

    def label(iri):
        labels = list(graph.objects(iri, RDFS.label))
        preferred = next((value for value in labels if value.language in ("zh", "zh-cn", "zh-CN")), None)
        return str(preferred or (labels[0] if labels else str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]))

    class_iris = set(graph.subjects(RDF.type, OWL.Class)) | set(graph.subjects(RDF.type, RDFS.Class))
    class_iris |= {kind for kind in graph.objects(None, RDF.type) if isinstance(kind, URIRef) and not str(kind).startswith((str(RDF), str(RDFS), str(OWL), "http://www.w3.org/ns/shacl#"))}
    class_iris |= {s for s, o in graph.subject_objects(RDFS.subClassOf) if isinstance(s, URIRef)}
    class_iris |= {o for s, o in graph.subject_objects(RDFS.subClassOf) if isinstance(o, URIRef)}
    class_iris = {iri for iri in class_iris if isinstance(iri, URIRef)}
    type_map = {iri: identifier("et_", iri) for iri in class_iris}
    types = []
    warnings = []
    for iri in sorted(class_iris, key=str):
        parents = sorted((parent for parent in graph.objects(iri, RDFS.subClassOf) if parent in type_map), key=str)
        if len(parents) > 1:
            warnings.append(f"{label(iri)} 有多个父类；类型树显示首个父类，其余继承作为 RDF 扩展保留并参与推理")
        types.append({"id": type_map[iri], "iri": str(iri), "ontology_id": ontology["id"], "name": label(iri), "description": str(next(graph.objects(iri, RDFS.comment), "")), "color": "#4f7cff", "property_schema": [], "parent_entity_type_id": type_map.get(parents[0]) if parents else None, "create_time": now, "update_time": now})
    individuals = {subject for subject, kind in graph.subject_objects(RDF.type) if kind in class_iris or kind == OWL.NamedIndividual}
    declared_properties = set(graph.subjects(RDF.type, OWL.ObjectProperty)) | set(graph.subjects(RDF.type, OWL.DatatypeProperty)) | set(graph.predicates())
    ontology_subjects = set(graph.subjects(RDF.type, OWL.Ontology))
    individuals |= {subject for subject in graph.subjects() if isinstance(subject, URIRef) and subject not in class_iris and subject not in declared_properties and subject not in ontology_subjects and not str(subject).startswith((str(RDF), str(RDFS), str(OWL), "http://www.w3.org/ns/shacl#"))}
    individuals = {iri for iri in individuals if isinstance(iri, URIRef) and iri not in class_iris}
    untyped = {iri for iri in individuals if not any(kind in type_map for kind in graph.objects(iri, RDF.type))}
    if untyped:
        type_map[RDFS.Resource] = identifier("et_", RDFS.Resource)
        class_iris.add(RDFS.Resource)
        types.append({"id": type_map[RDFS.Resource], "iri": str(RDFS.Resource), "ontology_id": ontology["id"], "name": "RDF 资源", "description": "原始 RDF 中未声明具体类型的资源", "color": "#8a9ab2", "property_schema": [], "create_time": now, "update_time": now})
    entity_map = {iri: identifier("ent_", iri) for iri in individuals}
    entities = []
    for iri in sorted(individuals, key=str):
        kind = next((value for value in graph.objects(iri, RDF.type) if value in type_map), RDFS.Resource if iri in untyped else None)
        properties = []
        for predicate, value in graph.predicate_objects(iri):
            if isinstance(value, Literal) and predicate not in (RDFS.label, RDFS.comment):
                properties.append({"id": identifier("prop_", str(iri) + str(predicate)), "iri": str(predicate), "rdf_datatype": str(value.datatype or ""), "rdf_language": value.language or "", "entity_id": entity_map[iri], "name": label(predicate), "value": str(value), "data_type": "number" if re.search(r"#(integer|decimal|double|float|int|long|short)$", str(value.datatype or "")) else "string", "create_time": now, "update_time": now})
        entities.append({"id": entity_map[iri], "iri": str(iri), "ontology_id": ontology["id"], "name": label(iri), "instance_of": type_map.get(kind, ""), "properties": properties, "create_time": now, "update_time": now})
    relation_types = []
    type_relations, relations = [], []
    predicates = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    predicates |= {predicate for subject, predicate, obj in graph if subject in entity_map and obj in entity_map}
    for predicate in sorted(predicates, key=str):
        name = label(predicate)
        relation_types.append({"name": name, "iri": str(predicate), "description": str(next(graph.objects(predicate, RDFS.comment), ""))})
        for source in graph.objects(predicate, RDFS.domain):
            for target in graph.objects(predicate, RDFS.range):
                if source in type_map and target in type_map:
                    type_relations.append({"id": identifier("etr_", str(source) + str(predicate) + str(target)), "ontology_id": ontology["id"], "source_entity_type_id": type_map[source], "target_entity_type_id": type_map[target], "relation_type": name, "create_time": now, "update_time": now})
        for source, target in graph.subject_objects(predicate):
            if source in entity_map and target in entity_map:
                relations.append({"id": identifier("rel_", str(source) + str(predicate) + str(target)), "ontology_id": ontology["id"], "source_id": entity_map[source], "target_id": entity_map[target], "relation_type": name, "create_time": now, "update_time": now})
    blank_triples = sum(not isinstance(subject, URIRef) or (not isinstance(obj, (URIRef, Literal))) for subject, _, obj in graph)
    if blank_triples:
        warnings.append(f"包含匿名节点的 {blank_triples} 个三元组作为 RDF 扩展完整保留；表单不直接编辑复杂 OWL 限制")
    result = {"ontology": {**ontology, "rdf_document": "", "rdf_dataset": "", "rdf_projection_hash": "", "rdf_extensions": "", "rdf_extension_nodes": [], "relation_types": relation_types, "namespaces": {str(prefix): str(namespace) for prefix, namespace in graph.namespaces()}}, "entity_types": types, "entity_type_relations": type_relations, "entities": entities, "relations": relations}
    represented, _ = rdf_graph(result)
    from rdflib import Graph
    extra = Graph()
    for triple in graph:
        if triple not in represented:
            extra.add(triple)
    result["ontology"]["rdf_extensions"] = extra.serialize(format="turtle") if len(extra) else ""
    result["ontology"]["rdf_extension_nodes"] = [str(iri) for iri in [*class_iris, *individuals]]
    return result, warnings


def history_path(ontology_id):
    return Path(host().USER_ONTOLOGIES_DIR) / "revisions" / f"{ontology_id}.json"


@router.get("/{ontology_id}/workbench")
async def get_workbench(ontology_id: str):
    return {"success": True, "data": snapshot(ontology_id)}


@router.put("/{ontology_id}/workbench")
async def save_workbench(ontology_id: str, request: SaveRequest):
    return await persist_document(ontology_id, request)


async def persist_document(ontology_id: str, request: SaveRequest, *, rdf_mode=False):
    service = host()
    result = validate_document(request.document)
    async with service.db_lock:
        previous = snapshot(ontology_id)
        if previous["revision"] != request.expected_revision:
            raise HTTPException(409, "本体已被其他操作更新，请重新载入后合并修改")
        # Existing incomplete business facts remain visible without preventing
        # unrelated edits. New missing required values are still rejected.
        baseline = validate_document(previous["document"])
        legacy = {(issue["node_id"], issue["property_name"]) for issue in baseline["issues"] if issue["code"] == "required-property"}
        blocking = [issue for issue in result["issues"] if issue["severity"] == "error" and not (issue["code"] == "required-property" and (rdf_mode or (issue["node_id"], issue["property_name"]) in legacy))]
        if blocking:
            raise HTTPException(422, {"message": "本体校验未通过", "issues": blocking})
        document = copy.deepcopy(request.document)
        document["ontology"]["id"] = ontology_id
        document["ontology"]["entity_types"] = document.get("entity_types") or []
        try:
            ontology = OntologyModel.model_validate(document["ontology"])
            typed_types = [EntityType.model_validate({**value, "ontology_id": ontology_id}) for value in document.get("entity_types") or []]
            typed_type_relations = [EntityTypeRelation.model_validate({**value, "ontology_id": ontology_id}) for value in document.get("entity_type_relations") or []]
            typed_entities = [Entity.model_validate({**value, "ontology_id": ontology_id}) for value in document.get("entities") or []]
            typed_relations = [Relation.model_validate({**value, "ontology_id": ontology_id}) for value in document.get("relations") or []]
        except Exception as error:
            raise HTTPException(422, f"本体结构不完整：{str(error)[:300]}") from error
        # Make the recoverable previous snapshot durable before changing the model.
        path = history_path(ontology_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path) + ".lock"):
            history = service.load_json_with_backup(str(path), [])
            history.append({"id": f"revision_{uuid.uuid4().hex[:12]}", "time": datetime.now().isoformat(), "note": request.note, "revision": previous["revision"], "new_revision": "", "status": "prepared", "document": previous["document"]})
            history = history[-50:]
            service.atomic_write_json(str(path), history)
        service.ontologies_db[ontology_id] = ontology
        service.entity_types_db[ontology_id] = typed_types
        service.entity_type_relations_db[ontology_id] = typed_type_relations
        service.entities_db[ontology_id] = typed_entities
        service.relations_db[ontology_id] = typed_relations
        if rdf_mode:
            ontology.rdf_projection_hash = projection_fingerprint(snapshot(ontology_id)["document"])
        try:
            service.save_ontology(ontology_id)
            service.save_index()
        except Exception:
            # The journal already contains the recovery snapshot. Restore the
            # live model and attempt to repair any partially written files.
            old = previous["document"]
            service.ontologies_db[ontology_id] = OntologyModel.model_validate(old["ontology"])
            service.entity_types_db[ontology_id] = [EntityType.model_validate(value) for value in old["entity_types"]]
            service.entity_type_relations_db[ontology_id] = [EntityTypeRelation.model_validate(value) for value in old["entity_type_relations"]]
            service.entities_db[ontology_id] = [Entity.model_validate(value) for value in old["entities"]]
            service.relations_db[ontology_id] = [Relation.model_validate(value) for value in old["relations"]]
            try:
                service.save_ontology(ontology_id)
                service.save_index()
            except Exception:
                logging.getLogger("ontology-service").error("本体回滚文件写入失败，可从版本记录恢复保存前快照", exc_info=True)
            raise
        current = snapshot(ontology_id)
        history[-1].update({"new_revision": current["revision"], "status": "committed"})
        try:
            with FileLock(str(path) + ".lock"):
                service.atomic_write_json(str(path), history)
        except OSError:
            logging.getLogger("ontology-service").warning("本体已保存，历史记录状态更新失败；保存前快照仍保留", exc_info=True)
        warnings = [issue for issue in result["issues"] if issue["severity"] == "error"]
        return {"success": True, "message": "本体已保存，变更记录已归档", "data": {**current, "legacy_validation_warnings": warnings}}


@router.get("/{ontology_id}/workbench/history")
async def get_history(ontology_id: str):
    host()._get_ontology_or_404(ontology_id)
    items = host().load_json_with_backup(str(history_path(ontology_id)), [])
    return {"success": True, "items": list(reversed(items))}


@router.post("/{ontology_id}/workbench/validate")
def validate_workbench(ontology_id: str, request: ValidationRequest):
    host()._get_ontology_or_404(ontology_id)
    result = validate_document(request.document)
    if request.shapes and result["conforms"]:
        from pyshacl import validate
        from rdflib.namespace import SH
        graph, _ = rdf_graph(request.document)
        shapes = parse_rdf(request.shapes, "turtle")
        conforms, report, _ = validate(graph, shacl_graph=shapes, inference="none", advanced=False, js=False, do_owl_imports=False)
        for node in report.subjects(None, SH.ValidationResult):
            result["issues"].append({"severity": "error", "code": "shacl", "node_id": str(next(report.objects(node, SH.focusNode), "")), "message": str(next(report.objects(node, SH.resultMessage), "SHACL 约束未通过")), "path": str(next(report.objects(node, SH.resultPath), ""))})
        result["conforms"] = result["conforms"] and conforms
    return {"success": True, "data": result}


@router.post("/{ontology_id}/workbench/reason")
def reason_workbench(ontology_id: str, request: DocumentRequest):
    host()._get_ontology_or_404(ontology_id)
    validation = validate_document(request.document)
    if any(issue["severity"] == "error" and issue["code"] != "required-property" for issue in validation["issues"]):
        raise HTTPException(422, "请先修复本体结构中的错误再推理")
    from rdflib import URIRef
    from rdflib.namespace import RDF, RDFS
    from owlrl import DeductiveClosure, OWLRL_Semantics
    graph, mapping = rdf_graph(request.document)
    asserted = set(graph)
    if len(asserted) > 15000:
        raise HTTPException(400, "交互推理最多支持 15000 个断言三元组，请筛选数据后执行")
    DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False).expand(graph)
    reverse = {iri: identifier for identifier, iri in mapping.items()}
    types = {value["id"]: value for value in request.document.get("entity_types") or []}
    inferences = []
    for subject, predicate, obj in sorted(set(graph) - asserted, key=lambda triple: tuple(map(str, triple))):
        if subject not in reverse or obj not in reverse or subject == obj:
            continue
        source_id, target_id = reverse[subject], reverse[obj]
        if predicate == RDF.type:
            relation = "继承类型"
            rule = "rdfs9：实例继承父类型"
        elif predicate == RDFS.subClassOf:
            relation = "间接继承"
            rule = "scm-sco：子类传递性"
        else:
            relation = str(next(graph.objects(predicate, RDFS.label), str(predicate).rsplit("#", 1)[-1]))
            rule = "OWL-RL 规则闭包"
        inferences.append({"id": "inf_" + hashlib.sha1(f"{subject}|{predicate}|{obj}".encode()).hexdigest()[:16], "source": source_id, "target": target_id, "relation": relation, "predicate": str(predicate), "rule": rule, "inferred": True})
    from owlrl.Namespaces import ERRNS
    diagnostics = [str(message) for message in graph.objects(None, ERRNS.error)]
    missing = sum(issue["code"] == "required-property" for issue in validation["issues"])
    if missing:
        diagnostics.insert(0, f"业务模型有 {missing} 项必填属性缺失；推理仅依据已知事实，不代表业务数据完整。")
    return {"success": True, "data": {"engine": "OWL-RL", "asserted_triples": len(asserted), "closure_triples": len(graph), "inferences": inferences[:3000], "diagnostics": diagnostics, "truncated": len(inferences) > 3000, "persisted": False}}


@router.post("/{ontology_id}/workbench/import-rdf")
def import_rdf(ontology_id: str, request: RdfRequest):
    current = snapshot(ontology_id)
    graph = parse_rdf(request.content, request.format)
    document, warnings = rdf_to_document(graph, current["document"]["ontology"])
    return {"success": True, "data": {"document": document, "revision": current["revision"], "triple_count": len(graph), "warnings": warnings, "validation": validate_document(document)}}


@router.get("/{ontology_id}/workbench/export-rdf")
def export_rdf(ontology_id: str, format: str = "turtle"):
    formats = {"turtle": "text/turtle", "xml": "application/rdf+xml", "json-ld": "application/ld+json", "nt": "application/n-triples"}
    if format not in formats:
        raise HTTPException(400, "不支持的导出格式")
    graph, _ = rdf_graph(snapshot(ontology_id)["document"])
    return Response(graph.serialize(format=format), media_type=formats[format])


@router.post("/{ontology_id}/workbench/query")
def query_workbench(ontology_id: str, request: QueryRequest):
    host()._get_ontology_or_404(ontology_id)
    query = re.sub(r"(?m)^\s*#.*$", "", request.query).strip()
    if re.search(r"\b(SERVICE|FROM|LOAD|INSERT|DELETE|CLEAR|DROP|CREATE|MOVE|COPY|ADD)\b", query, re.I) or not re.search(r"\b(SELECT|ASK)\b", query, re.I):
        raise HTTPException(400, "工作台仅支持本地 SELECT / ASK，不执行远程查询或修改语句")
    graph, _ = rdf_graph(request.document)
    try:
        result = graph.query(query)
        if result.type == "ASK":
            return {"success": True, "data": {"boolean": bool(result), "columns": [], "rows": []}}
        columns = [str(variable) for variable in result.vars]
        rows = []
        for index, row in enumerate(result):
            if index >= 200:
                break
            rows.append({key: str(value) if value is not None else "" for key, value in zip(columns, row)})
        return {"success": True, "data": {"columns": columns, "rows": rows, "limit": 200}}
    except Exception as error:
        raise HTTPException(400, f"SPARQL 查询失败：{str(error)[:250]}") from error
