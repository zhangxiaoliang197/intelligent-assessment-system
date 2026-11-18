"""Collect verifiable assessment literature and optionally import it into the KB.

Public OpenAlex metadata is CC0. Full texts are fetched only from an explicitly
open, reusable publisher/repository location. A record without full text is never
labelled as a full-text paper. Re-running resumes from the local source cache.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "python/knowledge-service/data/literature-1000"
FIELDS = "id,doi,title,language,publication_year,publication_date,type,authorships,primary_location,best_oa_location,open_access,abstract_inverted_index,cited_by_count,is_retracted"
TOPICS = [
    ("作战评估", ["作战评估", "作战效能", "作战能力", "作战仿真", "装备效能", "作战", "战斗力", "军事评估", "武器系统", "指挥效能", "防空效能", "雷达评估"], ["combat effectiveness assessment", "military capability assessment", "military simulation"], 100),
    ("体系评估", ["体系评估", "体系效能", "装备体系"], ["system of systems evaluation", "system of systems effectiveness"], 200),
    ("效能评估", ["效能评估", "效能评价", "系统效能"], ["effectiveness evaluation", "system effectiveness assessment"], 200),
    ("数据分析", ["数据分析", "数据挖掘", "多源数据融合"], ["data analysis", "data fusion evaluation"], 200),
    ("综合评估方法", ["综合评价", "评估方法", "多指标决策"], ["multi criteria decision making", "comprehensive evaluation methods"], 200),
]


def log(message):
    print(message, flush=True)


def download(url: str, path: Path | None = None, timeout: int = 60) -> bytes:
    command = ["curl.exe", "--ipv4", "--noproxy", "*", "--fail", "--location",
               "--connect-timeout", "10", "--max-time", str(timeout), "--silent", "--show-error",
               "--user-agent", "AssessmentLiteratureCollector/1.0 (public scholarly research)"]
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        command += ["--output", str(path)]
    result = subprocess.run([*command, url], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-350:])
    return result.stdout


def abstract_text(index):
    if not isinstance(index, dict):
        return ""
    words = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(words))


def canonical_title(title):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", title)).casefold()


def topic_matches(title, topic, language):
    if language == "zh":
        if re.search(r"讲话|专访|访谈|致辞|贺信|经验谈|侧记|纪实|宣传|图说|书评|致读者|之路|经验介绍", title):
            return False
        method = bool(re.search(r"评估|评价|效能|效率|分析|建模|模型|仿真|决策|指标|数据|方法|测度|算法|度量", title))
        if not method:
            return False
        anchors = {
            "作战评估": r"作战|战斗力|军事|装备|武器|兵力|军队|防空|导弹|雷达|电子战|火力|兵器|C.?4ISR",
            "体系评估": r"体系|系统|复杂网络",
            "效能评估": r"效能|效率|性能|绩效",
            "数据分析": r"数据|挖掘|融合|统计分析",
            "综合评估方法": r"评价|评估|决策|指标|测度",
        }
    else:
        title = title.lower()
        anchors = {
            "作战评估": r"combat|military|defen[sc]e|warfare|armed force|weapon|mission effectiveness",
            "体系评估": r"system.of.systems|systems engineering|complex system|systematic.*evaluat",
            "效能评估": r"effectiveness|efficiency|performance",
            "数据分析": r"data.*analy|data.*fusion|data mining|statistical",
            "综合评估方法": r"multi.criteria|decision.making|comprehensive.*evaluat|assessment method",
        }
    return bool(re.search(anchors[topic], title))


def paper_from_work(work, topic, language):
    title = str(work.get("title") or "").strip()
    if not title or work.get("is_retracted") or work.get("language") != language:
        return None
    if not topic_matches(title, topic, language):
        return None
    han = len(re.findall(r"[\u3400-\u9fff]", title))
    if language == "zh" and han < 4:
        return None
    if language == "en" and han:
        return None
    if not (1980 <= int(work.get("publication_year") or 0) <= 2026):
        return None
    abstract = abstract_text(work.get("abstract_inverted_index"))
    if len(abstract) < 80:
        return None
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    oa = work.get("best_oa_location") or {}
    authors = [a.get("author", {}).get("display_name", "") for a in work.get("authorships") or []]
    doi = str(work.get("doi") or "").lower()
    identifier = doi or str(work["id"])
    return {
        "record_id": "lit_" + hashlib.sha256(identifier.encode()).hexdigest()[:20],
        "title": title, "doi": doi, "openalex_id": work["id"],
        "language": language, "year": work.get("publication_year"),
        "publication_date": work.get("publication_date"), "authors": authors,
        "journal": source.get("display_name") or location.get("raw_source_name") or "来源未标注",
        "topic": topic, "abstract": abstract,
        "source_url": location.get("landing_page_url") or doi or work["id"],
        "pdf_url": oa.get("pdf_url") or (location.get("pdf_url") if location.get("is_oa") else None),
        "license": oa.get("license") or (location.get("license") if location.get("is_oa") else None),
        "is_oa": bool((work.get("open_access") or {}).get("is_oa")),
        "cited_by_count": work.get("cited_by_count", 0),
        "content_level": "abstract" if len(abstract) >= 80 else "metadata",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "metadata_source": "OpenAlex (CC0)",
    }


def collect(output: Path):
    cache = output / "source-cache"
    cache.mkdir(parents=True, exist_ok=True)
    records, seen_doi, seen_title = [], set(), set()
    for language in ("zh", "en"):
        for topic, chinese_queries, english_queries, quota_zh in TOPICS:
            quota = quota_zh if language == "zh" else 20
            accepted = 0
            queries = chinese_queries if language == "zh" else english_queries
            for query in queries:
                if accepted >= quota:
                    break
                for page in range(1, 4):
                    if accepted >= quota:
                        break
                    cache_key = hashlib.sha256(f"with-abstract|{language}|{query}|{page}".encode()).hexdigest()[:16]
                    cached = cache / f"{cache_key}.json"
                    if cached.is_file():
                        response = json.loads(cached.read_text(encoding="utf-8"))
                    else:
                        parameters = {
                            "filter": f"language:{language},type:article,is_retracted:false,has_abstract:true,title.search:{query}",
                            "per-page": 200, "page": page, "select": FIELDS,
                        }
                        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(parameters)
                        log(f"Searching {language} / {topic}: {query}, page {page}")
                        try:
                            response = json.loads(download(url))
                        except Exception as error:
                            log(f"Search failed: {query}: {error}")
                            break
                        cached.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
                        time.sleep(1.1)
                    works = response.get("results") or []
                    for work in works:
                        paper = paper_from_work(work, topic, language)
                        if not paper:
                            continue
                        key = canonical_title(paper["title"])
                        doi = paper["doi"]
                        if key in seen_title or (doi and doi in seen_doi):
                            continue
                        seen_title.add(key)
                        if doi:
                            seen_doi.add(doi)
                        records.append(paper)
                        accepted += 1
                        if accepted >= quota:
                            break
                    log(f"Selected {accepted}/{quota} for {language}/{topic}; total {len(records)}")
                    if len(works) < 200:
                        break
            if accepted < quota:
                log(f"SHORTFALL: {language}/{topic}: {accepted}/{quota}")
    return records


def enrich_fulltext(paper, output):
    license_name = str(paper.get("license") or "").lower()
    reusable = license_name in {"cc-by", "cc0", "public-domain", "cc-by-sa"}
    if not paper.get("pdf_url") or not reusable:
        return paper
    path = output / "fulltext" / f"{paper['record_id']}.pdf"
    try:
        if not path.is_file():
            download(paper["pdf_url"], path, timeout=25)
        if path.stat().st_size > 25 * 1024 * 1024:
            paper["fulltext_status"] = "file-too-large"
            return paper
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        if len(re.sub(r"\s", "", text)) >= 1200:
            paper["fulltext"] = text
            paper["pdf_path"] = str(path)
            paper["page_count"] = len(reader.pages)
            paper["content_level"] = "fulltext"
            paper["fulltext_status"] = "downloaded-and-parsed"
        else:
            paper["fulltext_status"] = "insufficient-extractable-text"
    except Exception as error:
        paper["fulltext_status"] = "unavailable"
        paper["fulltext_error"] = str(error)[:200]
    return paper


def document_text(paper):
    level = {"fulltext": "开放全文", "abstract": "论文摘要", "metadata": "仅题录"}[paper["content_level"]]
    text = (
        f"# {paper['title']}\n\n收录级别：{level}（不得将摘要或题录误认为全文）\n"
        f"语言：{'中文' if paper['language'] == 'zh' else '英文'}\n"
        f"作者：{'；'.join(paper['authors'])}\n年份：{paper['year']}\n"
        f"期刊/会议：{paper['journal']}\n主题：{paper['topic']}\n"
        f"DOI：{paper['doi'] or '未提供'}\n原始来源：{paper['source_url']}\n"
        f"学术索引：{paper.get('openalex_id') or '出版社原始记录'}\n元数据来源：{paper.get('metadata_source') or '来源未标注'}\n"
        f"全文许可：{paper.get('license') or '未获取可复用全文许可'}\n\n"
    )
    if paper.get("abstract"):
        text += "## 摘要\n\n" + paper["abstract"] + "\n\n"
    if paper.get("fulltext"):
        text += "## 开放全文\n\n" + paper["fulltext"]
    if paper["content_level"] == "metadata":
        text += "当前来源未提供可用摘要/全文。本条仅用于发现和引用，不支持论文研究结论。\n"
    return text


def write_outputs(records, output):
    output.mkdir(parents=True, exist_ok=True)
    documents = output / "documents"
    documents.mkdir(exist_ok=True)
    selected = {paper["record_id"] for paper in records}
    excluded = output / "source-cache" / "excluded-documents"
    for old_file in documents.glob("lit_*.md"):
        if old_file.stem not in selected and re.fullmatch(r"lit_[a-f0-9]{20}", old_file.stem):
            if not old_file.resolve().is_relative_to(output.resolve()):
                raise RuntimeError("Generated document path escaped output directory")
            excluded.mkdir(parents=True, exist_ok=True)
            old_file.replace(excluded / old_file.name)
    fulltext_ids = {paper["record_id"] for paper in records if paper["content_level"] == "fulltext"}
    for old_pdf in (output / "fulltext").glob("lit_*.pdf"):
        if old_pdf.stem not in fulltext_ids and re.fullmatch(r"lit_[a-f0-9]{20}", old_pdf.stem):
            if not old_pdf.resolve().is_relative_to(output.resolve()):
                raise RuntimeError("Full-text path escaped output directory")
            excluded_pdf = output / "source-cache" / "excluded-fulltext"
            excluded_pdf.mkdir(parents=True, exist_ok=True)
            old_pdf.replace(excluded_pdf / old_pdf.name)
    with (output / "manifest.jsonl").open("w", encoding="utf-8") as manifest:
        for paper in records:
            file_path = documents / f"{paper['record_id']}.md"
            file_path.write_text(document_text(paper), encoding="utf-8")
            paper["document_path"] = str(file_path)
            manifest.write(json.dumps(paper, ensure_ascii=False) + "\n")
    fields = ["record_id", "title", "language", "year", "topic", "journal", "doi", "source_url", "openalex_id", "content_level", "license"]
    with (output / "bibliography.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    counts = {
        "total": len(records),
        "zh": sum(p["language"] == "zh" for p in records),
        "en": sum(p["language"] == "en" for p in records),
        "levels": {level: sum(p["content_level"] == level for p in records) for level in ("fulltext", "abstract", "metadata")},
        "topics": {topic: sum(p["topic"] == topic for p in records) for topic, *_ in TOPICS},
        "unique_titles": len({canonical_title(p["title"]) for p in records}),
        "unique_ids": len({p["record_id"] for p in records}),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (output / "report.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    log(json.dumps(counts, ensure_ascii=False))
    return counts


def import_records(records, base_url):
    imported = []
    for offset in range(0, len(records), 20):
        batch = records[offset:offset + 20]
        payload = {"records": [{**paper, "text": document_text(paper)} for paper in batch]}
        request = urllib.request.Request(
            base_url.rstrip("/") + "/knowledge/literature/import",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.load(response)
        imported.extend(result.get("items") or [])
        log(f"Knowledge import: {offset + len(batch)}/{len(records)}")
    return imported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fulltext", action="store_true")
    parser.add_argument("--import-url", default="")
    parser.add_argument("--resume-manifest", action="store_true")
    args = parser.parse_args()
    manifest = args.output / "manifest.jsonl"
    if args.resume_manifest and manifest.is_file():
        records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        records = collect(args.output)
    if args.fulltext:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            records = list(pool.map(lambda paper: enrich_fulltext(paper, args.output), records))
    counts = write_outputs(records, args.output)
    if counts["total"] != 1000 or counts["zh"] != 900 or counts["en"] != 100:
        raise SystemExit("Quota not reached; source cache preserved for continuation")
    if args.import_url:
        imported = import_records(records, args.import_url)
        (args.output / "import-results.json").write_text(json.dumps(imported, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
