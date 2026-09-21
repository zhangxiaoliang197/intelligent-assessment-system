"""PageWriter —— 页面生成智能体。

流程：LLM 产出完整单文件 HTML → Guard 规则校验 → 最多 N 轮针对性重写
→ 仍不通过则确定性模板兜底（可配置关闭）。
重新设计（redesign）复用同一数据包，带用户修改意见重新组织呈现与交互，
旧页面 HTML 不回灌模型，仅在重设计失败时用于回退。
"""
import json
import logging
import re
from typing import Any, Dict, List, Tuple

import config
from llm_client import call_llm, LLMTruncatedText
from agent import prompts
from agent.guard import validate_page
from agent.template_render import render_template_page

logger = logging.getLogger("ipage-service")

# 给 LLM 的明细样例行候选（按数据包字符预算逐级缩减）
_SAMPLE_STEPS = [200, 100, 50, 20]

# 输出被 max_tokens 截断时的可读原因（替代只剩「缺少 </html>」的隐晦提示）
_TRUNCATED_ISSUE = ("本次输出被 max_tokens 截断，页面不完整"
                    "（可增大 IPAGE_PAGE_MAX_TOKENS 或精简页面）")

# ```html ... ``` 围栏（语言标记可有可无）
_FENCE_RE = re.compile(r"```(?:html|HTML)?\s*\n(.*?)```", re.DOTALL)
_DOCTYPE_RE = re.compile(r"<!DOCTYPE\s+html", re.IGNORECASE)
_HTML_OPEN_RE = re.compile(r"<html[\s>]", re.IGNORECASE)
_HTML_CLOSE_RE = re.compile(r"</html\s*>", re.IGNORECASE)


def strip_code_fence(text: str) -> str:
    """从 LLM 回复中提取纯 HTML 文档。

    兼容三种不合规返回：
    1. 被 ```html 围栏包裹（可能还带前后缀说明文字）；
    2. 直接输出 HTML 但前后有寒暄/解释文字；
    3. 仅结束围栏缺失。
    提取窗口：第一个 <!DOCTYPE html>/<html> 到最后一个 </html>。
    """
    if not text:
        return ""
    t = text.strip()

    # ① 优先抽取围栏内代码块（取第一个围栏）
    m = _FENCE_RE.search(t)
    if m:
        t = m.group(1).strip()

    # ② 去掉可能残留的零散围栏标记
    t = t.replace("```html", "").replace("```HTML", "").replace("```", "")

    # ③ 截取完整文档区间，丢弃前后散文
    start_m = _DOCTYPE_RE.search(t) or _HTML_OPEN_RE.search(t)
    close_m = None
    closes = list(_HTML_CLOSE_RE.finditer(t))
    if closes:
        close_m = closes[-1]
    if start_m and close_m and close_m.end() >= start_m.start():
        t = t[start_m.start():close_m.end()]
    elif start_m:
        t = t[start_m.start():]

    return t.strip()


def _fit_sample_rows(bundle: Dict[str, Any]) -> int:
    """选择能装进字符预算的最大样例行数。"""
    for n in _SAMPLE_STEPS:
        view = prompts._bundle_view(bundle, n)
        if len(json.dumps(view, ensure_ascii=False, default=str)) <= config.IPAGE_LLM_BUNDLE_CHARS:
            return n
    return _SAMPLE_STEPS[-1]


def _llm_write(messages: List[Dict[str, str]]) -> Tuple[str, bool]:
    """单次 LLM 页面写作调用。

    Returns:
        (html, truncated)：truncated=True 表示响应被 max_tokens 截断
        （内容非空但不完整，必须作为可读原因上报，不能静默当作正常结果）。
    """
    raw = call_llm(
        messages=messages,
        temperature=0.3,
        max_tokens=config.PAGE_LLM_MAX_TOKENS,
        thinking_type=config.IPAGE_PAGE_THINKING,
    )
    truncated = isinstance(raw, LLMTruncatedText)
    return strip_code_fence(raw), truncated


def _check_page(html: str, bundle: Dict[str, Any], truncated: bool) -> List[str]:
    """Guard 校验 + 截断原因合并。"""
    issues = validate_page(html, bundle)
    if truncated:
        issues.append(_TRUNCATED_ISSUE)
    return issues


