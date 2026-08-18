"""态势图服务配置常量。

集中管理跨服务地址与可调参数，全部通过环境变量覆盖，禁止硬编码。
Docker 部署时由 start-docker-run.sh 的 -e 覆盖为容器名。
"""
import os

# 自举加载 .env：任何入口（含测试）先 import config 也能拿到环境变量，
# 避免依赖调用方先执行 load_dotenv 的隐式顺序。
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

_SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 跨服务地址（默认本地开发，Docker 由 -e 覆盖）──
# admin-service：LLM 配置 / 地图配置 / 数据集元数据与查询 / 态势产物持久化 CRUD
# 态势图服务仅依赖 admin-service + LLM API（ADR-01/05），不再调用 knowledge/qa/indicator。
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")

# ── LLM 调用参数（与 ontology-service 对齐）──
# max_tokens 为单次输出上限，受模型/部署 max_model_len 限制（本项目 vLLM 上限 393216=384K 为
# 输入+输出总量上限，并非单次输出能力）。态势服务各阶段实际输出 8K-24K token 已足够；
# 全局兜底默认值取 24000，传超过模型 max_output_tokens 的值会被网关拒绝（HTTP 400）。
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "24000"))
LLM_ALLOWED_HOSTS = tuple(
    host.strip().lower()
    for host in os.getenv(
        "SITUATION_LLM_ALLOWED_HOSTS",
        "api.deepseek.com,localhost,127.0.0.1,::1",
    ).split(",")
    if host.strip()
)

# ── 态势生成参数 ──
# LLM 暂不可用时，仍可基于已经取得的真实数据生成基础图表，避免整次任务丢失。
SITUATION_ALLOW_DATA_FALLBACK = os.getenv(
    "SITUATION_ALLOW_DATA_FALLBACK", "true"
).strip().lower() in {"1", "true", "yes", "on"}
# 单个物理数据集送入编排器的最大行数（前端展示用的全量行数上限）。
# admin-service 默认上限 10000（ADMIN_MAX_RESULT_ROWS），此处默认 5000 与之对齐，
# 保证前端图表/地图能拿到全量明细，LLM 仍只取采样行（见 SITUATION_LLM_EVIDENCE_ROWS）。
SITUATION_DATA_ROW_LIMIT = max(1, min(int(os.getenv("SITUATION_DATA_ROW_LIMIT", "5000")), 10000))
# 完成后的 SSE 事件保留时间，支持浏览器断线重连和结果回放。
SITUATION_STREAM_REPLAY_TTL = max(30, int(os.getenv("SITUATION_STREAM_REPLAY_TTL", "300")))

# ── 生成任务资源治理。请求超过在途上限时直接返回 429，单任务超过 deadline 会被
# 取消并持久化为 failed，避免慢数据源或 LLM 长时间占住唯一事件循环。
SITUATION_MAX_INFLIGHT = max(1, int(os.getenv("SITUATION_MAX_INFLIGHT", "8")))
SITUATION_MAX_CONCURRENT = max(1, min(
    int(os.getenv("SITUATION_MAX_CONCURRENT", "2")), SITUATION_MAX_INFLIGHT,
))
SITUATION_MAX_PER_USER = max(1, int(os.getenv("SITUATION_MAX_PER_USER", "2")))
SITUATION_GENERATION_TIMEOUT = max(30, int(os.getenv("SITUATION_GENERATION_TIMEOUT", "480")))
SITUATION_IDEMPOTENCY_TTL = max(60, int(os.getenv("SITUATION_IDEMPOTENCY_TTL", "900")))

# ── Agent 架构参数（态势图 Agent 架构重构方案 v1.1，V2 已是唯一路径）──
# 图表数量下限（v1.1 硬约束：至少 2 个图表）
SITUATION_MIN_CHARTS = max(1, int(os.getenv("SITUATION_MIN_CHARTS", "2")))
# Reflection 循环上限（chart 数值/适配校验失败时的重写轮数）
SITUATION_REFLECTION_MAX_ROUNDS = max(0, min(int(os.getenv("SITUATION_REFLECTION_MAX_ROUNDS", "2")), 4))
# Verifier LLM 通道开关（默认关闭，仅用规则通道；启用后增加 LLM 成本）
SITUATION_VERIFIER_LLM = os.getenv("SITUATION_VERIFIER_LLM", "false").strip().lower() in {"1", "true", "yes", "on"}
# Planner 失败重试上限（共 attempts+1 次机会；2 表示 3 次）
SITUATION_PLANNER_MAX_RETRIES = max(0, min(int(os.getenv("SITUATION_PLANNER_MAX_RETRIES", "2")), 5))

# situation-service 调 admin-service 数据查询专用端点时使用的服务身份。生产环境
# 必须通过 Secret 注入并覆盖默认值；该值不会发送给浏览器或 LLM。
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()

# Direct-browser development origins. Production traffic is normally same-origin through
# nginx; never combine wildcard origins with credentialed CORS.
SITUATION_CORS_ORIGINS = tuple(
    value.strip()
    for value in os.getenv(
        "SITUATION_CORS_ORIGINS",
        "http://localhost:10086,http://127.0.0.1:10086",
    ).split(",")
    if value.strip()
)

# 原始记录不再直接外发。下面两项约束允许送给模型的脱敏/聚合证据大小。
SITUATION_LLM_EVIDENCE_ROWS = max(0, min(
    int(os.getenv("SITUATION_LLM_EVIDENCE_ROWS", "20")), 100,
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

# ── 地图图层渲染上限（全量展示下的前端性能保护）──
# 标点/路线/区域/圆 的渲染上限，超出会在 _sanitize_map_layer 中截断并置 truncated。
# 默认值与全量取数对齐：标点 5000、路线/区域/圆 1000，前端超大数量时再聚合/降级。
SITUATION_MAP_POINT_LIMIT = max(1, int(os.getenv("SITUATION_MAP_POINT_LIMIT", "5000")))
SITUATION_MAP_PATH_LIMIT = max(1, int(os.getenv("SITUATION_MAP_PATH_LIMIT", "1000")))

# ── 草稿态 TTL（秒），跨功能跳转传参用 ──
DRAFT_TTL = int(os.getenv("DRAFT_TTL", "3600"))

# ── 跨服务 HTTP 调用超时（秒）──
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))

# SQL 执行（LLM 生成的精确查询）可能较慢，单独放宽超时（与评估分析对齐）
SQL_QUERY_TIMEOUT = int(os.getenv("SQL_QUERY_TIMEOUT", "120"))

# ── Skill 生命周期 / 收藏 / 使用记录持久化（SQLite）──
SITUATION_SKILL_DB = os.getenv(
    "SITUATION_SKILL_DB",
    os.path.join(_SERVICE_DIR, "data", "situation_skills.sqlite3"),
)
