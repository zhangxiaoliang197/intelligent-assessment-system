"""本体构建服务配置常量。

集中管理分批处理的可调参数，避免散落硬编码。
所有参数基于"中文 1 字 ≈ 1.5-2 token"经验估算，适配主流 16K-32K 上下文窗口。
"""
import os

# ── Step 1 概念提取分批 ──
# 文档字符数超过此值才分批，否则单次调用（保持兼容、节省开销）
STEP1_BATCH_THRESHOLD_CHARS = int(os.getenv("STEP1_BATCH_THRESHOLD_CHARS", "10000"))
# 每批喂给 LLM 的文档字符数上限（≈13.5K-18K token，留出 prompt 模板 + 输出空间）
STEP1_BATCH_MAX_CHARS = int(os.getenv("STEP1_BATCH_MAX_CHARS", "9000"))
# 相邻批重叠字符数（覆盖跨批边界概念的上下文，约 5-8 个句子）
STEP1_BATCH_OVERLAP = int(os.getenv("STEP1_BATCH_OVERLAP", "500"))

# ── Step 2 层次结构分组 ──
# 概念数超过此值才分组，否则单次调用（保持兼容）
STEP2_GROUP_THRESHOLD_CONCEPTS = int(os.getenv("STEP2_GROUP_THRESHOLD_CONCEPTS", "25"))
# 每组概念数上限（20 概念 + prompt 模板约 5K token + 输出 4K token，总占用约 10K，安全）
STEP2_GROUP_SIZE = int(os.getenv("STEP2_GROUP_SIZE", "20"))

# ── Step 2 跨组关系补充 ──
# 实体数超过此值时，跨组关系补充调用也按批分组实体（防止实体名列表过长）
STEP2_CROSS_GROUP_ENTITY_THRESHOLD = int(os.getenv("STEP2_CROSS_GROUP_ENTITY_THRESHOLD", "80"))
# 跨组关系补充时每批实体数上限
STEP2_CROSS_GROUP_ENTITY_BATCH = int(os.getenv("STEP2_CROSS_GROUP_ENTITY_BATCH", "60"))

# ── LLM 调用参数（复用现有 max_tokens=8000，不新增）──
LLM_MAX_TOKENS = 8000
