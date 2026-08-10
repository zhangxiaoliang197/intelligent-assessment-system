---
version: 2.0.0
---

# 内置评估 Skill 目录

本目录使用 Markdown 文件存储系统内置的评估 Skill。

## 存储约定

- 每个 Skill 使用独立的 `<skill-id>/SKILL.md` 文件。
- YAML front matter 是运行时结构化数据源。
- Markdown 正文同步提供便于阅读和维护的说明、步骤与输出要求。
- Skill 文件夹名称必须与 front matter 中的 `id` 完全一致。
