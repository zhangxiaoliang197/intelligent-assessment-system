"""地图密度分级与航迹抽稀（态势图-排版多样性与产物质量校验方案 §三.②）。

职责（全部确定性规则，零 LLM）：
- 密度分级：按要素数量与空间聚集度给图层打 density 标（sparse/normal/cluster/heavy），
  前端 GeoMap 据此决定是否启用 markercluster 聚合、骨架选型据此给地图主导型加分；
- 航迹抽稀：单条路线点数超阈值时用 Douglas-Peucker 抽稀，保留轨迹形状特征，
  避免几千个点平铺导致地图渲染卡顿与视觉糊成一团。

设计边界：
- 抽稀只作用于"渲染层"路线点序列；点位的 props/业务属性不随抽稀丢失（抽稀的是线不是点）；
- 只加渲染提示字段（density 等），不删除任何业务数据；
- 分级阈值集中在文件头，可调。
"""
import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger("situation-service")

# ── 阈值常量 ──
# 标点数超过该值 → density='cluster'（前端启用 markercluster 聚合）
_CLUSTER_POINT_THRESHOLD = 300
# 总要素（点+线+面+圆）超过该值 → density='heavy'（地图应升为主图）
_HEAVY_FEATURE_THRESHOLD = 2000
# 点位最近邻平均距离（度，约 111km/度）低于该值视为空间聚集 → 聚合
_CLUSTER_NN_DISTANCE = 0.5
# 单条路线点数超过该值时触发 Douglas-Peucker 抽稀
_ROUTE_THIN_THRESHOLD = 500
# 抽稀目标点数
_ROUTE_THIN_TARGET = 500
# 抽稀容差下限（度）：避免小跨度轨迹被过度抽稀
_MIN_TOLERANCE = 0.0005


# ──────────────────────────────────────────────────────────────────
# Douglas-Peucker 航迹抽稀
# ──────────────────────────────────────────────────────────────────

def _perpendicular_distance(point: Dict[str, Any], start: Dict[str, Any], end: Dict[str, Any]) -> float:
    """点到线段（start-end）的垂直距离（经纬度平面近似，小跨度下足够精确）。"""
    x, y = float(point["lng"]), float(point["lat"])
    x1, y1 = float(start["lng"]), float(start["lat"])
    x2, y2 = float(end["lng"]), float(end["lat"])
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    # 投影参数截断到 [0,1]（落在线段内），否则退化为到端点距离
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    proj_x, proj_y = x1 + t * dx, y1 + t * dy
    return math.hypot(x - proj_x, y - proj_y)


def douglas_peucker(points: List[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    """Douglas-Peucker 折线抽稀（迭代实现，避免深递归）。

    Args:
        points: [{"lng", "lat", ...}] 有序点列（保持原顺序）
        tolerance: 容差（度）；越大抽稀越狠

    Returns:
        抽稀后的点列（首尾点必保留，相对顺序不变）
    """
    n = len(points)
    if n <= 2:
        return list(points)
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        max_dist, index = -1.0, -1
        for i in range(first + 1, last):
            dist = _perpendicular_distance(points[i], points[first], points[last])
            if dist > max_dist:
                max_dist, index = dist, i
        if max_dist > tolerance and index > 0:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep) if k]


def _route_span(points: List[Dict[str, Any]]) -> float:
    """路线经纬跨度（取 lng/lat 跨度的较大者，用于自适应容差）。"""
    lngs = [float(p["lng"]) for p in points]
    lats = [float(p["lat"]) for p in points]
    return max(max(lngs) - min(lngs), max(lats) - min(lats))


def _thin_route(route: Dict[str, Any]) -> Dict[str, Any]:
    """单条路线抽稀：超阈值时按跨度自适应容差 Douglas-Peucker 到目标点数。"""
    points = route.get("points")
    if not isinstance(points, list) or len(points) <= _ROUTE_THIN_THRESHOLD:
        return route
    original = len(points)
    span = _route_span(points) or 1.0
    # 初始容差按跨度/目标点数估算；不足则逐步加倍，直到点数落入目标
    tolerance = max(_MIN_TOLERANCE, span / _ROUTE_THIN_TARGET * 0.3)
    thinned = points
    for _ in range(6):
        thinned = douglas_peucker(points, tolerance)
        if len(thinned) <= _ROUTE_THIN_TARGET:
            break
        tolerance *= 2.0
    new_route = dict(route)
    new_route["points"] = thinned
    new_route["thinned"] = {"original": original, "kept": len(thinned)}
    logger.info("航迹抽稀: %s %s → %s 点", route.get("name", ""), original, len(thinned))
    return new_route


# ──────────────────────────────────────────────────────────────────
# 密度分级
# ──────────────────────────────────────────────────────────────────

def _mean_nearest_neighbor_distance(points: List[Dict[str, Any]], sample: int = 200) -> Optional[float]:
    """点位最近邻平均距离（度）。采样上限防 O(n²) 爆炸。"""
    pts = [(float(p["lng"]), float(p["lat"])) for p in points
           if isinstance(p, dict) and p.get("lng") is not None and p.get("lat") is not None]
    if len(pts) < 2:
        return None
    if len(pts) > sample:
        step = len(pts) / sample
        pts = pts[::int(step)]
    total = 0.0
    for i, (x, y) in enumerate(pts):
        best = min(
            math.hypot(x - ox, y - oy)
            for j, (ox, oy) in enumerate(pts) if j != i
        )
        total += best
    return total / len(pts)


def grade_layer_density(layer: Dict[str, Any]) -> Dict[str, Any]:
    """给图层打密度标并执行航迹抽稀（原地增强，返回同一 layer）。

    density 四档：
    - sparse：要素少且分散（正常渲染）
    - normal：默认（正常渲染）
    - cluster：标点多或空间聚集（前端应启用 markercluster 聚合）
    - heavy：总要素极多（骨架选型给地图主导型加分；前端聚合 + 线抽稀双开）
    """
    if not isinstance(layer, dict):
        return layer

    # ① 航迹抽稀先行（抽稀后再计数，密度判级以渲染口径为准）
    routes = layer.get("routes")
    if isinstance(routes, list):
        layer["routes"] = [
            _thin_route(r) if isinstance(r, dict) else r for r in routes
        ]

    points = layer.get("points") if isinstance(layer.get("points"), list) else []
    routes = layer.get("routes") if isinstance(layer.get("routes"), list) else []
    areas = layer.get("areas") if isinstance(layer.get("areas"), list) else []
    circles = layer.get("circles") if isinstance(layer.get("circles"), list) else []
    feature_count = len(points) + len(routes) + len(areas) + len(circles)
    route_point_total = sum(len(r.get("points") or []) for r in routes if isinstance(r, dict))

    density = "normal"
    if feature_count >= _HEAVY_FEATURE_THRESHOLD or route_point_total >= _HEAVY_FEATURE_THRESHOLD:
        density = "heavy"
    elif len(points) >= _CLUSTER_POINT_THRESHOLD:
        density = "cluster"
    else:
        nn = _mean_nearest_neighbor_distance(points)
        if nn is not None and len(points) >= 50 and nn < _CLUSTER_NN_DISTANCE:
            density = "cluster"

    layer["density"] = density
    logger.info(
        "地图密度分级: density=%s points=%s routes=%s(总点 %s) areas=%s circles=%s",
        density, len(points), len(routes), route_point_total, len(areas), len(circles),
    )
    return layer


__all__ = ["grade_layer_density", "douglas_peucker"]
