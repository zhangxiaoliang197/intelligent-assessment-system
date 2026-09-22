"""技能语义匹配：用户问题 → 候选技能与得分 → 阈值门控决定是否自动套用。

匹配口径（用户已确认走语义向量而非确定性打分）：

1. 语料：每个技能的「名称 + 说明 + triggers」；
2. 打分：query 向量与技能语料向量逐个算余弦，取相似度最高的前 k 条求均值
   （单条语料偶然高相似容易误命中，均值更稳）；
3. 门控：双阈值 + 歧义边际 —— 只有「最高分 ≥ HIGH 且与次高分差 ≥ MARGIN」才自动套用；
   达到 LOW 但未达 HIGH 只返回候选供用户手动选择；低于 LOW 一律不套用（等价改造前行为）；
4. 降级：向量服务不可用、目录为空、语料为空等一切异常都返回「不套用」并记中文原因，
   **绝不阻断页面生成**。

向量来源是 knowledge-service 的通用向量接口（模型只加载一份，ipage 不引入 torch）。
"""
import hashlib
import json
import logging
import math
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import cache_registry
import config
from agent import skill_catalog
from agent.skill_catalog import Skill

logger = logging.getLogger("ipage-service")

MATCHER_CACHE_NAME = "ipage_skill_vectors"

# 语料向量缓存：{"fingerprint": str, "vectors": {skill_id: [[...], ...]}}
_VECTOR_CACHE: Dict[str, Any] = {}


@dataclass
class MatchResult:
    """一次技能匹配的结果。"""

    candidates: List[Dict[str, Any]] = field(default_factory=list)
    auto_id: str = ""
    reason: str = ""

    @property
    def auto(self) -> bool:
        return bool(self.auto_id)

    def to_dict(self) -> Dict[str, Any]:
        return {"candidates": self.candidates, "autoId": self.auto_id, "reason": self.reason}