class PageWriter:
    """页面生成器。"""

    def generate(self, query: str, plan: Dict[str, Any],
                 bundle: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """首次生成；返回 (html, 元信息)。"""
        sample_rows = _fit_sample_rows(bundle)
        messages = prompts.build_page_messages(query, plan, bundle, sample_rows)
        issues: List[str] = []
        html = ""
        try:
            html, truncated = _llm_write(messages)
        except Exception as exc:
            logger.error("PageWriter 首次生成异常: %s", exc)
            truncated = False
            issues.append(f"生成服务异常: {str(exc)[:120]}")

        if html:
            issues = _check_page(html, bundle, truncated)
            if not issues:
                logger.info("PageWriter 首次生成即通过校验，长度=%s", len(html))
                return html, {"usedTemplate": False, "rounds": 0, "issues": []}

        # 校验失败 → 最多 IPAGE_REPAIR_MAX_ROUNDS 轮重写
        for rnd in range(1, config.IPAGE_REPAIR_MAX_ROUNDS + 1):
            logger.warning("页面校验第 %s 轮不通过：%s", rnd, "；".join(issues[:5]))
            try:
                repaired, truncated = _llm_write(messages + prompts.build_repair_messages(issues))
            except Exception as exc:
                logger.error("第 %s 轮重写异常: %s", rnd, exc)
                break
            new_issues = _check_page(repaired, bundle, truncated)
            if not new_issues:
                logger.info("第 %s 轮重写通过校验", rnd)
                return repaired, {"usedTemplate": False, "rounds": rnd, "issues": []}
            html, issues = repaired, new_issues

        # 最终兜底
        if config.IPAGE_TEMPLATE_FALLBACK:
            # 必须打印最终失败原因：循环内只在进入时打印上一轮问题，
            # 不打印这里就等于「重写轮为什么失败」永远没有日志线索
            logger.warning("页面 %s 轮未通过校验，启用确定性模板兜底：%s",
                           config.IPAGE_REPAIR_MAX_ROUNDS, "；".join(issues[:5]))
            tpl = render_template_page(bundle)
            return tpl, {"usedTemplate": True, "rounds": config.IPAGE_REPAIR_MAX_ROUNDS,
                         "issues": issues[:20]}
        raise RuntimeError("页面生成未通过校验且模板兜底已关闭：" + "；".join(issues[:5]))

    def redesign(self, query: str, plan: Dict[str, Any], bundle: Dict[str, Any],
                 previous_html: str, feedback: str) -> Tuple[str, Dict[str, Any]]:
        """带修改意见的重新设计；失败时保留旧页面。

        与首次生成同源：数据包与规划复用父页面，旧页面 HTML 不回灌模型
        （只用于重设计失败时回退），避免模型照抄半截历史页面。
        """
        sample_rows = _fit_sample_rows(bundle)
        base = prompts.build_page_messages(query, plan, bundle, sample_rows)
        messages = base + prompts.build_redesign_messages(feedback)
        issues: List[str] = []
        try:
            html, truncated = _llm_write(messages)
            issues = _check_page(html, bundle, truncated) if html else ["重新设计未返回内容"]
        except Exception as exc:
            html, issues = "", [f"重新设计服务异常: {str(exc)[:120]}"]
        logger.info("重新设计完成反馈=%s 采纳=%s",
                    feedback[:50], bool(html and not issues))

        if html and not issues:
            return html, {"usedTemplate": False, "revised": True, "issues": []}

        for _ in range(config.IPAGE_REPAIR_MAX_ROUNDS):
            try:
                repaired, truncated = _llm_write(messages + prompts.build_repair_messages(issues))
            except Exception as exc:
                logger.warning("重新设计重写异常: %s", exc)
                break
            new_issues = _check_page(repaired, bundle, truncated)
            if not new_issues:
                return repaired, {"usedTemplate": False, "revised": True, "issues": []}
            html, issues = repaired, new_issues

        # 重新设计失败：保留上一版（上一版此前已通过校验或为模板）
        logger.warning("重新设计未通过校验，保留上一版页面：%s", "；".join(issues[:5]))
        return previous_html, {"usedTemplate": False, "revised": False,
                               "issues": issues[:20]}
