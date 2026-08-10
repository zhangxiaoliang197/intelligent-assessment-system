"""SSE 事件流封装。

复用 ontology-service 的 SSE 格式：event: <type>\\ndata: <json>\\n\\n
并提供 StreamingResponse 构造器，附带防止 nginx 缓冲的响应头。
"""
import json
from typing import AsyncIterator, Tuple

from fastapi.responses import StreamingResponse


def format_event(event_type: str, data: dict) -> str:
    """格式化一条 SSE 事件。

    Args:
        event_type: 事件类型（plan/dataset/chart/map_layer/narrative/done/error 等）
        data: 事件数据字典

    Returns:
        SSE 文本行 ``event: <type>\\ndata: <json>\\n\\n``
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


def sse_response(event_generator: AsyncIterator[str]) -> StreamingResponse:
    """构造 SSE StreamingResponse。

    Args:
        event_generator: 异步生成器，yield 已格式化的 SSE 文本行

    Returns:
        StreamingResponse，media_type=text/event-stream，附带防缓冲头。
    """
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # 禁用 nginx 缓冲，保证事件实时推送
            "X-Accel-Buffering": "no",
        },
    )


# 事件类型别名，供 orchestrator yield (event_type, data) 元组
SSEEvent = Tuple[str, dict]
