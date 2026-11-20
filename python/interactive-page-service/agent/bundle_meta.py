"""数据包元信息：运行时数据包需要与页面写作契约对齐的派生字段。

页面写作提示词（prompts.RUNTIME_API_GUIDE）声明了 ``data.mapAvailable``，
业务页面的地图区块会以它为开关。若运行时数据包缺少该字段，模型生成的
``if (data.mapAvailable) { SitMap.render(...) }`` 永远不会执行，表现为
「勾选时标记地图可用、页面地图却是空白」。本模块统一计算该字段，
生成与读取历史页面时都保证数据包带有它。
"""
from typing import Any, Dict, Iterable, List

_GEO_KEYS = ("tracks", "points", "units", "circles")


def has_geo_features(geo: Any) -> bool:
    """geoFeatures 是否包含可上图要素（缺字段或空数组均视为无）。"""
    if not isinstance(geo, dict):
        return False
    return any(isinstance(geo.get(key), list) and bool(geo.get(key)) for key in _GEO_KEYS)


def map_available(entries: Iterable[Dict[str, Any]]) -> bool:
    """数据包内是否存在任一可渲染的地理要素。"""
    return any(
        has_geo_features(entry.get("geoFeatures"))
        for entry in entries
        if isinstance(entry, dict)
    )


def apply_bundle_meta(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """就地补齐数据包的派生字段，返回同一个数据包便于链式使用。"""
    if not isinstance(bundle, dict):
        return bundle
    datasets: List[Dict[str, Any]] = [
        ds for ds in (bundle.get("datasets") or []) if isinstance(ds, dict)
    ]
    bundle["mapAvailable"] = map_available(datasets)
    return bundle
