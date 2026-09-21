"""智能交互页面服务（ipage-service）配置常量。

集中管理跨服务地址与可调参数，全部通过环境变量覆盖，禁止硬编码。
Docker 部署时由 start-docker-run.sh 的 -e 覆盖为容器名。

本服务与 situation-service 完全独立：唯一跨服务依赖是 admin-service
（LLM 配置、数据集元数据、只读 SQL 执行）。
"""
import os

# 自举加载 .env：任何入口（含测试）先 import config 也能拿到环境变量。
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 跨服务地址（默认本地开发，Docker 由 -e 覆盖）──
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")

# ── LLM 调用参数 ──
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "24000"))
# 页面 HTML 生成的输出上限（完整单文件页面 ≈30k~50k 字符，比结构化阶段大得多；
# 默认独立于 LLM_MAX_TOKENS，避免结构化阶段的预算把整页输出挤到截断）
PAGE_LLM_MAX_TOKENS = int(os.getenv("IPAGE_PAGE_MAX_TOKENS", "32000"))
# 页面写作阶段的推理开关：大输出阶段默认 disabled，避免思考 token 挤占正文预算
IPAGE_PAGE_THINKING = os.getenv("IPAGE_PAGE_THINKING", "disabled").strip().lower()
if IPAGE_PAGE_THINKING not in ("enabled", "disabled"):
    IPAGE_PAGE_THINKING = "disabled"
# 结构化阶段的推理开关（Planner 规划、Researcher SQL 生成）：输出短且格式固定，
# thinking 只会拉长耗时，还会让「指定 function 的 tool_choice」被服务端拒绝、白跑一次请求
IPAGE_STRUCT_THINKING = os.getenv("IPAGE_STRUCT_THINKING", "disabled").strip().lower()
if IPAGE_STRUCT_THINKING not in ("enabled", "disabled"):
    IPAGE_STRUCT_THINKING = "disabled"
LLM_ALLOWED_HOSTS = tuple(
    host.strip().lower()
    for host in os.getenv(
        "IPAGE_LLM_ALLOWED_HOSTS",
        "api.deepseek.com,localhost,127.0.0.1,::1",
    ).split(",")
    if host.strip()
)

# ── 生成任务资源治理（口径与 situation-service 对齐）──
IPAGE_MAX_INFLIGHT = max(1, int(os.getenv("IPAGE_MAX_INFLIGHT", "8")))
IPAGE_MAX_CONCURRENT = max(1, min(
    int(os.getenv("IPAGE_MAX_CONCURRENT", "2")), IPAGE_MAX_INFLIGHT,
))
IPAGE_MAX_PER_USER = max(1, int(os.getenv("IPAGE_MAX_PER_USER", "2")))
IPAGE_GENERATION_TIMEOUT = max(30, int(os.getenv("IPAGE_GENERATION_TIMEOUT", "480")))
IPAGE_IDEMPOTENCY_TTL = max(60, int(os.getenv("IPAGE_IDEMPOTENCY_TTL", "900")))
# 完成后的 SSE 事件保留时间，支持浏览器断线重连和结果回放。
IPAGE_STREAM_REPLAY_TTL = max(30, int(os.getenv("IPAGE_STREAM_REPLAY_TTL", "300")))

# ── 数据治理：脱敏 / 行数上限 / 地图抽稀 ──
# 单个聚合数据集送给页面的行数上限（图表数据，已由 SQL GROUP BY 收敛）
IPAGE_CHART_ROW_LIMIT = max(10, min(int(os.getenv("IPAGE_CHART_ROW_LIMIT", "1000")), 5000))
# 单个明细数据集（地图/表格）行数上限，超出确定性抽稀/截断
IPAGE_DETAIL_ROW_LIMIT = max(50, min(int(os.getenv("IPAGE_DETAIL_ROW_LIMIT", "3000")), 10000))
# 地图可渲染点/航迹点上限（超过由抽稀器压缩；表格仍可保留 detail 上限）
IPAGE_MAP_POINT_LIMIT = max(100, min(int(os.getenv("IPAGE_MAP_POINT_LIMIT", "2000")), 8000))
# 送给 LLM 的单个数据集行数上限（明细数据在证据摘要之外的采样行）
IPAGE_LLM_EVIDENCE_ROWS = max(0, min(int(os.getenv("IPAGE_LLM_EVIDENCE_ROWS", "200")), 2000))
# 送给 LLM 的数据包 JSON 字符上限（超出先压缩长文本，再降采样）
IPAGE_LLM_BUNDLE_CHARS = max(4000, min(int(os.getenv("IPAGE_LLM_BUNDLE_CHARS", "60000")), 120000))
# 整表回退查询行数上限
IPAGE_DATA_ROW_LIMIT = max(100, min(int(os.getenv("IPAGE_DATA_ROW_LIMIT", "5000")), 10000))

# ── Agent 行为开关 ──
# Guard 校验失败后的 LLM 重写次数（0=不重写直接模板兜底）
IPAGE_REPAIR_MAX_ROUNDS = max(0, min(int(os.getenv("IPAGE_REPAIR_MAX_ROUNDS", "1")), 2))
# LLM 不可用/余额不足时是否允许确定性模板兜底（默认开启，保证不白屏）
IPAGE_TEMPLATE_FALLBACK = os.getenv("IPAGE_TEMPLATE_FALLBACK", "true").strip().lower() in {
    "1", "true", "yes", "on",
}

# ── 安全 ──
# ipage-service 调 admin-service 时使用的服务身份，生产环境必须由 Secret 注入。
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
IPAGE_SENSITIVE_COLUMNS = tuple(
    item.strip().lower()
    for item in os.getenv(
        "IPAGE_SENSITIVE_COLUMNS",
        "姓名,身份证,证件,手机号,电话,邮箱,地址,密码,口令,token,secret,api_key,apikey",
    ).split(",")
    if item.strip()
)

# ── CORS（直连浏览器开发来源；生产走 nginx 同源）──
IPAGE_CORS_ORIGINS = tuple(
    value.strip()
    for value in os.getenv(
        "IPAGE_CORS_ORIGINS",
        "http://localhost:10086,http://127.0.0.1:10086",
    ).split(",")
    if value.strip()
)

# ── SQLite 产物持久化 ──
IPAGE_DB = os.getenv(
    "IPAGE_DB",
    os.path.join(_SERVICE_DIR, "data", "ipage_pages.sqlite3"),
)

# ── HTTP 超时 ──
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))
SQL_QUERY_TIMEOUT = int(os.getenv("SQL_QUERY_TIMEOUT", "120"))

# ── 服务端口（仅健康检查与文档展示用）──
SERVICE_PORT = 10259
