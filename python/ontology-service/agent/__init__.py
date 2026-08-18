"""AI 构建聊天 Agent 模块。

提供聊天式本体构建所需的 Prompt 构造与 LLM 编排：
- prompts.py：意图识别 / 自然语言回复 / 历史摘要 / 任务状态摘要构造
- orchestrator.py：意图分类与回复生成的 LLM 编排（不直接操作 BuildJob）
"""
