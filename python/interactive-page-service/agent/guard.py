"""Guard —— 页面产物纯规则校验（零 LLM）。

校验四类风险：
1. 结构：完整 HTML 文档、含启动入口、至少一个可视化调用
2. 外联：禁止任何外链脚本/样式/网络 API（CSP 之外的第二道闸）
3. 危险能力：eval / Function / 存储 / cookie / 动态 import / 直接操作 echarts、L
4. 泄密与占位：密钥特征、未填充占位符

返回问题列表（空列表表示通过）。
"""
import re
from typing import Any, Dict, List


def _bundle_has_geo_features(bundle: Any) -> bool:
    """数据包中是否存在非空地理要素（空数组视为没有地图数据）。"""
    if not isinstance(bundle, dict):
        return False
    for dataset in bundle.get("datasets") or []:
        if not isinstance(dataset, dict):
            continue
        geo = dataset.get("geoFeatures")
        if not isinstance(geo, dict):
            continue
        if any(
            isinstance(geo.get(key), list) and bool(geo.get(key))
            for key in ("tracks", "points", "units", "circles")
        ):
            return True
    return False


# 禁止出现的 JS 危险片段（词法级，避免误伤子串：带调用形态）
_FORBIDDEN_JS_PATTERNS = [
    (r"\beval\s*\(", "禁止使用 eval"),
    (r"new\s+Function\b", "禁止使用 new Function"),
    (r"\bfetch\s*\(", "禁止使用 fetch（页面必须离线自包含）"),
    (r"XMLHttpRequest", "禁止使用 XMLHttpRequest"),
    (r"\bWebSocket\b", "禁止使用 WebSocket"),
    (r"navigator\.sendBeacon", "禁止使用 sendBeacon"),
    (r"\.import\s*\(|import\s*\(", "禁止使用动态 import"),
    (r"localStorage", "禁止使用 localStorage"),
    (r"sessionStorage", "禁止使用 sessionStorage"),
    (r"indexedDB", "禁止使用 indexedDB"),
    (r"document\.cookie", "禁止访问 document.cookie"),
    (r"window\.open\s*\(", "禁止使用 window.open"),
    (r"\becharts\s*[.\(]", "禁止直接操作 echarts（请用 SitChart）"),
    (r"(?<![A-Za-z0-9_])L\.map\s*\(", "禁止直接使用 Leaflet L.map（请用 SitMap）"),
    (r"L\.tileLayer\s*\(", "禁止直接使用 Leaflet 瓦片图层（请用 SitMap）"),
]

# 禁止的标签 / 属性
_FORBIDDEN_TAG_PATTERNS = [
    (r"<script[^>]+src\s*=", "禁止 <script src>（运行时由系统统一注入）"),
    (r"<link\b", "禁止 <link> 外链样式"),
    (r"<iframe\b", "禁止内嵌 iframe"),
    (r"<object\b", "禁止 <object>"),
    (r"<embed\b", "禁止 <embed>"),
    (r"<meta[^>]+http-equiv", "禁止 <meta http-equiv>（CSP 由系统统一注入；charset 允许）"),
    (r"\s(?:src|href|poster)\s*=\s*[\"']\s*(?:https?:)?//", "禁止外链资源地址"),
]

# 地图容器（id/class 中含 map 的 div）：无地理要素时不允许出现，避免空白地图占位
_MAP_CONTAINER_RE = re.compile(
    r"<div[^>]+(?:id|class)\s*=\s*[\"'][^\"']*map[^\"']*[\"']", re.IGNORECASE)

# 密钥/凭据特征
_SECRET_PATTERNS = [
    (r"sk-[A-Za-z0-9]{16,}", "疑似 API Key 泄露"),
    (r"Bearer\s+[A-Za-z0-9\-\._]{16,}", "疑似 Bearer 凭据泄露"),
    (r"api[_-]?key\s*[:=]\s*[\"'][^\"']{8,}", "疑似 apiKey 字面量"),
    (r"password\s*[:=]\s*[\"'][^\"']{4,}", "疑似密码字面量"),
]

