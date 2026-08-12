"""地图标注 Skill 动态加载器。

从 qa-service/skill/ 目录读取 map_*.md 文件，
提取摘要信息 + JSON 格式模板组装为 MAP_SKILL_GUIDE 注入 Agent prompt。
Phase 2 LLM Agent 调用 render_map_layer 时作为参考。

加载策略（与 qa-service/main.py 的 _get_skill_catalog 一致）：
- 按需加载：仅在地图相关查询时调用
- mtime 缓存：文件未变则不重读
- 同时提取格式模板：确保 LLM 知道每种标注的精确 JSON 字段
"""

import os
import logging
from typing import Dict, Optional

logger = logging.getLogger("situation-service")

# 默认 skill 目录（可配置覆盖）
_skill_dir: Optional[str] = None
_skill_cache: Dict[str, tuple] = {}  # path → (mtime, content, summary)


def _parse_skill_full(text: str) -> dict:
    """从 skill .md 文件中提取名称、描述、触发场景、JSON 格式模板。"""
    result = {"name": "", "description": "", "triggers": [], "formats": []}
    current_section = ""
    in_code_block = False
    in_map_annotations = False
    in_json_block = False  # 通用 JSON 代码块
    code_lines = []

    for line in text.split("\n"):
        stripped = line.strip()

        # 跟踪代码块
        if stripped.startswith("```"):
            if in_code_block:
                # 结束代码块，收集内容
                if code_lines:
                    code_str = "\n".join(code_lines)
                    if in_map_annotations or in_json_block:
                        result["formats"].append(code_str)
                in_code_block = False
                in_map_annotations = False
                in_json_block = False
                code_lines = []
            else:
                # 开始代码块
                in_code_block = True
                lang = stripped[3:].strip()
                if "map_annotations" in lang:
                    in_map_annotations = True
                elif "json" in lang.lower():
                    in_json_block = True
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # 提取名称（第一个 # 标题）
        if stripped.startswith("# ") and not result["name"]:
            result["name"] = stripped[2:].strip()
            continue

        # 跟踪当前节
        if stripped.startswith("## "):
            section_title = stripped[3:].strip()
            if "描述" in section_title:
                current_section = "desc"
            elif "触发" in section_title:
                current_section = "trigger"
            elif "输出格式" in section_title:
                current_section = "format"
            else:
                current_section = ""
            continue

        if not stripped:
            continue

        if current_section == "desc":
            if not result["description"]:
                result["description"] = stripped

        elif current_section == "trigger":
            if stripped.startswith("- "):
                trigger = stripped[2:].split("（")[0].split("：")[0].strip().rstrip("、")
                result["triggers"].append(trigger)

    return result


def _convert_format_for_situation(fmt: str) -> str:
    """将 qa-service 的 map_annotations 格式转为 situation 的 points/routes/areas/circles 格式。
    
    qa-service 格式:
      { "markers": [...], "routes": [...], "areas": [...] }
    
    situation 格式:
      { "points": [...], "routes": [...], "areas": [...], "circles": [...] }
    
    关键差异:
    - markers → points
    - areas 中的 shape/circle 配置保留
    """
    import json as _json
    try:
        data = _json.loads(fmt)
    except Exception:
        # 无法解析，保持原样
        return fmt

    converted = {}
    if "markers" in data:
        # markers → points (situation 字段名)
        converted["points"] = data["markers"]
    if "routes" in data:
        converted["routes"] = data["routes"]
    if "areas" in data:
        # areas 中的 polygon/circle 原样保留
        converted["areas"] = data["areas"]
        # 同时提取 circles（如果 areas 中有 shape: "circle"）
        circles = [a for a in data["areas"] if a.get("shape") == "circle"]
        if circles:
            converted["circles"] = circles

    return _json.dumps(converted, ensure_ascii=False, indent=2)


def load_map_skill_guide(skill_dir: str = None) -> str:
    """从 skill 目录动态加载地图标注能力指南。

    Args:
        skill_dir: skill .md 文件所在目录，默认自动推断

    Returns:
        格式化的 MAP_SKILL_GUIDE 文本，无可用 skill 时返回空字符串
    """
    global _skill_dir

    if skill_dir:
        _skill_dir = skill_dir

    if not _skill_dir:
        # 自动推断：相对于 situation-service 同级目录 qa-service/skill
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _skill_dir = os.path.join(base, "qa-service", "skill")

    if not os.path.isdir(_skill_dir):
        logger.debug("skill 目录不存在: %s", _skill_dir)
        return ""

    entries = []
    try:
        for filename in sorted(os.listdir(_skill_dir)):
            if not filename.startswith("map_") or not filename.endswith(".md"):
                continue

            path = os.path.join(_skill_dir, filename)
            mtime = os.path.getmtime(path)
            cached = _skill_cache.get(path)

            # mtime 缓存
            if cached and cached[0] == mtime:
                summary = cached[2] if len(cached) > 2 else None
                if summary is None:
                    # 旧缓存无 summary，重新解析
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                    summary = _parse_skill_full(text)
                    _skill_cache[path] = (mtime, text, summary)
            else:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                summary = _parse_skill_full(text)
                _skill_cache[path] = (mtime, text, summary)

            if not summary.get("name"):
                continue

            name = summary["name"]
            desc = summary.get("description", "")
            triggers = "、".join(summary.get("triggers", [])[:3])
            formats = summary.get("formats", [])

            entry = f"### {name}\n"
            if desc:
                entry += f"描述：{desc}\n"
            if triggers:
                entry += f"适用场景：{triggers}\n"
            # 注入 JSON 格式模板（转为 situation 的字段名）
            for fmt in formats[:2]:  # 最多 2 个格式示例
                converted = _convert_format_for_situation(fmt)
                entry += f"输出格式：\n```json\n{converted}\n```\n"
            entries.append(entry)

    except Exception as e:
        logger.warning("加载 map skill 失败: %s", e)
        return ""

    if not entries:
        return ""

    guide = "## 地图标注能力\n\n"
    guide += "当产出地图图层时，支持以下技能，可在同一个 layer 中组合使用 points/routes/areas/circles：\n\n"
    guide += "\n".join(entries)
    guide += "\n坐标统一使用 WGS84，前端自动转 GCJ02。\n"
    guide += "输出为 JSON 对象：{ \"layerId\": \"main\", \"points\": [...], \"routes\": [...], \"areas\": [...], \"circles\": [...], \"layerConfig\": {} }\n"

    return guide
