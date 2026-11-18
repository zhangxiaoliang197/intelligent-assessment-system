# 评估研究文献知识库

目标：1000 篇可追溯文献记录，900 篇中文、100 篇英文。领域覆盖数据分析、作战评估、体系评估、效能评估与综合评估方法。文献题名按实际文字和 OpenAlex 语言字段共同检查；不把英文论文的中文翻译计为中文论文。

## 收集和内容分级

来源为 [OpenAlex 公共学术索引](https://openalex.org/)（元数据 CC0）以及论文的官方开放出版/仓储位置。按 DOI 和规范化题名去重，剔除撤稿记录，并按题名相关性排除讲话、专访、宣传报道等明显不适合研究知识库的内容。

每条记录保留题名、作者、年份、来源期刊、DOI（如有）、原文链接、OpenAlex ID、语言、主题和许可。只从许可明确允许复用的开放位置尝试获取全文；不会绕过付费墙或把摘要误标为全文。

最初收集的 1000 篇集合（仍保留）：

| 口径 | 数量 |
| --- | ---: |
| 总计（唯一题名及唯一记录 ID） | 1000 |
| 中文 | 900 |
| 英文 | 100 |
| 可复用开放 PDF 全文（成功解析） | 6 |
| 带论文摘要 | 994 |
| 仅题录、无摘要 | 0 |

主题分布：作战评估 120 篇，体系评估、效能评估、数据分析、综合评估方法各 220 篇。上述主题数量包含英文文献。

本次是“文献全文/摘要分级入库”，不是“1000 篇全文论文”。开放全文原件单独保留，摘要记录带有明确的内容级别标签。

## 优先交付的 100 篇全文

根据用户后续“先来100篇全文”的要求，另建 `python/knowledge-service/data/literature-fulltext-100/` 全文集合：**100 篇完整论文，中文 90 篇、英文 10 篇**，共 1166 页。PDF 文件、唯一 DOI、唯一规范化题名、文件 SHA-256 和可检索正文均已核验，100 个文件哈希互不重复。

中文新增来源以汉斯出版社官方开放 PDF 为主，英文补充来自 SCIRP 官方开放 PDF。逐份检查文内 CC BY 声明；缺少许可、下载失败、题名不一致或正文无法完整提取的候选不计入 100 篇。原始 PDF 保留排版、图表和公式；知识库分片使用提取后的正文。

全文清单：`literature-fulltext-100/bibliography.csv`；逐篇元数据与完整正文：`manifest.jsonl`；原件：`fulltext/`。知识库按确定性文献 ID 去重，旧摘要可升级为全文，其他既有记录保留。界面可以按“全文论文”筛选，并直接打开本地收录的 PDF 原件。

复用全文清单入库：`.\.venv\Scripts\python.exe scripts/collect_fulltext_100.py --resume-manifest --import-url http://127.0.0.1:10252`。

最终知识库包含 1094 条去重文献记录（中文 988、英文 106，中文占约 90.3%），其中全文 100 篇、摘要 994 篇，共 11223 个知识分片与向量。验收逐份请求了 100 个本地 PDF 接口，并比对文件 SHA-256；中英文全文检索、分类检索、本体语义接口均通过。报告：`tmp/acceptance/ontology-literature.json`。

## 文件与知识库

运行时材料存于 `python/knowledge-service/data/literature-1000/`：

- `manifest.jsonl`：逐篇来源、内容层级和完整元数据。
- `bibliography.csv`：可核对的 1000 篇文献清单。
- `documents/`：与最终清单一致的可检索 Markdown 文献。
- `fulltext/`：获得许可的 PDF 原件。
- `source-cache/`：公共索引响应、排除文档等采集审计材料。
- `report.json`：语言、内容级别、主题和去重统计。
- `import-results.json`：知识库导入记录。

上述为知识库运行时数据，按项目规则不提交 Git。知识库文献导入 API 使用确定性 ID，可重复运行；每篇文献实际生成知识分片和 BGE 向量，存入项目 Qdrant `knowledge_chunks` 集合。分片上限 400 字符并保留重叠，适配本地 BGE 512-token 模型。

知识库列表增加内容级别和原文来源；检索结果附带 `literature`、`source_url`、`content_level`，便于问答区分文献全文与摘要证据。

## 重复执行

```powershell
.\.venv\Scripts\python.exe scripts/collect_assessment_literature.py --fulltext
.\.venv\Scripts\python.exe scripts/collect_assessment_literature.py --resume-manifest --import-url http://127.0.0.1:10252
```

第二条命令复用清单并幂等入库；不需要重新下载公共索引。最终统计接口为 `GET /knowledge/literature/stats`，分片修复接口为 `POST /knowledge/literature/reindex`（只重建文献文档，不删除其他知识）。
