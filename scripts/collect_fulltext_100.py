"""Collect and index 90 Chinese and 10 English complete, licensed OA PDFs.

Seed URLs are discovered from official indexes. No access challenge is solved.
Every accepted article retains attribution, DOI, PDF hash, page count and text.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
from pypdf import PdfReader
from collect_assessment_literature import canonical_title, document_text, write_outputs

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "python/knowledge-service/data/literature-1000"
OUTPUT = ROOT / "python/knowledge-service/data/literature-fulltext-100"

def chinese_title(value):
    value = value.strip()
    for match in re.finditer(r"[A-Z][a-z]+|A(?=\s)", value):
        if re.search(r"[\u3400-\u9fff]", value[:match.start()]) and not re.search(r"[\u3400-\u9fff]", value[match.start():]):
            return value[:match.start()].strip()
    return value

def download_pdf(url, path, referer):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes()[:5] == b"%PDF-":
        return
    for direct in (False, True):
        args = ["curl.exe", "--fail", "--location", "--connect-timeout", "10", "--max-time", "50", "--silent", "--show-error", "--user-agent", "Mozilla/5.0", "--referer", referer, "--output", str(path)]
        if direct:
            args += ["--ipv4", "--noproxy", "*"]
        result = subprocess.run([*args, url], capture_output=True)
        if not result.returncode and path.is_file() and path.read_bytes()[:5] == b"%PDF-":
            return
    raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-150:] or "No public PDF returned")

def classify(title):
    if re.search(r"作战|武器|装备|军事|防空|战斗|雷达|指挥|保障能力", title): return "作战评估"
    if re.search(r"效能|效率|绩效|有效性", title): return "效能评估"
    if re.search(r"评估|评价|多指标|决策|赋权", title): return "综合评估方法"
    return "数据分析"

def from_hans(seed):
    doi = "https://doi.org/" + seed["doi"].lower()
    title = chinese_title(seed["title"])
    return {"record_id": "lit_" + hashlib.sha256(doi.encode()).hexdigest()[:20],
        "title": title, "doi": doi, "openalex_id": "", "language": "zh",
        "year": int(re.search(r"\.(20\d\d)\.", doi)[1]), "authors": seed.get("authors", []),
        "journal": {612:"数据挖掘",601:"运筹与模糊学",762:"建模与仿真",759:"统计学与应用"}[seed["journal_id"]],
        "topic": classify(title), "source_url": f"https://www.hanspub.org/journal/paperinformation?paperid={seed['paper_id']}",
        "pdf_url": seed["pdf_url"], "index_url": seed["index_url"], "license": "cc-by", "is_oa": True,
        "metadata_source": "Hans Publishers official journal index and PDF"}

def parse_paper(paper):
    checkpoint = OUTPUT / "source-cache/parsed" / (paper["record_id"] + ".json")
    if checkpoint.is_file(): return json.loads(checkpoint.read_text(encoding="utf-8"))
    pdf = OUTPUT / "fulltext" / (paper["record_id"] + ".pdf")
    old_pdf = ORIGINAL / "fulltext" / pdf.name
    if old_pdf.is_file() and paper.get("content_level") == "fulltext":
        pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_pdf, pdf)
    else: download_pdf(paper["pdf_url"], pdf, paper["source_url"])
    reader = PdfReader(pdf)
    pages = [page.extract_text() or "" for page in reader.pages]
    body = "\n\n".join(f"[第 {i+1} 页 / Page {i+1}]\n{text}" for i,text in enumerate(pages))
    first = "\n".join(pages[:2])
    if len(pages) < 2 or len(body) < 3000: raise ValueError("Insufficient article text")
    if paper["language"] == "zh":
        if len(re.findall(r"[\u3400-\u9fff]", body)) < 600: raise ValueError("Insufficient Chinese body text")
        if "hanspub" in paper["pdf_url"]:
            license_text = re.sub(r"\s+", " ", first)
            if not re.search(r"CC\s*BY\s*4\.0", license_text) or re.search(r"CC\s*BY-NC", license_text):
                raise ValueError("No explicit CC BY 4.0 statement in PDF")
            if canonical_title(paper["title"]) not in canonical_title(first): raise ValueError("Title does not match PDF")
            abstract = re.search(r"摘\s*要\s*([\s\S]+?)关\s*键\s*词", first)
            paper["abstract"] = re.sub(r"\s+", "", abstract[1]) if abstract else ""
            paper["license_url"] = "https://creativecommons.org/licenses/by/4.0/"
            paper["license_evidence"] = "CC BY 4.0 statement verified in first two PDF pages"
    if len(paper.get("abstract", "")) < 80: raise ValueError("Missing article abstract")
    paper.update({"content_level":"fulltext", "fulltext":body, "page_count":len(pages),
        "pdf_sha256":hashlib.sha256(pdf.read_bytes()).hexdigest(), "fulltext_characters":len(body),
        "retrieved_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps(paper,ensure_ascii=False,indent=2),encoding="utf-8")
    return paper

def from_pdf_url(url):
    cached = OUTPUT / "source-cache/search-pdfs" / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".pdf")
    download_pdf(url, cached, "https://www.hanspub.org/")
    reader = PdfReader(cached)
    first = "\n".join(page.extract_text() or "" for page in reader.pages[:2])
    match = re.search(r"10\.12677/[A-Za-z]+\.\d{4}\.\d+", first)
    title = str((reader.metadata or {}).get("/Title") or "").strip()
    if not match or not re.search(r"[\u3400-\u9fff]", title): raise ValueError("Cannot verify DOI and title in PDF")
    doi = "https://doi.org/" + match[0].lower()
    paper_id = "lit_" + hashlib.sha256(doi.encode()).hexdigest()[:20]
    target = OUTPUT / "fulltext" / (paper_id + ".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached, target)
    journals = {"csa":"计算机科学与应用", "mos":"建模与仿真", "orf":"运筹与模糊学", "sa":"统计学与应用", "aam":"应用数学进展", "ae":"教育进展", "sd":"可持续发展", "ecl":"电子商务评论"}
    code = match[0].split("/")[1].split(".")[0].lower()
    paper = {"record_id":paper_id,"title":title,"doi":doi,"openalex_id":"","language":"zh",
        "year":int(re.search(r"\.(20\d\d)\.",doi)[1]), "authors":[x.strip() for x in re.split(r"[，,、；;]",str((reader.metadata or {}).get("/Author") or "")) if x.strip()],
        "journal":journals.get(code,"Hans Publishers"),"topic":classify(title),"source_url":url,"pdf_url":url,
        "license":"cc-by","is_oa":True,"metadata_source":"Hans Publishers official PDF metadata"}
    if re.search(r"体系|装备体系",title) and re.search(r"评估|评价",title): paper["topic"]="体系评估"
    return parse_paper(paper)

def from_english_pdf_url(url):
    cached=OUTPUT/"source-cache/search-pdfs"/(hashlib.sha256(url.encode()).hexdigest()[:20]+".pdf")
    download_pdf(url,cached,"https://www.scirp.org/")
    reader=PdfReader(cached)
    first="\n".join(page.extract_text() or "" for page in reader.pages[:2])
    match=re.search(r"10\.4236/[A-Za-z]+\.\d{4}\.\d+",first)
    title=str((reader.metadata or {}).get("/Title") or "").strip()
    if not match or not title or re.search(r"[\u3400-\u9fff]",title): raise ValueError("Cannot verify English title and DOI")
    if not re.search(r"CC\s*BY\s*4\.0|creativecommons.org/licenses/by/4.0",first): raise ValueError("No explicit CC BY license")
    abstract=re.search(r"\bAbstract\s*([\s\S]+?)(?:\bKeywords\b|\bKey words\b|1\.\s*Introduction)",first,re.I)
    if not abstract: raise ValueError("Cannot extract English abstract")
    doi="https://doi.org/"+match[0].lower();record_id="lit_"+hashlib.sha256(doi.encode()).hexdigest()[:20]
    target=OUTPUT/"fulltext"/(record_id+".pdf");target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(cached,target)
    journal=re.search(r"^\s*([^\n]+?),\s*(?:19|20)\d{2},",first,re.M)
    if not journal: raise ValueError("Cannot extract journal citation")
    paper={"record_id":record_id,"title":title,"doi":doi,"openalex_id":"","language":"en",
        "year":int(re.search(r"\.(20\d\d)\.",doi)[1]),"authors":[x.strip() for x in str((reader.metadata or {}).get("/Author") or "").split(",") if x.strip()],
        "journal":journal[1].strip(),"topic":"综合评估方法","source_url":url,"pdf_url":url,"license":"cc-by","is_oa":True,
        "abstract":re.sub(r"\s+"," ",abstract[1]).strip(),"license_url":"https://creativecommons.org/licenses/by/4.0/",
        "license_evidence":"CC BY 4.0 statement verified in publisher PDF","metadata_source":"SCIRP official PDF metadata"}
    if re.search(r"performance|efficien",title,re.I): paper["topic"]="效能评估"
    return parse_paper(paper)

def collect():
    original = [json.loads(line) for line in (ORIGINAL/"manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    seeds = json.loads((OUTPUT/"source-cache/hans-seeds.json").read_text(encoding="utf-8"))
    candidates = [p for p in original if p["content_level"] == "fulltext"] + [from_hans(seed) for seed in seeds]
    for paper in original:
        if paper["language"] != "en" or paper["content_level"] == "fulltext" or paper.get("license") != "cc-by": continue
        if paper["title"] == "Sustainable data analysis with Snakemake":
            paper["pdf_url"] = "https://duepublico2.uni-due.de/servlets/MCRFileNodeServlet/duepublico_derivate_00074511/Moelder_et_al_2021_Sustainable_data_analysis_v2.pdf"
        if paper.get("pdf_url"): candidates.append(paper)
    candidates = list({p["record_id"]:p for p in candidates}.values())
    records, failures = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(parse_paper,dict(p)):p for p in candidates}
        extra_urls = json.loads((OUTPUT/"source-cache/search-pdf-urls.json").read_text(encoding="utf-8"))
        futures.update({pool.submit(from_pdf_url,url):{"title":url,"record_id":""} for url in extra_urls})
        english_urls=json.loads((OUTPUT/"source-cache/english-pdf-urls.json").read_text(encoding="utf-8"))
        futures.update({pool.submit(from_english_pdf_url,url):{"title":url,"record_id":""} for url in english_urls})
        for future in as_completed(futures):
            paper = futures[future]
            try:
                parsed = future.result(); records.append(parsed)
                print(json.dumps({"accepted":len(records), "zh":sum(p["language"]=="zh" for p in records), "en":sum(p["language"]=="en" for p in records), "title":parsed["title"]},ensure_ascii=False),flush=True)
            except Exception as error:
                failures.append({"title":paper["title"],"record_id":paper["record_id"],"reason":str(error)})
                print(json.dumps({"failed":paper["title"],"reason":str(error)},ensure_ascii=False),flush=True)
    known = {p["record_id"] for p in original if p["content_level"]=="fulltext"}
    records = list({p["record_id"]:p for p in records}.values())
    records.sort(key=lambda p:(p["record_id"] not in known,p["topic"]=="数据分析",p["record_id"]))
    selected = [p for p in records if p["language"]=="zh"][:90] + [p for p in records if p["language"]=="en"][:10]
    (OUTPUT/"source-cache/failures.json").write_text(json.dumps(failures,ensure_ascii=False,indent=2),encoding="utf-8")
    write_outputs(selected,OUTPUT)
    if len(selected)!=100 or sum(p["language"]=="zh" for p in selected)!=90:
        raise SystemExit(f"Full-text quota not reached: zh={sum(p['language']=='zh' for p in selected)}, en={sum(p['language']=='en' for p in selected)}")
    assert len({p["pdf_sha256"] for p in selected})==100
    return selected

def import_selected(records,url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})); results=[]
    for offset in range(0,len(records),2):
        batch=records[offset:offset+2]
        payload={"records":[{**p,"text":document_text(p)} for p in batch]}
        req=urllib.request.Request(url.rstrip("/")+"/knowledge/literature/import",data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),headers={"Content-Type":"application/json"})
        with opener.open(req,timeout=600) as response: result=json.load(response)
        results.extend(result.get("items") or [])
        print(f"Full-text knowledge import {offset+len(batch)}/{len(records)}",flush=True)
    (OUTPUT/"import-results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-url",default=""); parser.add_argument("--resume-manifest",action="store_true")
    args=parser.parse_args(); manifest=OUTPUT/"manifest.jsonl"
    records=[json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()] if args.resume_manifest else collect()
    assert len(records)==100 and sum(p["language"]=="zh" for p in records)==90
    if args.import_url: import_selected(records,args.import_url)