_PLACEHOLDER_PATTERNS = [
    r"数据待补充", r"待填充", r"TODO", r"lorem ipsum",
]

# 单位符号允许英文（用户口径：单位不算英文）；含数字的编号/型号一律放行
_ALLOWED_UNIT_WORDS = {
    "km", "cm", "mm", "m", "kg", "g", "t", "h", "min", "s", "ms", "kt", "kts",
    "ft", "nmi", "mach", "kph", "mps", "kmh", "rpm", "hz", "khz", "mhz", "ghz",
    "kw", "mw", "kwh", "v", "a", "ma", "db", "px", "kb", "mb", "gb",
}


def _visible_text(html: str) -> str:
    """提取页面可见文本：去掉 script/style 块、注释、标签与 HTML 实体。"""
    text = re.sub(r"<!--.*?-->", " ", html or "", flags=re.S)
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&#?\w+;", " ", text)
    return text


def _english_words(html: str) -> List[str]:
    """找出可见文本中的英文单词（单位与含数字的编号/型号放行）。"""
    found: List[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_\-]*", _visible_text(html)):
        word = match.group(0)
        if len(word) < 2:
            continue
        if any(ch.isdigit() for ch in word):
            continue
        if word.lower() in _ALLOWED_UNIT_WORDS:
            continue
        found.append(word)
    return list(dict.fromkeys(found))


def validate_layout(html: str, bundle: Dict[str, Any]) -> List[str]:
    """无地理数据时的版式校验（仅用于 LLM 生成页，模板兜底不走这里）。

    无地图页面必须采用「KPI 整行 + 图表平铺 + 页面自然滚动」版式。
    以下三类写法说明模型仍在套用「左图表 / 右侧栏」的一屏分栏结构，必须重写：
    1. 使用 --ipage-left 双列主区；
    2. 图表/内容容器内部滚动（overflow:auto、overflow-y:auto、overscroll-behavior）；
    3. 用 --ipage-vh 把内容区固定为一屏高度。

    Args:
        html: LLM 产出的完整 HTML
        bundle: 数据包（用于判断是否存在地理要素）

    Returns:
        中文问题列表（空列表表示版式合规）
    """
    if _bundle_has_geo_features(bundle):
        return []
    text = html or ""
    issues: List[str] = []

    if re.search(r"--ipage-left\s*:", text) or re.search(r"var\(\s*--ipage-left", text):
        issues.append("无地理数据时禁止左右分栏（不要使用 --ipage-left），KPI 与图表应整行平铺")
    if (re.search(r"overflow\s*:\s*(?:auto|scroll)", text, re.I)
            or re.search(r"overflow-y\s*:\s*(?:auto|scroll)", text, re.I)
            or re.search(r"overscroll-behavior", text, re.I)):
        issues.append("无地理数据时禁止容器内部滚动（不要设置 overflow:auto），页面应随内容自然滚动")
    if re.search(r"height\s*:\s*var\(--ipage-vh", text):
        issues.append("无地理数据时禁止固定一屏高度（不要用 --ipage-vh），图表平铺后页面自然滚动")
    if re.search(r"ip-chart-col|ip-main", text):
        issues.append("无地理数据时禁止使用双列布局基础类（.ip-main/.ip-chart-col）")

    return issues


