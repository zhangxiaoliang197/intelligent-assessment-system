"""单 chart PNG 截图渲染 —— 复用 visual_judge 的 playwright + echarts 单例。

设计目标（参见方案文档 §3.3.1）：
- 复用 visual_judge._load_echarts_js / _get_browser / _browser_lock，不新建第二套 playwright 实例
- 单图 HTML 模板：单容器 + setOption(option)，视口 640x480（VLM 看单图足够）
- 失败项返回 None，Critic 仅看文本信号决策（行为与现状兼容）
- playwright 不可用时整体返回 None 列表，由调用方降级

注意：sync_playwright 不允许运行在 asyncio 事件循环内，必须经 asyncio.to_thread 隔离。
"""
import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from agent import visual_judge

logger = logging.getLogger("situation-service")


# 单图渲染视口（VLM 评估单图足够；小于此值标签会被压缩失真）
_CHART_VIEWPORT_WIDTH = 720
_CHART_VIEWPORT_HEIGHT = 540
# ECharts 动画稳定等待（ms），与 _render_sync 的 800ms 对齐
_RENDER_STABILIZE_MS = 800


def _build_single_chart_html(chart_id: str) -> str:
    """构建单图渲染 HTML 骨架。

    Args:
        chart_id: 用于 data-ref 属性，方便后续注入 option

    Returns:
        HTML 字符串（含 echarts 容器与占位文本，option 由 page.evaluate 注入）
    """
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: #fff; }}
  #chart {{
    width: {_CHART_VIEWPORT_WIDTH}px;
    height: {_CHART_VIEWPORT_HEIGHT}px;
    margin: 0 auto;
    background: #fff;
  }}
</style>
</head>
<body>
  <div id="chart" data-ref="{chart_id}"></div>
</body>
</html>"""


def _render_single_chart_sync(
    chart_id: str,
    option: Dict[str, Any],
) -> Optional[bytes]:
    """同步渲染单张 chart 为 PNG（工作线程内执行）。

    Args:
        chart_id: chart 唯一标识（用于日志，不参与渲染）
        option: ECharts option dict（chart.option 字段）

    Returns:
        PNG bytes；渲染失败返回 None
    """
    if not isinstance(option, dict):
        logger.warning("chart %s option 非 dict，跳过截图", chart_id)
        return None

    timeout_ms = max(10000, config.SITUATION_JUDGE_TIMEOUT * 1000)
    browser = visual_judge._get_browser()
    with visual_judge._browser_lock:
        page = browser.new_page(
            viewport={
                "width": _CHART_VIEWPORT_WIDTH,
                "height": _CHART_VIEWPORT_HEIGHT,
            }
        )
        try:
            html = _build_single_chart_html(chart_id)
            page.set_content(html, wait_until="load", timeout=timeout_ms)
            echarts_js = visual_judge._load_echarts_js()
            if not echarts_js:
                logger.warning("echarts.min.js 不可用，chart %s 截图返回空", chart_id)
                return None
            page.add_script_tag(content=echarts_js)
            # 注入 option 并初始化；option_map 复用 _render_sync 的挂载签名
            option_map = {chart_id: option}
            page.evaluate(
                """(optionMap) => {
                  if (typeof echarts === 'undefined') return;
                  for (const [cid, opt] of Object.entries(optionMap)) {
                    const el = document.getElementById('chart');
                    if (!el || el._sitMounted) continue;
                    try {
                      const chart = echarts.init(el);
                      chart.setOption(opt);
                      el._sitMounted = true;
                    } catch (e) { /* 单图失败不致命 */ }
                  }
                }""",
                option_map,
            )
            page.wait_for_timeout(_RENDER_STABILIZE_MS)
            png = page.screenshot(full_page=True, type="png")
            return png
        except Exception as exc:
            logger.warning("chart %s 截图渲染失败: %s", chart_id, exc)
            return None
        finally:
            page.close()


async def render_chart_pngs(
    charts: List[Dict[str, Any]],
) -> List[Tuple[str, Optional[str]]]:
    """对每张 chart 渲染独立 PNG（base64 字符串）。

    Args:
        charts: chart dict 列表（含 chartId / type / option）

    Returns:
        [(chartId, png_b64 or None), ...] —— 渲染失败的项 png_b64=None
        顺序与 charts 一致，方便 Critic 拼装 messages
    """
    if not charts:
        return []

    if not await visual_judge.is_available_async():
        logger.warning("playwright 不可用，chart 截图全部跳过")
        return [(str(c.get("chartId") or ""), None) for c in charts]

    # 浏览器单例 + _browser_lock 串行，asyncio.to_thread 仅调度不并发
    async def _render_one(chart: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        chart_id = str(chart.get("chartId") or "")
        option = chart.get("option")
        if not isinstance(option, dict):
            return chart_id, None
        try:
            png_bytes = await asyncio.to_thread(_render_single_chart_sync, chart_id, option)
            if not png_bytes:
                return chart_id, None
            png_b64 = base64.b64encode(png_bytes).decode("ascii")
            return chart_id, png_b64
        except Exception as exc:
            logger.warning("chart %s 异步截图失败: %s", chart_id, exc)
            return chart_id, None

    # 顺序调度：浏览器单例串行，并发也无加速，且避免 _browser_lock 竞态
    results: List[Tuple[str, Optional[str]]] = []
    for chart in charts:
        results.append(await _render_one(chart))
    return results


__all__ = ["render_chart_pngs"]
