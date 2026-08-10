"""草稿态存储（内存 + TTL）。

跨功能跳转用：源页面创建草稿拿 draftId → 跳转 → 态势图按 draftId 读取上下文。
Phase 1 用内存字典；Phase 2 若需多实例共享可换 Redis（接口不变）。
"""
import time
import threading
from typing import Optional

import config
from models import DraftRequest

_DRAFTS: dict = {}
_LOCK = threading.Lock()


def create_draft(req: DraftRequest) -> str:
    """创建草稿态，返回 draftId。"""
    draft_id = f"d_{int(time.time() * 1000)}_{id(req) % 10000}"
    expire_at = time.time() + config.DRAFT_TTL
    with _LOCK:
        _DRAFTS[draft_id] = {
            "draftId": draft_id,
            "source": req.source,
            "context": req.context.dict(),
            "userId": req.userId,
            "teamIds": req.teamIds,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "expire_at": expire_at,
        }
    return draft_id


def get_draft(draft_id: str) -> Optional[dict]:
    """读取草稿态，过期则删除并返回 None。"""
    with _LOCK:
        item = _DRAFTS.get(draft_id)
        if not item:
            return None
        if time.time() > item["expire_at"]:
            _DRAFTS.pop(draft_id, None)
            return None
        return {k: v for k, v in item.items() if k != "expire_at"}
