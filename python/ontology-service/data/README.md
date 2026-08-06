# ontology-service 数据目录说明

| 文件/目录 | 用途 | 是否入库 |
|-----------|------|----------|
| `ontologies_index.json` | 本体列表索引（服务启动时加载） | ✅ 是 |
| `ontology_ont_seed_combat.json` | 种子本体：作战效能评估本体 | ✅ 是 |
| `ontology_ont_61daa626.json` | 演示本体：金融示例（分步构建功能生成的演示数据） | ✅ 是 |
| `build_jobs/` | 分步构建任务的运行时状态数据（含文档原文、LLM 结果） | ❌ 否（已 gitignore） |

> `build_jobs/` 为运行时产物，随分步构建任务自动生成，请勿手动修改或提交。
