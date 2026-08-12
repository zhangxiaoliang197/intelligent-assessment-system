"""本体构建服务配置常量。

集中管理分批处理的可调参数，避免散落硬编码。
所有参数基于"中文 1 字 ≈ 1.5-2 token"经验估算，适配主流 16K-32K 上下文窗口。
"""
import os

# ── Repository 后端选择 ──
# json：JsonRepository（默认，内存字典 + JSON 文件）
# neo4j：Neo4jRepository（图数据库，Phase 3 引入）
# dual：DualRepository（双写过渡，Phase 4 引入）
REPOSITORY_BACKEND = os.getenv("ONTOLOGY_REPOSITORY_BACKEND", "json").lower()

# ── Neo4j 连接配置（Phase 3 引入）──
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "ontology123")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
# 连接池大小（默认 100，大规模查询可调高）
NEO4J_MAX_CONNECTIONS = int(os.getenv("NEO4J_MAX_CONNECTIONS", "100"))
# 连接超时秒数
NEO4J_CONNECTION_TIMEOUT = int(os.getenv("NEO4J_CONNECTION_TIMEOUT", "30"))

# ── Step 1 概念提取分批（类型层）──
# 文档字符数超过此值才分批，否则单次调用（保持兼容、节省开销）
STEP1_BATCH_THRESHOLD_CHARS = int(os.getenv("STEP1_BATCH_THRESHOLD_CHARS", "10000"))
# 每批喂给 LLM 的文档字符数上限（≈13.5K-18K token，留出 prompt 模板 + 输出空间）
STEP1_BATCH_MAX_CHARS = int(os.getenv("STEP1_BATCH_MAX_CHARS", "9000"))
# 相邻批重叠字符数（覆盖跨批边界概念的上下文，约 5-8 个句子）
STEP1_BATCH_OVERLAP = int(os.getenv("STEP1_BATCH_OVERLAP", "500"))

# ── Step 2 实体+属性提取分批（实例层）──
# 与 step1 同源分批策略：长文档分批提取实体，跨批按 name 去重合并 properties
STEP2_BATCH_THRESHOLD_CHARS = int(os.getenv("STEP2_BATCH_THRESHOLD_CHARS", "10000"))
STEP2_BATCH_MAX_CHARS = int(os.getenv("STEP2_BATCH_MAX_CHARS", "9000"))
STEP2_BATCH_OVERLAP = int(os.getenv("STEP2_BATCH_OVERLAP", "500"))

# ── 并行抽取并发数 ──
# Step1/Step2 多批 LLM 调用的最大并发数（asyncio.Semaphore 限流，避免触发 LLM API 速率限制）。
# 各批在线程池中并行调用（_llm_json_async → run_in_executor），此处限制同时 in-flight 的批数。
# 单批或低配 LLM 账号建议设 1-2；高配可设 3-5。
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "3"))

# ── Step 3 关系建模分组 ──
# 实体数超过此值才分组，否则单次调用（保持兼容）
STEP3_GROUP_THRESHOLD_ENTITIES = int(os.getenv("STEP3_GROUP_THRESHOLD_ENTITIES", "25"))
# 每组实体数上限（20 实体 + prompt 模板约 5K token + 输出 4K token，总占用约 10K，安全）
STEP3_GROUP_SIZE = int(os.getenv("STEP3_GROUP_SIZE", "20"))

# ── Step 3 跨组关系补充 ──
# 实体数超过此值时，跨组关系补充调用也按批分组实体（防止实体名列表过长）
STEP3_CROSS_GROUP_ENTITY_THRESHOLD = int(os.getenv("STEP3_CROSS_GROUP_ENTITY_THRESHOLD", "80"))
# 跨组关系补充时每批实体数上限
STEP3_CROSS_GROUP_ENTITY_BATCH = int(os.getenv("STEP3_CROSS_GROUP_ENTITY_BATCH", "60"))

# ── Step 4 验证 + 报告 ──
# 验证 prompt 中喂给 LLM 的原文字符数上限（防止 prompt 过长撑爆上下文）
VERIFICATION_MAX_DOC_CHARS = int(os.getenv("VERIFICATION_MAX_DOC_CHARS", "20000"))

# ── LLM 调用参数 ──
# reasoning 模型（如 deepseek-v4-flash / deepseek-reasoner）会优先消耗 token 做思考链
# （reasoning_content），再输出正式 content。max_tokens 需同时容纳 reasoning + content，
# 否则 reasoning 耗尽上限后 content 会被截断为空（finish_reason=length）。
# 复杂文学/叙事文档的 reasoning 可达 6K-15K token，8000 明显不足，提到 24000。
# 可通过环境变量 LLM_MAX_TOKENS 覆盖。
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "24000"))

# ── 粒度预设（step0 用户选择，注入 step1/step2 prompt 控制提取数量）──
# coarse（粗）：仅核心概念，适合快速概览
# medium（中）：默认，平衡覆盖与噪声
# fine（细）：详细提取，适合深度分析
# 区间为 (下限, 上限)，注入 prompt 时转为"通常提取 X-Y 个"的软约束
GRANULARITY_RANGES = {
    "coarse": {"concepts": (5, 10), "entities": (10, 20)},
    "medium": {"concepts": (10, 20), "entities": (20, 40)},
    "fine": {"concepts": (20, 40), "entities": (40, 80)},
}

# ── 主要实体识别阈值（step2 LLM 标注 is_primary_candidate 的参考依据）──
PRIMARY_ENTITY_MIN_FREQUENCY = int(os.getenv("PRIMARY_ENTITY_MIN_FREQUENCY", "3"))
PRIMARY_ENTITY_MIN_REFERENCED = int(os.getenv("PRIMARY_ENTITY_MIN_REFERENCED", "1"))
