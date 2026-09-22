"""智能交互页面服务（ipage-service）配置常量。

集中管理跨服务地址与可调参数，全部通过环境变量覆盖，禁止硬编码。
Docker 部署时由 start-docker-run.sh 的 -e 覆盖为容器名。

本服务的跨服务依赖只有两个：
- admin-service（LLM 配置、数据集元数据、只读 SQL 执行）；
- knowledge-service（技能语义匹配所需的文本向量；不可用时自动降级为不套用技能）。
"""
import os

# 自举加载 .env：任何入口（含测试）先 import config 也能拿到环境变量。
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 跨服务地址（默认本地开发，Docker 由 -e 覆盖）──
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
# 技能语料匹配的向量来源（knowledge-service 的通用向量接口）：
# 不可达时匹配自动降级为「不套用技能」，不影响页面生成。
KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:10252")

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

# ── 生成任务资源治理 ──
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

# ── 技能（生成剧本）──
# 技能目录：<服务目录>/config/ipage_skills/<id>/SKILL.md；可用环境变量覆盖为挂载目录
IPAGE_SKILLS_DIR = os.getenv(
    "IPAGE_SKILLS_DIR",
    os.path.join(_SERVICE_DIR, "config", "ipage_skills"),
)
# 是否启用技能匹配（关闭后一律走自由规划，等价改造前行为）
IPAGE_SKILL_MATCH_ENABLED = os.getenv("IPAGE_SKILL_MATCH_ENABLED", "true").strip().lower() in {
    "1", "true", "yes", "on",
}
# 自动套用阈值：最高分达到该值且与次高分差 ≥ MARGIN 才自动套用
IPAGE_SKILL_MATCH_HIGH = float(os.getenv("IPAGE_SKILL_MATCH_HIGH", "0.62"))
# 候选提示阈值：达到该值但未达 HIGH 时只返回候选，由用户手动选择
IPAGE_SKILL_MATCH_LOW = float(os.getenv("IPAGE_SKILL_MATCH_LOW", "0.50"))
# 歧义边际：首位与次位分差小于该值时不自动套用（避免两个互斥技能被误选）
IPAGE_SKILL_MATCH_MARGIN = float(os.getenv("IPAGE_SKILL_MATCH_MARGIN", "0.03"))
# 每个技能参与打分的语料条数（取相似度最高的前 k 条求均值，比单点最大更稳）
IPAGE_SKILL_MATCH_TOP_K = max(1, int(os.getenv("IPAGE_SKILL_MATCH_TOP_K", "3")))
# 技能默认套用策略：off=默认不套用（用户可手动开启）；auto=默认按问题语义自动匹配。
# 默认 off —— 不再"始终自动适配执行"，由用户在页面上显式选择是否使用技能；
# 取值非法（非 off/auto）时回落到 off，避免因配置写错又变回"始终自动套用"。
_SKILL_DEFAULT_MODE_RAW = os.getenv("IPAGE_SKILL_DEFAULT_MODE", "off").strip().lower()
IPAGE_SKILL_DEFAULT_MODE = (
    _SKILL_DEFAULT_MODE_RAW if _SKILL_DEFAULT_MODE_RAW in ("off", "auto") else "off"
)
# 调用向量接口的超时（秒）与单次最大文本条数
IPAGE_SKILL_EMBED_TIMEOUT = max(1, int(os.getenv("IPAGE_SKILL_EMBED_TIMEOUT", "10")))
IPAGE_SKILL_EMBED_MAX_TEXTS = max(1, int(os.getenv("IPAGE_SKILL_EMBED_MAX_TEXTS", "64")))

# ── 注解校验 ──
# 运行期的注解值域采样校验：默认关闭。值域校验已左移到保存期（admin 的 AnnotationValidator），
# 运行期只做零成本的值域漂移告警（用内存中的结果行比对注解值域），打开本开关仅供排障复核。
IPAGE_ANNOTATION_SAMPLE_CHECK = os.getenv(
    "IPAGE_ANNOTATION_SAMPLE_CHECK", "false").strip().lower() in {"1", "true", "yes", "on"}

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

# ── 服务端口（仅健康检查与文档展示用；实际监听端口由启动脚本/容器 CMD 注入）──
SERVICE_PORT = int(os.getenv("IPAGE_SERVICE_PORT", "10257"))
