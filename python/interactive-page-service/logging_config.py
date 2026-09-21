"""统一日志配置模块（与其他服务同源的单源副本，参见 scripts/sync-logging-config.sh）。

设计要点
────────
* JSON 结构化输出（python-json-logger），字段与 Java logback 对齐
* dev/prod 双环境，通过 LOG_ENV 环境变量切换
* 幂等：重复调用 setup_logging 不会重复添加 handler
* 接管 uvicorn/fastapi 第三方 logger，避免重复输出
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
        return (
            f"{record_asctime} {color}[{record.levelname}]{_ANSI_RESET} "
            f"[{record.name}] {msg}"
        )


def _resolve_log_dir(service_name: str) -> str:
    """解析日志目录：LOG_DIR 优先，否则落到项目根 logs/{service_name}/。"""
    env_dir = os.getenv("LOG_DIR")
    if env_dir:
        return os.path.join(env_dir, service_name)

    here = os.path.dirname(os.path.abspath(__file__))
    # 向上 2 级：python/{service} → python → 项目根
    project_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(project_root, "logs", service_name)


def _build_json_formatter(service_name: str) -> logging.Formatter:
    """构建 JSON 格式化器，字段与 Java logstash encoder 对齐。"""
    if not _HAS_JSON_LOGGER:
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
        json_ensure_ascii=False,
    )
    try:
        return jsonlogger.JsonFormatter(time_field="timestamp", **kwargs)
    except TypeError:
        return jsonlogger.JsonFormatter(**kwargs)


def _build_file_handler(log_dir: str) -> logging.Handler:
    """构建文件 handler，按 LOG_ROTATION_MODE 选择轮转策略。"""
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
            log_path, when="midnight", interval=1,
            backupCount=retention_days, encoding="utf-8", utc=False,
        )

    handler.setFormatter(_build_json_formatter("ipage-service"))
    return handler


def _build_console_handler(dev: bool) -> logging.Handler:
    """构建控制台 handler。dev 彩色纯文本，prod JSON。"""
    handler = logging.StreamHandler(sys.stdout)
    if dev:
        handler.setFormatter(ColorFormatter("%(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    else:
        handler.setFormatter(_build_json_formatter("ipage-service"))
    return handler


def _takeover_third_party_loggers(level: int) -> None:
    """接管 uvicorn / fastapi 日志，清空其默认 handler，让 root 统一处理。"""
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(level)


def setup_logging(service_name: str = "ipage-service", default_level: str = "INFO") -> logging.Logger:
    """初始化统一日志配置。

    Args:
        service_name: 服务名，写入 JSON 的 service 字段
        default_level: 默认日志级别，被 LOG_LEVEL 环境变量覆盖

    Returns:
        该服务的 logger
    """
    if logging.root.handlers and getattr(logging.root, "_unified_configured", False):
        return logging.getLogger(service_name)

    dev = os.getenv("LOG_ENV", "dev").lower() == "dev"
    level_name = os.getenv("LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)

    if dev and level_name == default_level.upper() and level >= logging.INFO:
        level = logging.DEBUG

    log_dir = _resolve_log_dir(service_name)

    logging.root.handlers = []

    console_handler = _build_console_handler(dev)
    console_handler.setLevel(level)
    logging.root.addHandler(console_handler)

    try:
        file_handler = _build_file_handler(log_dir)
        file_handler.setLevel(level)
        logging.root.addHandler(file_handler)
    except (OSError, PermissionError) as e:
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
