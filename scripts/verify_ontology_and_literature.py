"""Read-only acceptance check against the running ontology and knowledge services."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import sys
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, data=None):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=120) as response:
        raw = response.read()
        return json.loads(raw) if "json" in response.headers.get("Content-Type", "") else raw


def main():
    corpus = ROOT / "python/knowledge-service/data/literature-1000"
    papers = [json.loads(line) for line in (corpus / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(papers) == 1000
    assert sum(paper["language"] == "zh" for paper in papers) == 900
    assert sum(paper["language"] == "en" for paper in papers) == 100
    assert len({paper["record_id"] for paper in papers}) == 1000
    assert len({re.sub(r"[\W_]+", "", paper["title"]).casefold() for paper in papers}) == 1000
    assert all(len(paper["abstract"]) >= 80 and paper["source_url"] and paper["openalex_id"] for paper in papers)
    assert len(list((corpus / "documents").glob("*.md"))) == 1000
    from pypdf import PdfReader
    for paper in papers:
        if paper["content_level"] == "fulltext":
            assert paper.get("license") in {"cc-by", "cc0", "public-domain", "cc-by-sa"}
            reader = PdfReader(corpus / "fulltext" / (paper["record_id"] + ".pdf"))
            assert len(reader.pages) == paper["page_count"]

    fulltext_dir = ROOT / "python/knowledge-service/data/literature-fulltext-100"
    fulltexts = [json.loads(line) for line in (fulltext_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(fulltexts) == 100 and sum(paper["language"] == "zh" for paper in fulltexts) == 90
    assert sum(paper["language"] == "en" for paper in fulltexts) == 10
    assert len({paper["pdf_sha256"] for paper in fulltexts}) == 100
    assert len({paper["doi"].lower() for paper in fulltexts}) == 100
    assert len(list((fulltext_dir / "fulltext").glob("*.pdf"))) == 100
    for paper in fulltexts:
        pdf_path = fulltext_dir / "fulltext" / (paper["record_id"] + ".pdf")
        assert hashlib.sha256(pdf_path.read_bytes()).hexdigest() == paper["pdf_sha256"]
        assert len(PdfReader(pdf_path).pages) == paper["page_count"]
        assert paper["content_level"] == "fulltext" and len(paper["fulltext"]) > 3000
    expected = {paper["record_id"]: paper for paper in papers + fulltexts}

    literature_stats = request("http://127.0.0.1:10252/knowledge/literature/stats")["data"]
    assert literature_stats["total"] == len(expected)
    assert literature_stats["zh"] == sum(paper["language"] == "zh" for paper in expected.values())
    assert literature_stats["en"] == sum(paper["language"] == "en" for paper in expected.values())
    assert literature_stats["levels"]["fulltext"] == 100
    statistics = request("http://127.0.0.1:10252/knowledge/stats")["data"]
    database = json.loads((ROOT / "python/knowledge-service/data/knowledge.json").read_text(encoding="utf-8"))
    assert len(database["knowledge_db"]) == statistics["total_documents"]
    assert max(len(chunk["text"]) for chunk in database["chunks_db"]) <= 400
    assert statistics["qdrant_vectors"] == statistics["total_chunks"]
    indexed = {item["id"]: item for item in database["knowledge_db"]}
    for paper in fulltexts:
        stored = indexed["kb_" + paper["record_id"]]
        assert stored["literature"]["content_level"] == "fulltext"
        assert stored["literature"]["pdf_sha256"] == paper["pdf_sha256"]
        stored_text = Path(stored["file_path"]).read_text(encoding="utf-8")
        assert "## 开放全文" in stored_text
        assert f"元数据来源：{paper['metadata_source']}" in stored_text
        original_pdf = request(f"http://127.0.0.1:10252/knowledge/literature/{paper['record_id']}/pdf")
        assert hashlib.sha256(original_pdf).hexdigest() == paper["pdf_sha256"]
    search_tests = []
    for query, category in [
        ("基于层次分析法与模糊综合评价的作战效能评估方法", "作战评估"),
        ("TOPSIS 多指标决策评价方法", "综合评估方法"),
        ("数据分析与数据挖掘方法", "数据分析"),
    ]:
        result = request("http://127.0.0.1:10252/knowledge/search", {"query": query, "category": category, "top_k": 3})
        assert result["total"] > 0, result
        assert all(item["category"] == category and item.get("source_url") and item.get("content_level") for item in result["results"])
        search_tests.append({"query": query, "results": [{"title": item["title"], "source_url": item["source_url"], "content_level": item["content_level"]} for item in result["results"]]})
    for query in ("军事目标评估中多属性决策方法综述", "Audit Risk Evaluation Method Based on TOPSIS and Choquet Fuzzy Integral"):
        result = request("http://127.0.0.1:10252/knowledge/search", {"query": query, "top_k": 3})
        assert any(item["content_level"] == "fulltext" and item["title"] == query for item in result["results"]), result
        search_tests.append({"query": query, "fulltext_found": True})

    ontology_list = request("http://127.0.0.1:10256/ontology/list")["items"]
    assert ontology_list
    ontology_id = ontology_list[0]["id"]
    base = f"http://127.0.0.1:10256/ontology/{ontology_id}/workbench"
    snapshot = request(base)["data"]
    document = snapshot["document"]
    validation = request(base + "/validate", {"document": document})["data"]
    query = request(base + "/query", {"document": document, "query": "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> SELECT ?s ?label WHERE { ?s rdfs:label ?label } LIMIT 5"})["data"]
    assert query["rows"]
    from rdflib import Graph
    exported = request(base + "/export-rdf?format=turtle")
    exported_graph = Graph().parse(data=exported.decode("utf-8"), format="turtle")
    assert len(exported_graph)
    structural_errors = [issue for issue in validation["issues"] if issue["severity"] == "error" and issue["code"] != "required-property"]
    reasoning = request(base + "/reason", {"document": document})["data"] if not structural_errors else {"skipped": "existing ontology has structural errors", "issues": structural_errors}
    # Import and reason over a draft only; leave the user's existing models intact.
    fixture = '''@prefix ex: <https://example.org/acceptance#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Object a owl:Class ; rdfs:label "评估对象"@zh .
ex:Task a owl:Class ; rdfs:subClassOf ex:Object ; rdfs:label "任务"@zh .
ex:task1 a ex:Task ; rdfs:label "示例任务"@zh .'''
    imported = request(base + "/import-rdf", {"content": fixture, "format": "turtle"})["data"]
    assert imported["validation"]["conforms"]
    fixture_reasoning = request(base + "/reason", {"document": imported["document"]})["data"]
    assert fixture_reasoning["inferences"] and fixture_reasoning["persisted"] is False
    shapes = '''@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <https://example.org/acceptance#> .
ex:Shape a sh:NodeShape ; sh:targetClass ex:Task ;
sh:property [ sh:path ex:score ; sh:minCount 1 ; sh:message "缺少评分" ] .'''
    fixture_validation = request(base + "/validate", {"document": imported["document"], "shapes": shapes})["data"]
    assert not fixture_validation["conforms"] and any(issue["code"] == "shacl" for issue in fixture_validation["issues"])
    assert request(base)["data"]["revision"] == snapshot["revision"]
    report = {"literature": literature_stats, "fulltext_delivery": {"total": 100, "zh": 90, "en": 10, "pages": sum(paper["page_count"] for paper in fulltexts), "unique_pdf_hashes": 100, "pdf_downloads_verified": 100}, "knowledge_index": statistics, "search_checks": search_tests, "ontology": {"id": ontology_id, "revision": snapshot["revision"], "validation": validation, "rdf_triples": len(exported_graph), "query_rows": len(query["rows"]), "reasoning": reasoning}, "draft_acceptance": {"import_triples": imported["triple_count"], "reasoning": fixture_reasoning, "shacl": fixture_validation, "existing_revision_unchanged": True}, "passed": True}
    output = ROOT / "tmp" / "acceptance"
    output.mkdir(parents=True, exist_ok=True)
    (output / "ontology-literature.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "literature": literature_stats, "vectors": statistics["qdrant_vectors"], "search_cases": len(search_tests), "ontology_id": ontology_id, "rdf_triples": len(exported_graph), "legacy_validation_conforms": validation["conforms"], "draft_inferences": len(fixture_reasoning["inferences"]), "shacl_checked": True}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
