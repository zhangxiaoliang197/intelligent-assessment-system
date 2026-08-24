"""布局树后处理 —— 校验 + 确定性修复（态势布局增强）。

设计目标：
- LLM 产出的布局树可能引用不存在的 chartId/layerId/datasetId/列名，
  本模块用纯规则（不调 LLM）做剔除与补齐，保证任何输出都能收敛为安全布局；
- 修复失败（结构整体非法）返回 None，前端回退固定三段布局；
- 布局树只含引用与几何参数，本模块同样不接触任何数据值。

布局树契约（version 1）：
{
  "version": 1,
  "root": {
    "type": "grid",
    "props": {"gap": 12},
    "children": [
      {"type": "block", "span": 3-12, "minHeight": int, "slots": [
        {"kind": "chart", "ref": chartId}
        {"kind": "map", "ref": "*" | layerId}
        {"kind": "narrative_intro"}
        {"kind": "narrative_chart", "ref": chartId}
        {"kind": "map_explanation"}
        {"kind": "metrics", "ref": datasetId, "metrics": [{"label", "column", "agg"}]}
      ]}
    ]
  }
}
"""
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("situation-service")

# 合法 slot kind 白名单
_SLOT_KINDS = {"chart", "map", "narrative_intro", "narrative_chart", "map_explanation", "metrics"}
# 合法聚合函数白名单
_AGGS = {"sum", "count", "max", "min", "avg"}
# span / minHeight 边界
_SPAN_MIN, _SPAN_MAX = 3, 12
_MIN_HEIGHT_MIN, _MIN_HEIGHT_MAX = 120, 1200
# 指标项上限
_MAX_METRIC_ITEMS = 6


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    """把任意值收敛为 [lo, hi] 内的整数，非法取 default。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _sanitize_metric_items(raw_items: Any, columns: Set[str]) -> List[Dict[str, Any]]:
    """清洗单个 metrics slot 的指标项：列名/agg 白名单过滤。"""
    if not isinstance(raw_items, list):
        return []
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        column = str(raw.get("column") or "").strip()
        agg = str(raw.get("agg") or "").strip().lower()
        if agg not in _AGGS:
            continue
        # count 只需数据集存在；其余聚合必须命中真实列名
        if agg != "count" and column not in columns:
            continue
        label = str(raw.get("label") or "").strip()
        if not label:
            label = f"{agg}({column})" if column else agg
        items.append({"label": label, "column": column, "agg": agg})
        if len(items) >= _MAX_METRIC_ITEMS:
            break
    return items


def sanitize_layout(
    raw: Any,
    charts: List[Dict[str, Any]],
    map_layer: Optional[Dict[str, Any]],
    evidences: List[Any],
) -> Optional[Dict[str, Any]]:
    """校验并修复 LLM 布局树。

    Args:
        raw: write_layout 的 LLM 原始返回
        charts: 最终产出图表列表（chartId/datasetRef）
        map_layer: 最终产出地图图层（可为 None）
        evidences: EvidenceStore.list_evidences()（id/columns/rows）

    Returns:
        修复后的布局树 dict；整体非法返回 None。
    """
    if not isinstance(raw, dict):
        return None
    root = raw.get("root")
    if not isinstance(root, dict) or root.get("type") != "grid":
        return None
    children = root.get("children")
    if not isinstance(children, list) or not children:
        return None

    chart_ids = {str(c.get("chartId") or "") for c in charts if c.get("chartId")}
    layer_ids = {str(map_layer.get("layerId") or "")} if map_layer else set()
    # 数据集列名映射（evidence id -> columns 集合），供 metrics 校验
    dataset_columns: Dict[str, Set[str]] = {}
    for ev in evidences:
        dataset_columns[str(ev.id)] = {str(col) for col in (ev.columns or [])}

    has_map = map_layer is not None
    map_block_seen = False
    referenced_charts: Set[str] = set()
    blocks: List[Dict[str, Any]] = []
    dropped = 0

    for child in children:
        if not isinstance(child, dict) or child.get("type") != "block":
            dropped += 1
            continue
        span = _clamp_int(child.get("span"), 12, _SPAN_MIN, _SPAN_MAX)
        min_height = _clamp_int(child.get("minHeight"), 320, _MIN_HEIGHT_MIN, _MIN_HEIGHT_MAX)

        slots: List[Dict[str, Any]] = []
        raw_slots = child.get("slots")
        if not isinstance(raw_slots, list):
            raw_slots = []
        for slot in raw_slots:
            if not isinstance(slot, dict):
                continue
            kind = str(slot.get("kind") or "").strip()
            ref = str(slot.get("ref") or "").strip()
            if kind not in _SLOT_KINDS:
                continue
            if kind == "chart":
                if ref in chart_ids:
                    slots.append({"kind": "chart", "ref": ref})
                    referenced_charts.add(ref)
            elif kind == "map":
                # 无地图产物 / 已有地图块 / ref 非法时丢弃；ref 只接受 "*" 或真实 layerId
                if not has_map or map_block_seen:
                    continue
                if ref != "*" and ref not in layer_ids:
                    continue
                slots.append({"kind": "map", "ref": "*"})
                map_block_seen = True
            elif kind == "narrative_chart":
                if ref in chart_ids:
                    slots.append({"kind": "narrative_chart", "ref": ref})
            elif kind == "metrics":
                columns = dataset_columns.get(ref)
                if columns is None:
                    continue
                items = _sanitize_metric_items(slot.get("metrics"), columns)
                if items:
                    slots.append({"kind": "metrics", "ref": ref, "metrics": items})
            else:
                # narrative_intro / map_explanation 无需 ref
                slots.append({"kind": kind})

        if not slots:
            dropped += 1
            continue
        blocks.append({"type": "block", "span": span, "minHeight": min_height, "slots": slots})

    # ── 完整性补齐：未被引用的产物自动追加全宽块 ──
    # 1) 漏掉的图表 → 追加 chart 块（插在末尾，intro 补块之前）
    missing_charts = [cid for cid in chart_ids if cid not in referenced_charts]
    tail_blocks: List[Dict[str, Any]] = []
    for cid in missing_charts:
        blocks.append({
            "type": "block", "span": 12, "minHeight": 360,
            "slots": [{"kind": "chart", "ref": cid}],
        })
    # 2) 有地图但无地图块 → 追加全宽 map 块
    if has_map and not map_block_seen:
        blocks.append({
            "type": "block", "span": 12, "minHeight": 460,
            "slots": [{"kind": "map", "ref": "*"}],
        })
        map_block_seen = True
    # 3) intro 缺失 → 追加尾部块（放最后，符合"文本在后"时序观感）
    has_intro = any(
        s.get("kind") == "narrative_intro" for b in blocks for s in b.get("slots", [])
    )
    if not has_intro:
        tail_blocks.append({
            "type": "block", "span": 12, "minHeight": 0,
            "slots": [{"kind": "narrative_intro"}],
        })

    all_blocks = blocks + tail_blocks
    if not all_blocks:
        return None

    if dropped or missing_charts:
        logger.info(
            "布局后处理：剔除非法块 %s 个，补齐未引用图表 %s 个",
            dropped, len(missing_charts),
        )

    return {
        "version": 1,
        "root": {
            "type": "grid",
            "props": {"gap": 12},
            "children": all_blocks,
        },
    }


__all__ = ["sanitize_layout"]
