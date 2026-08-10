"""统一日志配置模块（单源文件，通过 scripts/sync-logging-config.sh 分发到各服务）。

设计要点
────────
* JSON 结构化输出（python-json-logger），字段与 Java logback 对齐
* dev/prod 双环境，通过 LOG_ENV 环境变量切换
* 幂等：重复调用 setup_logging 不会重复添加 handler
* 接管 uvicorn/fastapi 第三方 logger，避免重复输出

环境变量
────────
* LOG_ENV            dev | prod（默认 dev）
* LOG_LEVEL          DEBUG | INFO | WARN | ERROR（默认 INFO）
* LOG_DIR            日志根目录（Docker 内 /app/logs；本地默认项目根/logs）
* LOG_RETENTION_DAYS 生产环境日志保留天数（默认 14）
* LOG_MAX_SIZE_MB    单文件最大体积 MB（按大小轮转时生效，默认 100）
* LOG_ROTATION_MODE  time | size（默认 time；qa-service 等高频服务建议 size）
"""
import logging
import logging.handlers
import os
import sys

try:
    from pythonjsonlogger import jsonlogger
    _HAS_JSON_LOGGER = True
except ImportError:
    _HAS_JSON_LOGGER = False


# ── ANSI 颜色（dev 环境控制台彩色输出，不引入 colorlog 依赖） ──
_ANSI_COLORS = {
    "DEBUG": "\033[36m",     # 青色
    "INFO": "\033[32m",      # 绿色
    "WARNING": "\033[33m",   # 黄色
    "ERROR": "\033[31m",     # 红色
    "CRITICAL": "\033[35m",  # 紫色
}
_ANSI_RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    """dev 环境控制台彩色纯文本格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        color = _ANSI_COLORS.get(record.levelname, "")
        record_asctime = self.formatTime(record, self.datefmt)
        msg = super().format(record)
        # 仅对 level 着色，避免全行彩色干扰
        return (
            f"{record_asctime} {color}[{record.levelname}]{_ANSI_RESET} "
            f"[{record.name}] {msg}"
        )


def _resolve_log_dir(service_name: str) -> str:
    """解析日志目录。

    优先级：
      1. LOG_DIR 环境变量（Docker 内由 Dockerfile 注入 /app/logs）
      2. 本地开发：从本文件位置向上 3 级定位项目根，拼 logs/{service_name}/

    本文件位于 python/{service}/logging_config.py（同步后的副本），
    向上 3 级 = python/{service} → python → 项目根。
    """
    env_dir = os.getenv("LOG_DIR")
    if env_dir:
        return os.path.join(env_dir, service_name)

    here = os.path.dirname(os.path.abspath(__file__))
    # 向上 2 级：python/{service}/logging_config.py → python/{service} → python → 项目根
    # 兼容 common 源目录（python/common → python → 项目根，同样是 2 级）
    project_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(project_root, "logs", service_name)


def _build_json_formatter(service_name: str) -> logging.Formatter:
    """构建 JSON 格式化器，字段与 Java logstash encoder 对齐。

    兼容 python-json-logger 2.x 和 3.x（3.x 移除了 time_field 参数）。
    """
    if not _HAS_JSON_LOGGER:
        # 降级：python-json-logger 未安装时用纯文本（不应出现在生产环境）
        return logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    kwargs = dict(
        fmt=(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "%(module)s %(lineno)s %(funcName)s %(threadName)s %(process)d"
        ),
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
            "threadName": "thread",
            "lineno": "line",
            "funcName": "funcName",
        },
        static_fields={"service": service_name},
        json_ensure_ascii=False,  # 中文不转义
    )
    # time_field 仅 2.x 支持，3.x 已移除，用 try 兼容
    try:
        return jsonlogger.JsonFormatter(time_field="timestamp", **kwargs)
    except TypeError:
        return jsonlogger.JsonFormatter(**kwargs)


def _build_file_handler(log_dir: str, service_name: str) -> logging.Handler:
    """构建文件 handler，按 LOG_ROTATION_MODE 选择轮转策略。

    * time（默认）：TimedRotatingFileHandler，按日午夜轮转，保留 LOG_RETENTION_DAYS 天
    * size：RotatingFileHandler，单文件 LOG_MAX_SIZE_MB，保留 LOG_RETENTION_DAYS 个备份
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "app.log")
    mode = os.getenv("LOG_ROTATION_MODE", "time").lower()
    retention_days = int(os.getenv("LOG_RETENTION_DAYS", "14"))
    max_size_mb = int(os.getenv("LOG_MAX_SIZE_MB", "100"))

    if mode == "size":
        handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=retention_days,
            encoding="utf-8",
        )
    else:
        handler = logging.handlers.TimedRotatingFileHandler(
            log_path,
            when="midnight",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
            utc=False,
        )

    handler.setFormatter(_build_json_formatter(service_name))
    return handler


def _build_console_handler(dev: bool, service_name: str) -> logging.Handler:
    """构建控制台 handler。dev 彩色纯文本，prod JSON。"""
    handler = logging.StreamHandler(sys.stdout)
    if dev:
        handler.setFormatter(ColorFormatter(
            "%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    else:
        handler.setFormatter(_build_json_formatter(service_name))
    return handler


def _takeover_third_party_loggers(level: int) -> None:
    """接管 uvicorn / fastapi 日志，清空其默认 handler，让 root 统一处理。"""
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers = []        # 移除自带 handler，避免重复输出
        lg.propagate = True     # 冒泡到 root
        lg.setLevel(level)


def setup_logging(service_name: str, default_level: str = "INFO") -> logging.Logger:
    """初始化统一日志配置。

    Args:
        service_name: 服务名（如 "qa-service"），写入 JSON 的 service 字段
        default_level: 默认日志级别，被 LOG_LEVEL 环境变量覆盖

    Returns:
        该服务的 root logger
    """
    # ── 幂等：已配置过则直接返回 ──
    if logging.root.handlers and getattr(logging.root, "_unified_configured", False):
        return logging.getLogger(service_name)

    dev = os.getenv("LOG_ENV", "dev").lower() == "dev"
    level_name = os.getenv("LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)

    # dev 环境默认降到 DEBUG（除非显式指定 LOG_LEVEL）
    if dev and level_name == default_level.upper() and level >= logging.INFO:
        level = logging.DEBUG

    log_dir = _resolve_log_dir(service_name)

    # ── 清空 root 现有 handler（避免 basicConfig 残留） ──
    logging.root.handlers = []

    # ── 控制台 handler ──
    console_handler = _build_console_handler(dev, service_name)
    console_handler.setLevel(level)
    logging.root.addHandler(console_handler)

    # ── 文件 handler ──
    try:
        file_handler = _build_file_handler(log_dir, service_name)
        file_handler.setLevel(level)
        logging.root.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        # 日志目录不可写时仅用控制台，不阻断服务启动
        logging.root.addHandler(console_handler)
        print(f"[logging_config] 警告: 无法创建日志文件 {log_dir}: {e}", file=sys.stderr)

    logging.root.setLevel(level)
    logging.root._unified_configured = True  # type: ignore[attr-defined]

    _takeover_third_party_loggers(level)

    root_logger = logging.getLogger(service_name)
    root_logger.info(
        "统一日志已初始化: service=%s, env=%s, level=%s, dir=%s",
        service_name, "dev" if dev else "prod", level_name, log_dir,
    )
    return root_logger
