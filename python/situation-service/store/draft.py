"""草稿态存储（内存 + TTL）。

跨功能跳转用：源页面创建草稿拿 draftId → 跳转 → 态势图按 draftId 读取上下文。
Phase 1 用内存字典；Phase 2 若需多实例共享可换 Redis（接口不变）。
"""
import time
import threading
import uuid
from typing import Optional

import config
from models import DraftRequest

_DRAFTS: dict = {}
_LOCK = threading.Lock()


def create_draft(req: DraftRequest) -> str:
    """创建草稿态，返回 draftId。"""
    # Draft IDs are bearer-like references carried across pages. Use 128 bits of
    # entropy so IDs cannot be enumerated from timestamps or process object IDs.
    draft_id = f"d_{uuid.uuid4().hex}"
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


def get_draft(
    draft_id: str,
    *,
    user_id: str = "",
    team_ids: Optional[list[str]] = None,
    role: str = "viewer",
    consume: bool = False,
) -> Optional[dict]:
    """按 owner/team 读取草稿；生成时可原子地一次性消费。"""
    with _LOCK:
        item = _DRAFTS.get(draft_id)
        if not item:
            return None
        if time.time() > item["expire_at"]:
            _DRAFTS.pop(draft_id, None)
            return None
        if user_id:
            owner_match = user_id.strip().lower() == str(item.get("userId") or "").strip().lower()
            request_teams = {str(value).strip().lower() for value in (team_ids or []) if str(value).strip()}
            draft_teams = {str(value).strip().lower() for value in (item.get("teamIds") or []) if str(value).strip()}
            if role.strip().lower() != "admin" and not owner_match and not request_teams.intersection(draft_teams):
                return None
        result = {k: v for k, v in item.items() if k != "expire_at"}
        if consume:
            _DRAFTS.pop(draft_id, None)
        return result
