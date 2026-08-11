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

# ── 草稿态 TTL（秒），跨功能跳转传参用 ──
DRAFT_TTL = int(os.getenv("DRAFT_TTL", "3600"))

# ── 跨服务 HTTP 调用超时（秒）──
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))

# ── Phase 1 mock 流式模拟间隔（秒）；Phase 2 接入真实 Agent 后移除 ──
MOCK_STREAM_INTERVAL = float(os.getenv("MOCK_STREAM_INTERVAL", "0.6"))

# ── Skill 生命周期 / 收藏 / 使用记录持久化（SQLite）──
SITUATION_SKILL_DB = os.getenv(
    "SITUATION_SKILL_DB",
    os.path.join(_SERVICE_DIR, "data", "situation_skills.sqlite3"),
)
