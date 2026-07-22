import re
import logging

logger = logging.getLogger("indicator-service")

_QUERY_CONFIRM_KEYWORDS = [
    "查询", "查一下", "查数据", "查查看", "查看指标", "查指标", "查结果",
    "确认查询", "我查", "想查",
]

_QUERY_DENY_KEYWORDS = [
    "不查询", "不用查询", "不查", "不用查", "不", "不用了",
    "不需要", "不需要了", "不用", "不查询了", "先不查",
    "算了", "不要", "不要了", "不必", "免了", "不执行",
]

_NEW_QUESTION_KEYWORDS = [
    "什么是", "什么叫", "解释", "定义", "含义", "概念",
    "帮我分析", "帮我查", "如何", "怎样", "怎么",
]

_CONCEPT_KEYWORDS = [
    "什么是", "什么叫", "定义", "解释", "含义", "概念",
    "什么意思", "如何理解",
]


def _clean_text(text: str) -> str:
    t = text.strip().lower()
    return re.sub(r'[，。！？、；：""''（）\s]', '', t)


def is_concept_query(question: str) -> bool:
    t = question.strip().lower()
    for kw in _CONCEPT_KEYWORDS:
        if kw in t:
            return True
    return False


def is_new_question(question: str) -> bool:
    t = question.strip().lower()
    if len(t) > 8:
        return True
    for kw in _NEW_QUESTION_KEYWORDS:
        if kw in t:
            return True
    return False


def is_query_confirm(text: str) -> bool:
    t_clean = _clean_text(text)
    for kw in _QUERY_CONFIRM_KEYWORDS:
        if kw in t_clean:
            if not any(dk in t_clean for dk in _QUERY_DENY_KEYWORDS):
                return True
    return False


def is_query_deny(text: str) -> bool:
    t_clean = _clean_text(text)
    for kw in _QUERY_DENY_KEYWORDS:
        if kw in t_clean:
            return True
    return False


def match_database(user_text: str, databases: list) -> dict:
    t = user_text.strip()
    if not databases:
        return {}

    for db in databases:
        if t == db.get("id", ""):
            return db

    for db in databases:
        if t == db.get("name", ""):
            return db

    for db in databases:
        name = db.get("name", "")
        if name and name in t:
            return db
        if t in name:
            return db

    words = re.split(r'[，。！？、；：""''（）\s]+', t)
    for word in reversed(words):
        if len(word) >= 2:
            for db in databases:
                name = db.get("name", "")
                if word in name or name in word:
                    return db
    return {}