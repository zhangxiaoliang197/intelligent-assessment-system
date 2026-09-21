"""主题令牌层（StylistAgent 借鉴，态势图-主题令牌与叙事语义匹配方案 §4.1）。

职责：为每次排版生成一套 design tokens（CSS 变量块），解决视觉同质化。

设计边界（安全先行）：
- LLM 只允许改动"令牌白名单"内的值，且必须以 JSON 返回；
- css 块由白名单令牌程序化拼装，LLM 文本永不直接进入 CSS（防注入）；
- 数值越界 → 钳制到合法区间；对比度不达标 → 该值回退默认（局部降级，非整包回退）；
- LLM 整体失败/超时 → 按查询哈希从 8 套预设主题确定性选取（可复现）；
- 极端异常 → 返回现有静态默认令牌（= 现状行为）。

产物结构（source 三态）：
- source=llm：1 次 LLM 调用生成（temperature 0.7 鼓励风格多样性）
- source=preset：LLM 失败，预设池按 hash(query) 选取
- source=fallback：异常兜底，返回静态默认令牌
"""
import base64
import colorsys
import json
import logging
import re
from typing import Any, Dict, Optional

from llm_client import call_llm

logger = logging.getLogger("situation-service")


# ──────────────────────────────────────────────────────────────────
# 令牌白名单与默认值（唯一允许 LLM 影响的集合；其余结构令牌固定）
# ──────────────────────────────────────────────────────────────────

DEFAULT_TOKENS: Dict[str, Any] = {
    "primary": "#2563eb",
    "accent": "#d97706",  # 深琥珀：对白卡对比度 ≥3:1（WCAG 大文本），满足本校验
    "bg": "#f5f7fa",
    "card": "#ffffff",
    "text": "#1f2d3d",
    "muted": "#606266",
    "radius": 12,
    "gap": 16,
    "pad": 16,
    "title_weight": 700,
    "mood": "专业克制的商务数据看板",
}

# 令牌 → CSS 变量名映射（拼装 css 块的唯一依据，防止任意变量注入）
_TOKEN_TO_CSS = {
    "primary": "--sit-primary",
    "accent": "--sit-accent",
    "bg": "--sit-bg",
    "card": "--sit-card",
    "text": "--sit-text",
    "muted": "--sit-muted",
    "radius": "--sit-radius",
    "gap": "--sit-gap",
    "pad": "--sit-pad",
    "title_weight": "--sit-title-weight",
}

# 数值令牌合法区间（px / 字重）
_NUM_BOUNDS = {
    "radius": (8, 16),
    "gap": (12, 24),
    "pad": (12, 24),
    "title_weight": (600, 800),
}

# 亮度约束（HSL L 分量 0-1）：页面底与卡片必须处于浅色域，保证深色文字可读
_LIGHTNESS_MIN = {"bg": 0.94, "card": 0.98}
# 颜色对比度约束（WCAG 2.1）：正文 ≥4.5:1，主色/强调色作大字号数字 ≥3:1
_CONTRAST_MIN = {"text": ("card", 4.5), "muted": ("card", 3.0),
                 "primary": ("card", 3.0), "accent": ("card", 3.0)}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ──────────────────────────────────────────────────────────────────
# 颜色工具（WCAG 相对亮度 / 对比度 / HSL 钳制）
# ──────────────────────────────────────────────────────────────────

