"""Exercise authoritative RDF persistence and the four-turn equipment example."""
import copy
import unittest
from rdflib import Dataset, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS, OWL, XSD
from fastapi import HTTPException
import workbench as wb
import ontosphere_editor as editor
from examples.wargame import make_graph, demo_payload, DEMO_ID, DEMO_NAME, LEGACY_LABELS, LEGACY_NAME, S, E, U, M, V, A, SHAPES


class EditorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from test_workbench import WorkbenchTests
        WorkbenchTests.setUp(self)

    def tearDown(self):
        from test_workbench import WorkbenchTests
        WorkbenchTests.tearDown(self)

    async def test_demo_creation_is_idempotent_and_keeps_exact_owl(self):
        first = (await editor.ensure_wargame())["data"]
        second = (await editor.ensure_wargame())["data"]
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["revision"], second["revision"])
        graph = wb.parse_rdf(first["turtle"], "turtle")
        self.assertTrue(isomorphic(graph, make_graph(0)))
        self.assertEqual(first["entities"], 20)
        self.assertEqual(first["types"], 14)

    async def test_legacy_demo_labels_are_updated_in_canvas_and_stored_nodes(self):
        baseline = (await editor.ensure_wargame())["data"]
        self.service.ontologies_db[DEMO_ID].name = LEGACY_NAME
        before = wb.snapshot(DEMO_ID)
        graph = make_graph(2)
        expected_note = graph.value(V.E0, S.note)
        graph.set((E.R01, RDFS.label, Literal(LEGACY_LABELS[E.R01], lang="zh")))
        graph.set((E.R02, RDFS.label, Literal(LEGACY_LABELS[E.R02] + "〔已核验〕", lang="zh")))
        graph.set((E.G01, RDFS.label, Literal("青岚 自定义设备名称", lang="zh")))
        graph.set((V.E0, S.note, Literal("建立装备、指挥关系与任务基线。")))
        dataset = Dataset()
        data_iri = URIRef("urn:vg:data")
        for triple in graph:
            dataset.graph(data_iri).add(triple)
        other_iri = URIRef("urn:vg:provenance")
        provenance = (E.R01, RDFS.comment, Literal("保留命名图"))
        dataset.graph(other_iri).add(provenance)
        request = editor.EditorSave(dataset=dataset.serialize(format="nquads"), expected_revision=before["revision"], layouts={"host": {"turn": 2}})
        historical = copy.deepcopy(before["document"])
        historical["ontology"].update({"rdf_document": make_graph(2).serialize(format="turtle"), "rdf_dataset": request.dataset,
                                       "canvas_layouts": request.layouts})
        historical["ontology"]["rdf_projection_hash"] = wb.projection_fingerprint(historical)
        preview = (await editor.preview_revision(DEMO_ID, wb.DocumentRequest(document=historical)))["data"]
        self.assertEqual(preview["layouts"], request.layouts)
        self.assertNotIn("青岚", preview["dataset"])
        self.assertIn(LEGACY_LABELS[E.R01], historical["ontology"]["rdf_dataset"])
        self.assertEqual(wb.snapshot(DEMO_ID), before)

        saved = (await editor.save_editor(DEMO_ID, request))["data"]
        stored = wb.snapshot(DEMO_ID)
        self.assertNotEqual(saved["revision"], baseline["revision"])
        self.assertEqual(saved["name"], DEMO_NAME)
        self.assertEqual(saved["layouts"], request.layouts)
        normalized = Dataset().parse(data=saved["dataset"], format="nquads")
        self.assertIn(provenance, normalized.graph(other_iri))
        for updated in (normalized.graph(data_iri), wb.parse_rdf(saved["turtle"], "turtle")):
            self.assertEqual(updated.value(E.R01, RDFS.label), Literal("R-01 观测平台", lang="zh"))
            self.assertEqual(updated.value(E.R02, RDFS.label), Literal("R-02 观测平台〔已核验〕", lang="zh"))
            self.assertEqual(updated.value(E.G01, RDFS.label), Literal("自定义设备名称", lang="zh"))
            self.assertEqual(updated.value(V.E0, S.note), expected_note)
        self.assertNotIn("青岚", stored["document"]["ontology"]["rdf_dataset"])
        self.assertNotIn("青岚", stored["document"]["ontology"]["rdf_document"])
        stored_names = {entity["iri"]: entity["name"] for entity in stored["document"]["entities"]}
        self.assertEqual(stored_names[str(E.R02)], "R-02 观测平台〔已核验〕")
        self.assertEqual(stored_names[str(E.G01)], "自定义设备名称")

    async def test_dataset_roundtrip_excludes_inferences_from_asserted_owl(self):
        await editor.ensure_wargame()
        baseline = editor.editor_payload(DEMO_ID)
        dataset = Dataset()
        graph = dataset.graph(URIRef("urn:vg:data"))
        for triple in make_graph(1): graph.add(triple)
        dataset.graph(URIRef("urn:vg:inferred")).add((E.R01, RDF.type, S.ReadyPlatform))
        dataset.graph(URIRef("urn:vg:shapes")).parse(data=SHAPES, format="turtle")
        dataset.graph(URIRef("urn:vg:provenance")).add((E.R01, RDFS.comment, Literal("audit")))
        layouts = {"abox": {"layoutData": {"elements": []}}, "host": {"turn": 1}}
        request = editor.EditorSave(dataset=dataset.serialize(format="nquads"), expected_revision=baseline["revision"], layouts=layouts)
        response = (await editor.save_editor(DEMO_ID, request))["data"]
        asserted, _ = wb.rdf_graph(wb.snapshot(DEMO_ID)["document"])
        self.assertTrue(isomorphic(asserted, make_graph(1)))
        self.assertNotIn((E.R01, RDF.type, S.ReadyPlatform), asserted)
        self.assertEqual(response["layouts"], layouts)
        self.assertIn("urn:vg:shapes", response["dataset"])
        self.assertNotEqual(response["revision"], baseline["revision"])
        with self.assertRaises(HTTPException) as conflict:
            await editor.save_editor(DEMO_ID, request)
        self.assertEqual(conflict.exception.status_code, 409)
        history = (await wb.get_history(DEMO_ID))["items"]
        preview = (await editor.preview_revision(DEMO_ID, wb.DocumentRequest(document=history[-1]["document"])))["data"]
        self.assertTrue(isomorphic(wb.parse_rdf(preview["turtle"], "turtle"), make_graph(0)))

    async def test_legacy_edit_invalidates_cached_dataset_and_preserves_ids(self):
        before = wb.snapshot("ont_test")
        graph, _ = wb.rdf_graph(before["document"])
        await editor.save_editor("ont_test", editor.EditorSave(turtle=graph.serialize(format="turtle"), expected_revision=before["revision"]))
        snapshot = wb.snapshot("ont_test")
        self.assertEqual({x["id"] for x in snapshot["document"]["entities"]}, {"e1"})
        self.assertEqual({x["id"] for x in snapshot["document"]["entity_types"]}, {"a", "b", "c"})
        changed = copy.deepcopy(snapshot["document"])
        changed["entities"][0]["name"] = "旧服务修改名称"
        await wb.save_workbench("ont_test", wb.SaveRequest(document=changed, expected_revision=snapshot["revision"]))
        packed = editor.editor_payload("ont_test")
        self.assertIn("旧服务修改名称", packed["turtle"])
        self.assertEqual(packed["dataset"], "")

    async def test_rdf_save_preserves_legacy_property_binding_history_and_identifier(self):
        from models import Property
        from datetime import datetime
        prop = Property(id="prop_bound", entity_id="e1", name="得分", value="81", bindings={"field": "score"}, history=[{"value": "75"}], create_time=datetime.now(), update_time=datetime.now())
        self.service.entities_db["ont_test"][0].properties = [prop]
        before = wb.snapshot("ont_test")
        graph, _ = wb.rdf_graph(before["document"])
        await editor.save_editor("ont_test", editor.EditorSave(turtle=graph.serialize(format="turtle"), expected_revision=before["revision"]))
        saved = self.service.entities_db["ont_test"][0].properties[0]
        self.assertEqual(saved.id, "prop_bound")
        self.assertEqual(saved.entity_id, "e1")
        self.assertEqual(saved.bindings, {"field": "score"})
        self.assertEqual(saved.history[0].value, "75")

    def test_relation_definitions_participate_in_projection_cache_invalidation(self):
        before = wb.snapshot("ont_test")["document"]
        after = copy.deepcopy(before)
        after["ontology"]["relation_types"] = [{"name": "新关系", "iri": "urn:newRelation"}]
        self.assertNotEqual(wb.projection_fingerprint(before), wb.projection_fingerprint(after))

    def test_turns_have_correct_states_progress_and_event_provenance(self):
        from pyshacl import validate
        counts = []
        for turn in range(4):
            graph = make_graph(turn)
            payload = demo_payload(turn)
            counts.append(len(graph))
            self.assertIn((M.Observe, S.progress, Literal(payload["turns"][turn]["progress"], datatype=XSD.integer)), graph)
            self.assertIn((A.Readiness, S.derivedFrom, V[f"E{turn}"]), graph)
            self.assertEqual(validate(graph, shacl_graph=SHAPES, inference="rdfs")[0], True)
            self.assertEqual(len(list(graph.subjects(S.status, Literal("链路降级")))), 2 if turn == 1 else 0)
        self.assertEqual(counts, sorted(counts))


if __name__ == "__main__": unittest.main()
