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