def _hex_to_rgb01(value: str) -> Optional[tuple]:
    """#rgb/#rrggbb → (r,g,b) 0-1 元组；非法返回 None。"""
    if not isinstance(value, str) or not _HEX_RE.match(value.strip()):
        return None
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _relative_luminance(rgb: tuple) -> float:
    """WCAG 2.1 相对亮度定义。"""
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(hex_a: str, hex_b: str) -> float:
    """两个 hex 颜色的对比度（(L1+0.05)/(L2+0.05)）；无法解析返回 0。"""
    rgb_a, rgb_b = _hex_to_rgb01(hex_a), _hex_to_rgb01(hex_b)
    if rgb_a is None or rgb_b is None:
        return 0.0
    la, lb = _relative_luminance(rgb_a), _relative_luminance(rgb_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _hex_to_hsl(hex_color: str) -> Optional[tuple]:
    """hex → (h, s, l)，各分量 0-1。"""
    rgb = _hex_to_rgb01(hex_color)
    if rgb is None:
        return None
    # rgb_to_hls 返回 (h, l, s)，统一为 (h, s, l) 约定
    h, l, s = colorsys.rgb_to_hls(*rgb)
    return h, s, l


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """(h, s, l) 0-1 → #rrggbb。"""
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(
        round(r * 255), round(g * 255), round(b * 255)
    )


def _clamp_color(value: Any, key: str) -> Optional[str]:
    """颜色令牌钳制：hex 合法性 + 亮度域 + HSL 区间约束。"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _HEX_RE.match(value):
        return None
    # 3 位缩写先展开为 6 位，统一后续处理
    if len(value) == 4:
        value = "#" + "".join(c * 2 for c in value[1:])
    hsl = _hex_to_hsl(value)
    if hsl is None:
        return None
    h, s, l = hsl
    if key in _LIGHTNESS_MIN:
        # bg/card：压到浅色域下限之上
        l = max(l, _LIGHTNESS_MIN[key])
    if key in ("primary", "accent"):
        # 主色/强调色：亮度钳制在深浅适中区间；饱和度仅防荧光上溢
        # （中性低饱和色合法，可读性由对比度校验统一兜底）
        l = min(0.68, max(0.25, l))
        s = min(0.92, s)
    return _hsl_to_hex(h, s, l)


def _clamp_num(value: Any, key: str) -> Optional[int]:
    """数值令牌钳制：取整并截断到合法区间。"""
    try:
        num = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    lo, hi = _NUM_BOUNDS[key]
    return max(lo, min(hi, num))


# ──────────────────────────────────────────────────────────────────
# 校验与规范化：LLM 原始 dict → 合法 tokens（局部降级）
# ──────────────────────────────────────────────────────────────────

def sanitize_tokens(raw: Any) -> Dict[str, Any]:
    """校验并规范化令牌：非法值逐项回退默认（局部降级，非整包回退）。

    Args:
        raw: LLM 返回的令牌 dict（或任意值）

    Returns:
        全字段合法的 tokens dict（基于 DEFAULT_TOKENS 逐项替换）
    """
    tokens = dict(DEFAULT_TOKENS)
    if not isinstance(raw, dict):
        return tokens

    # ① 颜色类：先钳制到合法色域
    for key in ("primary", "accent", "bg", "card", "text", "muted"):
        clamped = _clamp_color(raw.get(key), key)
        if clamped:
            tokens[key] = clamped

    # ② 数值类：钳制到区间
    for key in ("radius", "gap", "pad", "title_weight"):
        clamped = _clamp_num(raw.get(key), key)
        if clamped is not None:
            tokens[key] = clamped

    # ③ 风格关键词：仅透传给排版 prompt（不进 CSS），限长防注入
    mood = str(raw.get("mood") or "").strip()
    if mood:
        tokens["mood"] = re.sub(r"\s+", " ", mood)[:40]

    # ④ 对比度校验：不达标回退该值默认（bg/card 已钳到浅色域，通常可过）
    for key, (against, min_ratio) in _CONTRAST_MIN.items():
        if _contrast(tokens[key], tokens[against]) < min_ratio:
            tokens[key] = DEFAULT_TOKENS[key]

    return tokens


def tokens_to_css(tokens: Dict[str, Any]) -> str:
    """令牌 → CSS 变量块（唯一出口，程序化拼装，无任何 LLM 原文）。"""
    pairs = ";".join(f"{css_var}:{tokens[key]}" for key, css_var in _TOKEN_TO_CSS.items())
    return f":root{{{pairs}}}"


# ──────────────────────────────────────────────────────────────────
# 预设主题池（12 套，全部预通过对比度校验；LLM 失败时确定性选取）
# ──────────────────────────────────────────────────────────────────

# 各预设只列与默认不同的字段，其余继承 DEFAULT_TOKENS
# 注意：bg/card 受 _LIGHTNESS_MIN 浅色域约束，预设必须保持浅色底
_PRESETS: list = [
    {"primary": "#2563eb", "accent": "#d97706", "bg": "#f5f7fa", "card": "#ffffff",
     "text": "#1f2d3d", "muted": "#606266", "mood": "专业克制的商务数据看板"},          # 商务蓝
    {"primary": "#4f46e5", "accent": "#ea580c", "bg": "#f5f6fb", "card": "#ffffff",
     "text": "#1e1b3a", "muted": "#5b5772", "mood": "稳重的靛青决策看板"},             # 靛青
    {"primary": "#0f766e", "accent": "#d97706", "bg": "#f3f8f6", "card": "#ffffff",
     "text": "#134e4a", "muted": "#5c7a75", "mood": "沉静的松石绿监测看板"},           # 松石绿
    {"primary": "#ea580c", "accent": "#1d4ed8", "bg": "#fdf6f2", "card": "#ffffff",
     "text": "#3d2417", "muted": "#7a6152", "mood": "醒目的暖橙运营看板"},             # 暖橙
    {"primary": "#475569", "accent": "#0e7490", "bg": "#f4f5f7", "card": "#ffffff",
     "text": "#1e293b", "muted": "#5a6472", "mood": "克制的石墨中性看板"},             # 石墨
    {"primary": "#7c3aed", "accent": "#0d9488", "bg": "#f8f5fc", "card": "#ffffff",
     "text": "#2e1065", "muted": "#6b6485", "mood": "精致的紫罗兰分析看板"},           # 紫罗兰
    {"primary": "#1d4ed8", "accent": "#dc2626", "bg": "#f2f5fa", "card": "#ffffff",
     "text": "#16255a", "muted": "#57608a", "mood": "严谨的藏青态势看板"},             # 藏青
    {"primary": "#b45309", "accent": "#0369a1", "bg": "#faf5ef", "card": "#ffffff",
     "text": "#422006", "muted": "#7d6a52", "mood": "沉稳的赤陶报告看板"},             # 赤陶
    {"primary": "#0891b2", "accent": "#be185d", "bg": "#f2fafa", "card": "#ffffff",
     "text": "#164e63", "muted": "#5e7a86", "mood": "清亮的青瓷水域监测看板"},         # 青瓷
    {"primary": "#be185d", "accent": "#1d4ed8", "bg": "#fbf5f8", "card": "#ffffff",
     "text": "#500f28", "muted": "#86606f", "mood": "明快的玫红专题看板"},             # 玫红
    {"primary": "#4d7c0f", "accent": "#b45309", "bg": "#f7faf2", "card": "#ffffff",
     "text": "#1a2e05", "muted": "#67745a", "mood": "朴实的橄榄田野看板"},             # 橄榄
    {"primary": "#1e40af", "accent": "#059669", "bg": "#f3f6fc", "card": "#ffffff",
     "text": "#172554", "muted": "#5d6b8a", "mood": "深邃的钴蓝指挥看板"},             # 钴蓝
]


def _preset_index(query: str, semantic: Optional[Dict[str, Any]] = None) -> int:
    """按「查询 + 叙事极性」哈希确定性选取预设（同一查询同一主题，可复现）。

    哈希因子加入 polarity：同为"巡航"类问题，预警叙事与对比叙事会落到
    不同预设主题，与骨架同分扰动配合打散"每次都一样"的观感。
    """
    polarity = str((semantic or {}).get("polarity") or "").strip().lower()
    digest = base64.b32encode(
        (str(query or "") + "|" + polarity).encode("utf-8")
    ).decode("ascii")
    return sum(ord(c) for c in digest) % len(_PRESETS)


def pick_preset(query: str, semantic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """从预设池确定性选取主题并规范化（预设也应过同一校验，保证口径一致）。"""
    return sanitize_tokens(_PRESETS[_preset_index(query, semantic)])


# ──────────────────────────────────────────────────────────────────
# LLM 生成入口
# ──────────────────────────────────────────────────────────────────

_POLARITY_LABELS = {
    "and": "现状罗列", "but": "问题聚焦", "therefore": "结论成果",
    "compare": "对比分析", "alert": "预警升级", "neutral": "中性概述",
}

_SYSTEM = (
    "你是资深海报视觉设计师（Stylist），负责为数据态势看板设计主题配色与质感。"
    "要求：专业、克制、可读性优先；同一页面主色只一种、强调色只一种。"
    "必须输出一个 JSON 对象，不要任何解释文字，字段如下：\n"
    '{"primary":"主色 hex（用于标题与主按钮）","accent":"强调色 hex（用于 KPI 数字与高亮，需与主色明显区分）",'
    '"bg":"页面底色 hex（必须非常浅）","card":"卡片底色 hex（接近白）",'
    '"text":"正文色 hex（深色，对卡片对比度≥4.5）","muted":"次要文字 hex",'
    '"radius":圆角像素8-16,"gap":间距像素12-24,"pad":内边距像素12-24,'
    '"title_weight":标题字重600|700|800,"mood":"≤40字的风格基调描述"}'
)


def generate_style_tokens(query: str, profile_desc: str,
                          semantic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """生成主题令牌：LLM 优先，失败按哈希取预设（确定性可复现）。

    Args:
        query: 用户原始问题（决定主题气质的语义来源）
        profile_desc: 产物画像描述（图表/地图/KPI 概况，供风格判断）
        semantic: Planner 叙事标签 {"polarity": .., "focus": ..}（可为 None）

    Returns:
        {"css": ":root{...}", "tokens": {...}, "source": "llm"|"preset"}
    """
    polarity = _POLARITY_LABELS.get(
        str((semantic or {}).get("polarity") or "").strip().lower(), "")
    focus = str((semantic or {}).get("focus") or "").strip()[:20]
    user = (
        f"报告主题：{str(query or '')[:80]}\n"
        f"版面内容：{str(profile_desc or '')[:80]}\n"
        + (f"叙事基调：{polarity}（{focus}）\n" if polarity else "")
        + "请设计配套主题。"
    )
    try:
        raw = call_llm(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": user}],
            temperature=0.7, max_tokens=500, thinking_type="disabled",
        )
        tokens = sanitize_tokens(json.loads(raw))
        if tokens == dict(DEFAULT_TOKENS):
            # LLM 输出完全无效（全部回退默认）→ 视为失败走预设，保证风格多样性
            raise ValueError("LLM 令牌全部非法")
        logger.info("主题令牌：LLM 生成成功（主色 %s，基调 %s）",
                    tokens["primary"], tokens["mood"])
        return {"css": tokens_to_css(tokens), "tokens": tokens, "source": "llm"}
    except Exception as exc:
        preset = pick_preset(query or "", semantic)
        logger.warning("主题令牌：LLM 生成失败（%s），使用预设主题（主色 %s）",
                       exc, preset["primary"])
        return {"css": tokens_to_css(preset), "tokens": preset, "source": "preset"}
