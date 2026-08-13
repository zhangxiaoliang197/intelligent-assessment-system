"""态势图服务配置常量。

集中管理跨服务地址与可调参数，全部通过环境变量覆盖，禁止硬编码。
Docker 部署时由 start-docker-run.sh 的 -e 覆盖为容器名。
"""
import os

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 跨服务地址（默认本地开发，Docker 由 -e 覆盖）──
# admin-service：LLM 配置 / 地图配置 / 态势产物持久化 CRUD
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
# qa-service：知识检索 / 评估结果（评估端点由 qa 暴露）
QA_SERVICE_URL = os.getenv("QA_SERVICE_URL", "http://localhost:10253")
# knowledge-service：知识库直接检索（可选）
KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:10252")
# indicator-service：指标数据
INDICATOR_SERVICE_URL = os.getenv("INDICATOR_SERVICE_URL", "http://localhost:10254")

# ── LLM 调用参数（与 ontology-service 对齐）──
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "24000"))

# ── 态势生成模式 ──
# 默认使用真实数据 + LLM；mock 仅用于显式的本地演示/测试。
SITUATION_GENERATION_MODE = os.getenv("SITUATION_GENERATION_MODE", "real").strip().lower()
# LLM 暂不可用时，仍可基于已经取得的真实数据生成基础图表，避免整次任务丢失。
SITUATION_ALLOW_DATA_FALLBACK = os.getenv(
    "SITUATION_ALLOW_DATA_FALLBACK", "true"
).strip().lower() in {"1", "true", "yes", "on"}
# 单个物理数据集送入编排器的最大行数；admin-service 本身还有 1000 行硬上限。
SITUATION_DATA_ROW_LIMIT = max(1, min(int(os.getenv("SITUATION_DATA_ROW_LIMIT", "200")), 1000))
# 通用提问未指定 Skill 时，自动抽样的已注册业务数据集数量。
SITUATION_AUTO_DATASET_LIMIT = max(1, min(int(os.getenv("SITUATION_AUTO_DATASET_LIMIT", "2")), 5))
# 完成后的 SSE 事件保留时间，支持浏览器断线重连和结果回放。
SITUATION_STREAM_REPLAY_TTL = max(30, int(os.getenv("SITUATION_STREAM_REPLAY_TTL", "300")))

# 生成任务资源治理。请求超过在途上限时直接返回 429，单任务超过 deadline 会被
# 取消并持久化为 failed，避免慢数据源或 LLM 长时间占住唯一事件循环。
SITUATION_MAX_INFLIGHT = max(1, int(os.getenv("SITUATION_MAX_INFLIGHT", "8")))
SITUATION_MAX_CONCURRENT = max(1, min(
    int(os.getenv("SITUATION_MAX_CONCURRENT", "2")), SITUATION_MAX_INFLIGHT,
))
SITUATION_MAX_PER_USER = max(1, int(os.getenv("SITUATION_MAX_PER_USER", "2")))
SITUATION_GENERATION_TIMEOUT = max(30, int(os.getenv("SITUATION_GENERATION_TIMEOUT", "240")))
SITUATION_IDEMPOTENCY_TTL = max(60, int(os.getenv("SITUATION_IDEMPOTENCY_TTL", "900")))

# situation-service 调 admin-service 数据查询专用端点时使用的服务身份。生产环境
# 必须通过 Secret 注入并覆盖默认值；该值不会发送给浏览器或 LLM。
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "local-development-token")

# 原始记录不再直接外发。下面两项约束允许送给模型的脱敏/聚合证据大小。
SITUATION_LLM_EVIDENCE_ROWS = max(0, min(
    int(os.getenv("SITUATION_LLM_EVIDENCE_ROWS", "0")), 100,
))
SITUATION_LLM_EVIDENCE_CHARS = max(2000, min(
    int(os.getenv("SITUATION_LLM_EVIDENCE_CHARS", "24000")), 60000,
))
SITUATION_SENSITIVE_COLUMNS = tuple(
    item.strip().lower()
    for item in os.getenv(
        "SITUATION_SENSITIVE_COLUMNS",
        "姓名,身份证,证件,手机号,电话,邮箱,地址,密码,口令,token,secret,api_key,apikey",
    ).split(",")
    if item.strip()
)

# ── 草稿态 TTL（秒），跨功能跳转传参用 ──
DRAFT_TTL = int(os.getenv("DRAFT_TTL", "3600"))

# ── 跨服务 HTTP 调用超时（秒）──
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))

# SQL 执行（LLM 生成的精确查询）可能较慢，单独放宽超时（与评估分析对齐）
SQL_QUERY_TIMEOUT = int(os.getenv("SQL_QUERY_TIMEOUT", "120"))

# ── Phase 1 mock 流式模拟间隔（秒）；Phase 2 接入真实 Agent 后移除 ──
MOCK_STREAM_INTERVAL = float(os.getenv("MOCK_STREAM_INTERVAL", "0.6"))

# ── 生成模式：true=Phase1 mock（canned 数据，不调 LLM）；false=Phase2 真实 LLM Agent ──
# Phase 2 默认启用；调试或无 LLM 环境时设 SITUATION_USE_MOCK=true 回退 mock
# 注意：os.getenv 返回字符串，"false" 在 Python 中为 truthy，必须显式解析为 bool
USE_MOCK = os.getenv("SITUATION_USE_MOCK", "false").strip().lower() in ("true", "1", "yes", "on")

# ── 真实生成时单数据集查询行数上限（传给 admin-service /dataset/{id}/data）──
DATA_QUERY_LIMIT = int(os.getenv("DATA_QUERY_LIMIT", "200"))

# ── Skill 生命周期 / 收藏 / 使用记录持久化（SQLite）──
SITUATION_SKILL_DB = os.getenv(
    "SITUATION_SKILL_DB",
    os.path.join(_SERVICE_DIR, "data", "situation_skills.sqlite3"),
)