def _post_embed(batch: List[str], timeout: int) -> Optional[List[List[float]]]:
    """单次调用向量接口；任何异常返回 None（由调用方降级）。"""
    url = config.KNOWLEDGE_SERVICE_URL.rstrip("/") + "/knowledge/embed"
    body = json.dumps({"texts": batch}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("调用向量接口失败 %s: %s", url, exc)
        return None

    if not isinstance(data, dict) or not data.get("success"):
        logger.warning("向量接口返回失败: %s", str((data or {}).get("message"))[:200])
        return None
    vectors = (data.get("data") or {}).get("vectors") or []
    if len(vectors) != len(batch):
        logger.warning("向量接口返回条数不匹配：期望 %s 实得 %s", len(batch), len(vectors))
        return None
    return vectors


def embed_texts(texts: Sequence[str], timeout: int = 0) -> Optional[List[List[float]]]:
    """批量文本向量化（按上限自动分批）；失败返回 None。"""
    items = [str(t or "") for t in texts]
    if not items:
        return []
    if not config.KNOWLEDGE_SERVICE_URL:
        logger.warning("未配置 KNOWLEDGE_SERVICE_URL，跳过向量化")
        return None
    timeout = timeout or config.IPAGE_SKILL_EMBED_TIMEOUT
    batch_size = max(1, min(config.IPAGE_SKILL_EMBED_MAX_TEXTS, 64))

    vectors: List[List[float]] = []
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        part = _post_embed(batch, timeout)
        if part is None:
            return None
        vectors.extend(part)
    return vectors


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度；零向量或维度不一致返回 0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _score_skill(query_vec: Sequence[float], skill_vectors: Sequence[Sequence[float]],
                 top_k: int) -> float:
    """技能得分：与语料向量相似度最高的前 k 条求均值。"""
    if not skill_vectors:
        return 0.0
    sims = sorted((_cosine(query_vec, vec) for vec in skill_vectors), reverse=True)
    head = sims[:max(1, top_k)]
    return sum(head) / len(head)


def _corpus_fingerprint(skills: Sequence[Skill]) -> str:
    """语料指纹：技能 id + 内容哈希 + 语料条数。"""
    raw = "|".join(f"{s.id}:{s.content_hash}:{len(s.corpus)}" for s in skills)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _corpus_vectors(skills: Sequence[Skill]) -> Optional[Dict[str, List[List[float]]]]:
    """取技能语料向量的分组映射；向量服务不可用返回 None。"""
    usable = [s for s in skills if s.corpus]
    if not usable:
        return {}
    fingerprint = _corpus_fingerprint(usable)
    if _VECTOR_CACHE.get("fingerprint") == fingerprint and "vectors" in _VECTOR_CACHE:
        return _VECTOR_CACHE["vectors"]

    flat: List[str] = []
    owners: List[str] = []
    for skill in usable:
        for text in skill.corpus:
            flat.append(text)
            owners.append(skill.id)

    vectors = embed_texts(flat)
    if vectors is None:
        return None
    if len(vectors) != len(flat):
        logger.warning("语料向量条数不匹配：期望 %s 实得 %s", len(flat), len(vectors))
        return None

    grouped: Dict[str, List[List[float]]] = {}
    for skill_id, vector in zip(owners, vectors):
        grouped.setdefault(skill_id, []).append(vector)
    _VECTOR_CACHE["fingerprint"] = fingerprint
    _VECTOR_CACHE["vectors"] = grouped
    return grouped


def match(query: str, top_n: int = 3) -> MatchResult:
    """对用户问题做技能匹配，返回候选与是否自动套用的决策。

    任何一步失败都返回「不套用」，reason 给出可读中文原因，调用方据此记录日志/提示。
    """
    if not config.IPAGE_SKILL_MATCH_ENABLED:
        return MatchResult(reason="技能匹配已关闭")
    text = str(query or "").strip()
    if not text:
        return MatchResult(reason="问题为空，跳过技能匹配")

    try:
        skills = skill_catalog.load_skills()
    except Exception as exc:
        logger.warning("技能目录加载异常，本次不套用技能: %s", exc)
        return MatchResult(reason="技能目录加载异常，本次不套用技能")
    if not skills:
        return MatchResult(reason="技能目录为空，本次不套用技能")

    try:
        corpus = _corpus_vectors(skills)
    except Exception as exc:
        logger.warning("技能语料向量化异常，本次不套用技能: %s", exc)
        return MatchResult(reason="向量服务异常，本次不套用技能")
    if corpus is None:
        return MatchResult(reason="向量服务不可用，本次不套用技能")
    if not corpus:
        return MatchResult(reason="技能语料为空，本次不套用技能")

    query_vectors = embed_texts([text])
    if not query_vectors:
        return MatchResult(reason="向量服务不可用，本次不套用技能")
    query_vec = query_vectors[0]

    scored: List[tuple] = []
    for skill in skills:
        skill_vectors = corpus.get(skill.id) or []
        if not skill_vectors:
            continue
        scored.append((skill, _score_skill(query_vec, skill_vectors, config.IPAGE_SKILL_MATCH_TOP_K)))
    if not scored:
        return MatchResult(reason="技能语料为空，本次不套用技能")

    scored.sort(key=lambda item: item[1], reverse=True)
    candidates = [{"id": skill.id, "name": skill.name, "score": round(score, 4)}
                  for skill, score in scored[:max(1, top_n)]]

    best_skill, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0
    logger.info("技能匹配结果：%s", ", ".join(
        f"{c['id']}={c['score']:.3f}" for c in candidates))

    if best_score < config.IPAGE_SKILL_MATCH_LOW:
        return MatchResult(candidates, "", f"最高匹配度 {best_score:.3f} 低于候选阈值")
    if best_score < config.IPAGE_SKILL_MATCH_HIGH:
        return MatchResult(candidates, "",
                           f"最高匹配度 {best_score:.3f} 未达自动套用阈值"
                           f"（{config.IPAGE_SKILL_MATCH_HIGH}）")
    if len(scored) > 1 and (best_score - second_score) < config.IPAGE_SKILL_MATCH_MARGIN:
        return MatchResult(candidates, "",
                           f"前两名匹配度接近（{best_score:.3f} vs {second_score:.3f}），存在歧义，"
                           "请手动选择技能")
    return MatchResult(candidates, best_skill.id,
                       f"自动套用「{best_skill.name}」，匹配度 {best_score:.3f}")


def clear_cache() -> int:
    """清空语料向量缓存，返回被清理的技能条目数（供 cache_registry 调用）。"""
    count = len(_VECTOR_CACHE.get("vectors") or {})
    _VECTOR_CACHE.clear()
    return count


cache_registry.register_cache(MATCHER_CACHE_NAME, lambda _database_id, _tables: clear_cache())
