import asyncio
import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from models import Entity, EntityType, OntologyModel, PropertySchema
import workbench


def document():
    now = datetime.now().isoformat()
    types = [
        {"id": "a", "name": "评估对象", "ontology_id": "ont_test", "create_time": now, "update_time": now},
        {"id": "b", "name": "评估体系", "ontology_id": "ont_test", "parent_entity_type_id": "a", "create_time": now, "update_time": now},
        {"id": "c", "name": "效能评估体系", "ontology_id": "ont_test", "parent_entity_type_id": "b", "create_time": now, "update_time": now},
    ]
    entities = [{"id": "e1", "ontology_id": "ont_test", "name": "测试体系", "instance_of": "c", "properties": [], "create_time": now, "update_time": now}]
    return {"ontology": {"id": "ont_test", "name": "工作台测试", "entity_types": types, "relation_types": [], "create_time": now, "update_time": now}, "entity_types": types, "entities": entities, "entity_type_relations": [], "relations": []}


class WorkbenchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        initial = document()
        ont = OntologyModel.model_validate(initial["ontology"])
        self.service = SimpleNamespace(
            USER_ONTOLOGIES_DIR=self.temp.name,
            ontologies_db={"ont_test": ont},
            entity_types_db={"ont_test": [EntityType.model_validate(value) for value in initial["entity_types"]]},
            entities_db={"ont_test": [Entity.model_validate(value) for value in initial["entities"]]},
            entity_type_relations_db={"ont_test": []}, relations_db={"ont_test": []},
            db_lock=asyncio.Lock(), save_index=lambda: None,
        )
        self.service._get_ontology_or_404 = lambda identifier: self.service.ontologies_db[identifier]
        self.service.save_ontology = lambda identifier: setattr(self.service.ontologies_db[identifier], "update_time", datetime.now())
        self.service.load_json_with_backup = lambda path, default: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default
        self.service.atomic_write_json = lambda path, data: Path(path).write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        self.patch = patch.object(workbench, "host", return_value=self.service)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_cycle_and_required_numeric_property_are_reported(self):
        value = document()
        value["entity_types"][0]["parent_entity_type_id"] = "c"
        value["entity_types"][2]["property_schema"] = [{"name": "评分", "required": True, "data_type": "number"}]
        result = workbench.validate_document(value)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertFalse(result["conforms"])
        self.assertIn("hierarchy-cycle", codes)
        self.assertIn("required-property", codes)

    async def test_owlrl_infers_transitive_types_without_persisting(self):
        result = await asyncio.to_thread(workbench.reason_workbench, "ont_test", workbench.DocumentRequest(document=document()))
        inferences = result["data"]["inferences"]
        self.assertTrue(any(item["source"] == "e1" and item["target"] == "a" for item in inferences))
        self.assertTrue(any(item["source"] == "c" and item["target"] == "a" for item in inferences))
        self.assertFalse(result["data"]["persisted"])
        self.assertEqual(self.service.entities_db["ont_test"][0].instance_of, "c")

    async def test_save_rejects_stale_revision_and_records_previous_snapshot(self):
        current = workbench.snapshot("ont_test")
        updated = copy.deepcopy(current["document"])
        updated["entities"][0]["name"] = "已修改体系"
        request = workbench.SaveRequest(document=updated, expected_revision=current["revision"], note="更新名称")
        result = await workbench.save_workbench("ont_test", request)
        self.assertNotEqual(result["data"]["revision"], current["revision"])
        history = await workbench.get_history("ont_test")
        self.assertEqual(history["items"][0]["document"]["entities"][0]["name"], "测试体系")
        with self.assertRaises(HTTPException) as context:
            await workbench.save_workbench("ont_test", request)
        self.assertEqual(context.exception.status_code, 409)

    def test_rdf_roundtrip_preserves_class_and_individual_iris(self):
        content = '''@prefix ex: <https://example.org/test#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Indicator a owl:Class ; rdfs:label "指标"@zh .
ex:Metric a owl:Class ; rdfs:subClassOf ex:Indicator ; rdfs:label "效能指标"@zh .
ex:score a ex:Metric ; rdfs:label "任务完成率"@zh .'''
        graph = workbench.parse_rdf(content, "turtle")
        converted, warnings = workbench.rdf_to_document(graph, document()["ontology"])
        exported, mapping = workbench.rdf_graph(converted)
        self.assertEqual(len(converted["entity_types"]), 2)
        self.assertEqual(len(converted["entities"]), 1)
        self.assertEqual(converted["entities"][0]["iri"], "https://example.org/test#score")
        self.assertFalse(warnings)
        self.assertGreater(len(exported), 0)

    async def test_shacl_focus_node_is_reported(self):
        shapes = '''@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ass: <https://assessment.local/ontology/ont_test#> .
@prefix ex: <https://example.org/> .
ex:Check a sh:NodeShape ; sh:targetClass ass:c ;
sh:property [ sh:path ex:missing ; sh:minCount 1 ; sh:message "缺少约束属性" ] .'''
        result = await asyncio.to_thread(workbench.validate_workbench, "ont_test", workbench.ValidationRequest(document=document(), shapes=shapes))
        self.assertFalse(result["data"]["conforms"])
        self.assertTrue(any("缺少约束属性" in issue["message"] for issue in result["data"]["issues"]))

    async def test_remote_sparql_and_external_jsonld_context_are_rejected(self):
        with self.assertRaises(HTTPException):
            workbench.query_workbench("ont_test", workbench.QueryRequest(document=document(), query="SELECT * WHERE { SERVICE <https://example.org/sparql> {?s ?p ?o} }"))
        with self.assertRaises(HTTPException):
            workbench.parse_rdf('{"@context":"https://example.org/context","@id":"x"}', "json-ld")

    async def test_rdf_semantic_extensions_survive_import_and_drive_inference(self):
        content = '''@prefix ex: <https://example.org/test#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Indicator a owl:Class .
ex:related a owl:ObjectProperty, owl:SymmetricProperty .
ex:left a ex:Indicator ; ex:related ex:right .
ex:right a ex:Indicator .'''
        graph = workbench.parse_rdf(content, "turtle")
        converted, warnings = workbench.rdf_to_document(graph, document()["ontology"])
        self.assertIn("SymmetricProperty", converted["ontology"]["rdf_extensions"])
        reexported, _ = workbench.rdf_graph(converted)
        from rdflib.namespace import RDF, OWL
        from rdflib import URIRef
        self.assertIn((URIRef("https://example.org/test#related"), RDF.type, OWL.SymmetricProperty), reexported)
        result = await asyncio.to_thread(workbench.reason_workbench, "ont_test", workbench.DocumentRequest(document=converted))
        left = next(value["id"] for value in converted["entities"] if value["iri"].endswith("#left"))
        right = next(value["id"] for value in converted["entities"] if value["iri"].endswith("#right"))
        self.assertTrue(any(value["source"] == right and value["target"] == left for value in result["data"]["inferences"]))

    def test_untyped_rdf_resources_get_a_visible_resource_type(self):
        graph = workbench.parse_rdf('@prefix ex: <https://example.org/> . ex:item ex:score "88" .', "turtle")
        converted, _ = workbench.rdf_to_document(graph, document()["ontology"])
        self.assertEqual(len(converted["entities"]), 1)
        self.assertTrue(workbench.validate_document(converted)["conforms"])

    async def test_history_write_failure_does_not_change_live_model(self):
        current = workbench.snapshot("ont_test")
        updated = copy.deepcopy(current["document"])
        updated["entities"][0]["name"] = "不应保存的名称"
        with patch.object(self.service, "atomic_write_json", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                await workbench.save_workbench("ont_test", workbench.SaveRequest(document=updated, expected_revision=current["revision"]))
        self.assertEqual(self.service.entities_db["ont_test"][0].name, "测试体系")

    def test_malformed_document_and_jsonld_are_rejected(self):
        from pydantic import ValidationError
        value = document()
        value["entities"] = "not-an-array"
        with self.assertRaises(ValidationError):
            workbench.DocumentRequest(document=value)
        with self.assertRaises(HTTPException) as context:
            workbench.parse_rdf('{"@context":', "json-ld")
        self.assertEqual(context.exception.status_code, 400)

    async def test_persistence_failure_restores_previous_model(self):
        current = workbench.snapshot("ont_test")
        updated = copy.deepcopy(current["document"])
        updated["entities"][0]["name"] = "不应生效的名称"
        with patch.object(self.service, "save_index", side_effect=[OSError("index failure"), None]):
            with self.assertRaises(OSError):
                await workbench.save_workbench("ont_test", workbench.SaveRequest(document=updated, expected_revision=current["revision"]))
        self.assertEqual(self.service.entities_db["ont_test"][0].name, "测试体系")

    async def test_legacy_missing_values_do_not_block_unrelated_edits(self):
        self.service.entity_types_db["ont_test"][2].property_schema = [PropertySchema(name="评分", required=True, data_type="number")]
        current = workbench.snapshot("ont_test")
        updated = copy.deepcopy(current["document"])
        updated["entities"][0]["name"] = "重命名体系"
        saved = await workbench.save_workbench("ont_test", workbench.SaveRequest(document=updated, expected_revision=current["revision"]))
        self.assertEqual(len(saved["data"]["legacy_validation_warnings"]), 1)
        self.assertEqual(self.service.entities_db["ont_test"][0].name, "重命名体系")
        reasoned = workbench.reason_workbench("ont_test", workbench.DocumentRequest(document=saved["data"]["document"]))
        self.assertTrue(any("必填属性缺失" in message for message in reasoned["data"]["diagnostics"]))

    async def test_new_missing_required_value_cannot_be_saved(self):
        current = workbench.snapshot("ont_test")
        updated = copy.deepcopy(current["document"])
        updated["entity_types"][2]["property_schema"] = [{"name": "评分", "required": True, "data_type": "number"}]
        with self.assertRaises(HTTPException) as context:
            await workbench.save_workbench("ont_test", workbench.SaveRequest(document=updated, expected_revision=current["revision"]))
        self.assertEqual(context.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