def validate_page(html: str, bundle: Dict[str, Any]) -> List[str]:
    """校验 LLM 页面，返回中文问题列表。

    Args:
        html: LLM 产出的完整 HTML 文本
        bundle: 最终数据包（用于判断可视化数据是否存在）
    """
    issues: List[str] = []
    text = html or ""

    if len(text) < 300:
        issues.append(f"页面内容过短（{len(text)} 字符），疑似生成不完整")

    low = text.lower()
    if "<!doctype html" not in low and "<html" not in low:
        issues.append("缺少 <!DOCTYPE html>/<html> 文档结构")
    if "</html>" not in low:
        issues.append("缺少 </html> 闭合标签")
    if "<body" not in low:
        issues.append("缺少 <body>")
    if "<script" not in low:
        issues.append("缺少业务 <script>")

    # 文档必须以 <!DOCTYPE html>/<html 开头（禁止前言寒暄、Markdown 围栏混入正文）
    head = text.lstrip("\ufeff \t\r\n")[:120].lower()
    if not (head.startswith("<!doctype html") or head.startswith("<html")):
        issues.append("文档必须以 <!DOCTYPE html> 或 <html> 开头（去除前言说明与 Markdown 围栏）")
    if "```" in text:
        issues.append("页面中不允许出现 Markdown 代码围栏标记（```）")

    if "SitApp.bootstrap" not in text:
        issues.append("必须通过 SitApp.bootstrap(function(data){...}) 作为唯一数据入口")
    if not ("SitChart.render" in text or "SitMap.render" in text or "SitTable.render" in text):
        issues.append("页面至少要调用 SitChart.render / SitMap.render / SitTable.render 之一展示数据")
    # 数据包没有地理要素时禁止渲染地图，避免生成空白地图
    has_geo = _bundle_has_geo_features(bundle)
    if "SitMap.render" in text and not has_geo:
        issues.append("数据包没有可渲染的地理要素，页面不允许调用 SitMap.render 或创建地图容器")
    elif not has_geo and _MAP_CONTAINER_RE.search(text):
        issues.append("数据包没有可渲染的地理要素，页面不允许创建地图容器")

    # 页面级时间轴（bundle.timeline）相关的契约校验
    timeline = (bundle or {}).get("timeline") if isinstance(bundle, dict) else None
    if timeline and (timeline.get("buckets") or []):
        if "SitTimeline.render" not in text:
            issues.append("数据包包含统一时间轴，页面必须调用 SitTimeline.render 创建页面级时间轴")
        # 页面时钟与地图内播放器互斥，否则地图与图表会按不同时钟播放
        if re.search(r"playback\s*:\s*(true|\{)", text):
            issues.append("页面级时间轴与 SitMap spec.playback 不能同时使用（避免双时钟）")
        # 图表是否绑定 timeline 由页面按数据口径决定（按需联动），Guard 不强制要求

    # 标签/外链
    for pattern, msg in _FORBIDDEN_TAG_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(msg)

    # 明文 http(s) 字面量（瓦片由运行时托管；注释里的也不允许，避免信息外带通道）
    if re.search(r"[\"']https?://", text):
        issues.append("页面中不允许出现 http(s) 字面量地址（一切资源与数据由系统注入）")

    # 危险 JS
    for pattern, msg in _FORBIDDEN_JS_PATTERNS:
        if re.search(pattern, text):
            issues.append(msg)

    # 密钥
    for pattern, msg in _SECRET_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(msg)

    # 占位符
    for pattern in _PLACEHOLDER_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(f"存在未替换的占位内容：{pattern}")

    # 界面语言：可见文案必须为中文（单位与含数字的编号/型号放行）
    english = _english_words(text)
    if english:
        issues.append("页面可见文字必须为中文，检测到英文：" + "、".join(english[:8]))

    # 数据包非空时，页面不应引用不存在的数据集 id
    datasets = {str(d.get("id")) for d in (bundle.get("datasets") or []) if d.get("id")}
    if datasets:
        referenced = set(re.findall(r"datasets\s*(?:\.\w*\[|\[)[\"']([\w\-]+)[\"']\]", text))
        # 兼容 getById('q1') 之类
        referenced |= set(re.findall(r"getDataset\(\s*[\"']([\w\-]+)[\"']", text))
        missing = {ref for ref in referenced if ref not in datasets}
        if missing:
            issues.append(f"引用了数据包中不存在的数据集 id：{', '.join(sorted(missing))}")

    return issues
