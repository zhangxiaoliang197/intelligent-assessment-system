"""地图标注 Skill 动态加载器。

从 qa-service/skill/ 目录读取 map_*.md 文件，
提取摘要信息组装为 MAP_SKILL_GUIDE 注入 Agent prompt。
Phase 2 LLM Agent 调用 render_map_layer 时作为参考。

加载策略（与 qa-service/main.py 的 _get_skill_catalog 一致）：
- 按需加载：仅在地图相关查询时调用
- mtime 缓存：文件未变则不重读
"""

import os
import logging
from typing import Dict, Optional

logger = logging.getLogger("situation-service")

# 默认 skill 目录（可配置覆盖）
_skill_dir: Optional[str] = None
_skill_cache: Dict[str, tuple] = {}  # path → (mtime, content)


def _parse_skill_header(text: str) -> dict:
    """从 skill .md 文件中提取名称、描述、触发场景。"""
    result = {"name": "", "description": "", "triggers": []}
    current_section = ""

    for line in text.split("\n"):
        stripped = line.strip()

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
                text = cached[1]
            else:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                _skill_cache[path] = (mtime, text)

            header = _parse_skill_header(text)
            if not header.get("name"):
                continue

            name = header["name"]
            desc = header.get("description", "")
            triggers = "、".join(header.get("triggers", [])[:3])

            entry = f"### {name}\n"
            if desc:
                entry += f"{desc}\n"
            if triggers:
                entry += f"适用场景：{triggers}\n"
            entries.append(entry)

    except Exception as e:
        logger.warning("加载 map skill 失败: %s", e)
        return ""

    if not entries:
        return ""

    guide = "## 地图标注能力\n\n"
    guide += "当产出地图图层（render_map_layer）时，支持三种技能，可在同一个 layer 中组合使用：\n\n"
    guide += "\n".join(entries)
    guide += "\n\n坐标统一使用 WGS84，前端自动转 GCJ02。\n"
    guide += "详细输出格式参考各 skill 的 输出格式 代码块。\n"

    return guide
