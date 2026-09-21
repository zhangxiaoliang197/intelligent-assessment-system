"""进程内缓存的统一注册表。

背景：ipage 的元数据相关缓存分散在多个模块（维度关系图、维度值采样、机型档案
索引、通用维度 enrich 索引），都是模块级 dict 且没有清空入口——注解在
admin 侧改完，不重启 ipage 就看不到效果（用户会误以为自己注解写错了）。

设计口径：
1. 每个缓存在自己模块内注册一个清理函数，签名 ``(database_id, tables) -> int``，
   返回清理掉的条目数；tables 为空表示该数据源全量清理；
2. 清理入口按 database_id + 表名精确定位，避免"改一列注解导致全库重新采样"
   （采样是要对每列打 GROUP BY 的 SQL 的）；
3. 新增缓存的模块必须在此注册，否则注解变更后该缓存仍持旧值——这是本模块
   存在的唯一理由，注册即声明"我会因注解变化而失效"。
"""
import logging
import threading
from typing import Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("ipage-service")

# 缓存名 → 清理函数
_registry: Dict[str, Callable[[Optional[str], Optional[Sequence[str]]], int]] = {}
_registry_lock = threading.Lock()

_bootstrapped = False


def register_cache(
    name: str,
    clear_fn: Callable[[Optional[str], Optional[Sequence[str]]], int],
) -> None:
    """注册一个缓存清理函数（重复注册以最后一次为准，便于测试替换）。"""
    with _registry_lock:
        _registry[name] = clear_fn


def registered_caches() -> List[str]:
    """已注册的缓存名列表（按名称排序，供日志与自检使用）。"""
    _ensure_registered()
    with _registry_lock:
        return sorted(_registry.keys())


def invalidate(
    database_id: Optional[str] = None,
    tables: Optional[Sequence[str]] = None,
) -> Dict[str, int]:
    """清理全部已注册缓存。

    Args:
        database_id: 数据源标识；空表示不限数据源
        tables: 发生变更的表名列表；空表示该数据源全量清理

    Returns:
        {缓存名: 清理条目数}；某缓存清理抛异常时记为 -1 并记录日志，
        不因为一个缓存失败而放弃其余缓存。
    """
    _ensure_registered()
    with _registry_lock:
        snapshot = dict(_registry)

    result: Dict[str, int] = {}
    for name, clear_fn in snapshot.items():
        try:
            result[name] = int(clear_fn(database_id, tables))
        except Exception as exc:  # 单个缓存失败不阻断其余清理
            logger.warning("清理缓存 %s 失败: %s", name, exc)
            result[name] = -1
    logger.info("元数据缓存清理完成: databaseId=%s tables=%s result=%s",
                database_id or "*", list(tables or []) or "*", result)
    return result


def _ensure_registered() -> None:
    """惰性导入持有缓存的模块，触发其 register_cache（避免循环导入）。"""
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    try:
        from agent import dimension_graph, researcher  # noqa: F401  触发注册
    except Exception as exc:  # 测试或裁剪部署下允许缺模块
        logger.warning("初始化缓存注册表时加载模块失败: %s", exc)


def reset_for_test() -> None:
    """测试用：清空注册表，便于隔离用例。"""
    global _bootstrapped
    with _registry_lock:
        _registry.clear()
    _bootstrapped = False
