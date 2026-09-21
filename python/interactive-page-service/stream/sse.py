"""SSE 事件流封装（独立实现，格式与平台其他服务一致）。

event: <type>\\ndata: <json>\\n\\n
"""
import json
from typing import AsyncIterator, Tuple

from fastapi.responses import StreamingResponse


def format_event(event_type: str, data: dict, event_id: int = None) -> str:
    """格式化一条 SSE 事件。

    Args:
        event_type: 事件类型（plan/dataset/progress/page/direct/done/error）
        data: 事件数据字典
        event_id: 可选的自增序号，支持 Last-Event-ID 断线回放

    Returns:
        SSE 文本行
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    id_line = f"id: {event_id}\n" if event_id is not None else ""
    return f"{id_line}event: {event_type}\ndata: {payload}\n\n"


def sse_response(event_generator: AsyncIterator[str]) -> StreamingResponse:
    """构造禁用代理缓冲的 SSE StreamingResponse。"""
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 禁用 nginx 缓冲，保证事件实时推送
            "X-Accel-Buffering": "no",
        },
    )


# 事件类型别名，供编排器 yield (event_type, data) 元组
SSEEvent = Tuple[str, dict]
