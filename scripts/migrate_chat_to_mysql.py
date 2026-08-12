"""
JSON → MySQL 聊天数据迁移脚本。
将 qa-service / indicator-service / evaluation_api 的 JSON 文件数据
迁移到 assessment 数据库的 ass_chat_* 表中。

用法：
  python scripts/migrate_chat_to_mysql.py [--dry-run] [--delete-json]

选项：
  --dry-run      仅预览，不实际写入
  --delete-json  迁移完成后删除 JSON 源文件（先备份到 *.bak）

依赖：urllib（标准库），需要 admin-service 已启动（localhost:10258）
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

# ─── 路径配置 ───
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_DIR = os.path.join(PROJECT_ROOT, "python")
ADMIN_URL = "http://localhost:10258"
DEFAULT_USER_ID = "default-user"

# 三套 JSON 文件路径
SOURCES = {
    "qa": {
        "sessions": os.path.join(PYTHON_DIR, "qa-service", "data", "sessions.json"),
        "type": "qa",
    },
    "indicator": {
        "sessions": os.path.join(PYTHON_DIR, "indicator-service", "data", "sessions.json"),
        "type": "indicator",
    },
    "evaluation": {
        "sessions": os.path.join(PYTHON_DIR, "qa-service", "data", "evaluation_sessions.json"),
        "history": os.path.join(PYTHON_DIR, "qa-service", "data", "evaluation_history.json"),
        "type": "evaluation",
    },
}

DRY_RUN = "--dry-run" in sys.argv
DELETE_JSON = "--delete-json" in sys.argv

stats = {"created": 0, "messages": 0, "skipped": 0, "errors": 0, "deleted_files": 0}


def http(method, path, body=None):
    """调用 admin-service API"""
    if DRY_RUN:
        print(f"  [DRY-RUN] {method} {path}")
        return {"success": True}
    url = f"{ADMIN_URL}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")[:200]
        print(f"  HTTP {e.code}: {msg}")
        return {"success": False, "message": msg}
    except Exception as e:
        print(f"  请求失败: {e}")
        return {"success": False, "message": str(e)}


def migrate_qa():
    """迁移 QA 会话"""
    path = SOURCES["qa"]["sessions"]
    if not os.path.exists(path):
        print(f"  [跳过] 文件不存在: {path}")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  QA 会话数: {len(data)}")
    for session_id, messages in data.items():
        sid = session_id  # 保留完整 UUID
        title = ""
        for msg in messages:
            if msg.get("role") == "user" and not title:
                content = msg.get("content", "")[:30]
                title = content if len(msg.get("content", "")) <= 30 else content + "..."

        # 创建会话
        resp = http("POST", "/api/admin/chat/sessions", {
            "id": sid, "userId": DEFAULT_USER_ID, "type": "qa", "title": title
        })
        if resp.get("success"):
            stats["created"] += 1
        else:
            stats["skipped"] += 1

        # 迁移消息
        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            meta = json.dumps({}, ensure_ascii=False)
            resp = http("POST", f"/api/admin/chat/sessions/{sid}/messages", {
                "role": role, "content": content,
                "sequenceNum": i, "metadata": meta,
                "title": title if role == "user" else ""
            })
            if resp.get("success"):
                stats["messages"] += 1
            else:
                stats["errors"] += 1

        print(f"    {sid[:8]}... {len(messages)} 条消息")


def migrate_indicator():
    """迁移 Indicator 会话"""
    path = SOURCES["indicator"]["sessions"]
    if not os.path.exists(path):
        print(f"  [跳过] 文件不存在: {path}")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  Indicator 会话数: {len(data)}")
    for session_id, session_data in data.items():
        sid = session_id  # 保留完整 UUID

        if isinstance(session_data, list):
            messages = session_data
            stage = "analyzing"
            pending_indicators = None
        else:
            messages = session_data.get("messages", [])
            stage = session_data.get("stage", "analyzing")
            pending_indicators = session_data.get("pending_indicators")

        title = ""
        for msg in messages:
            if msg.get("role") == "user" and not title:
                content = msg.get("content", "")[:30]
                title = content if len(msg.get("content", "")) <= 30 else content + "..."

        extra_data = json.dumps({"pending_indicators": pending_indicators}, ensure_ascii=False) if pending_indicators else ""

        resp = http("POST", "/api/admin/chat/sessions", {
            "id": sid, "userId": DEFAULT_USER_ID, "type": "indicator",
            "title": title, "stage": stage
        })
        if resp.get("success"):
            stats["created"] += 1

        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            resp = http("POST", f"/api/admin/chat/sessions/{sid}/messages", {
                "role": role, "content": content,
                "sequenceNum": i, "metadata": "",
                "title": title if role == "user" else ""
            })
            if resp.get("success"):
                stats["messages"] += 1
            else:
                stats["errors"] += 1

        print(f"    {sid[:8]}... {len(messages)} 条消息 [{stage}]")


def migrate_evaluation():
    """迁移 Evaluation 会话"""
    sessions_path = SOURCES["evaluation"]["sessions"]
    if not os.path.exists(sessions_path):
        print(f"  [跳过] 文件不存在: {sessions_path}")
        return
    with open(sessions_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  Evaluation 会话数: {len(data)}")
    for session_id, session_data in data.items():
        sid = session_id  # 保留完整 UUID
        turns = session_data.get("turns", [])
        title = session_data.get("question", "")[:30] or "评估分析"
        if len(session_data.get("question", "")) > 30:
            title = title + "..."

        skill_id = session_data.get("skill_id", "")

        resp = http("POST", "/api/admin/chat/sessions", {
            "id": sid, "userId": DEFAULT_USER_ID, "type": "evaluation",
            "title": title
        })
        if resp.get("success"):
            stats["created"] += 1

        seq = 0
        for turn in turns:
            question = turn.get("question", "")
            final_answer = turn.get("final_answer", "")
            skill = turn.get("skill_id", "")
            result = turn.get("result", {})
            steps = turn.get("steps", [])

            meta_answer = json.dumps({
                "resultType": "skill",
                "summary": result,
                "skillId": skill,
                "executionSteps": steps,
            }, ensure_ascii=False)

            for role, content in [("user", question), ("assistant", final_answer)]:
                meta = meta_answer if role == "assistant" else ""
                resp = http("POST", f"/api/admin/chat/sessions/{sid}/messages", {
                    "role": role, "content": content[:50000],
                    "sequenceNum": seq, "metadata": meta,
                    "title": title if role == "user" else "",
                    "summary": title[:200]
                })
                if resp.get("success"):
                    stats["messages"] += 1
                seq += 1

        # 更新会话的 extra data (skill_id)
        http("PUT", f"/api/admin/chat/sessions/{sid}", {"title": title})

        print(f"    {sid[:8]}... {len(turns)} 轮")


def backup_and_delete(filepath):
    """备份并删除 JSON 文件"""
    if DRY_RUN:
        return
    bak = filepath + ".bak"
    try:
        import shutil
        shutil.copy2(filepath, bak)
        os.remove(filepath)
        stats["deleted_files"] += 1
        print(f"    已备份并删除: {filepath}")
    except Exception as e:
        print(f"    [警告] 删除失败: {filepath} - {e}")


def main():
    print("=" * 60)
    print("JSON → MySQL 聊天数据迁移")
    if DRY_RUN:
        print("  *** DRY-RUN 模式（不实际写入）***")
    print("=" * 60)

    # 检查 admin-service
    try:
        resp = http("GET", "/api/admin/config/llm/active")
        if not resp.get("success"):
            print(" [错误] admin-service 不可用，请先启动 admin-service")
            sys.exit(1)
        print(" admin-service 连接正常")
    except Exception as e:
        print(f" [错误] 无法连接 admin-service: {e}")
        sys.exit(1)

    print()

    for name, config in SOURCES.items():
        print(f"[{name.upper()}]")
        if name == "qa":
            migrate_qa()
        elif name == "indicator":
            migrate_indicator()
        elif name == "evaluation":
            migrate_evaluation()
        print()

    # 汇总
    print("=" * 60)
    print(f"  迁移完成:")
    print(f"    会话创建: {stats['created']}")
    print(f"    消息写入: {stats['messages']}")
    print(f"    跳过: {stats['skipped']}")
    print(f"    失败: {stats['errors']}")
    if DELETE_JSON and not DRY_RUN:
        print(f"    源文件已备份为 .bak 并删除")
    print("=" * 60)

    # 删除 JSON 源文件
    if DELETE_JSON and not DRY_RUN:
        print("\n 删除 JSON 源文件...")
        for name, config in SOURCES.items():
            for key in ["sessions", "history"]:
                path = config.get(key)
                if path and os.path.exists(path):
                    backup_and_delete(path)

    if stats["errors"] > 0:
        print(f"\n  警告: 有 {stats['errors']} 条消息写入失败，请检查")
        sys.exit(1)


if __name__ == "__main__":
    main()
