"""长文本分批切分模块。

借鉴 knowledge-service chunk_text 的"分隔符切分 + 累加合并"思路，
但参数为 LLM 调优（每批 9000 字、重叠 500 字），用于 Step 1 实体类型提取的分批处理。

设计要点：
- 句子边界优先，避免切在半句话中间
- 相邻批重叠 overlap 字符，确保跨批边界实体类型不丢
- 单句超长（罕见）时硬切并按 overlap 步进
- 短文本走快路径，返回 [text]
"""
import re

# 句子分隔符：中英文句号、问号、感叹号、换行、分号
_SENT_DELIMITERS = r'[。！？\n;；!?]'


def split_into_batches(text: str, max_chars: int = 9000, overlap: int = 500) -> list:
    """把长文本切分为可重叠的批次，每批不超过 max_chars。

    Args:
        text: 原始文本
        max_chars: 每批字符数上限
        overlap: 相邻批重叠字符数（取上一批末尾 N 字符作为下一批开头）

    Returns:
        批次字符串列表，至少包含一个批次（空文本返回 []）
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # 用保留分隔符的方式切句：re.split 捕获组会把分隔符也保留在结果里
    parts = re.split(f'({_SENT_DELIMITERS})', text)
    sentences = []
    for i in range(0, len(parts), 2):
        s = parts[i] + (parts[i + 1] if i + 1 < len(parts) else '')
        if s:
            sentences.append(s)

    if not sentences:
        return [text]

    batches = []
    buf = ""
    i = 0
    while i < len(sentences):
        sent = sentences[i]

        # 单句超长（罕见）：硬切并按 overlap 步进，退化为字符级切分
        if len(sent) > max_chars:
            if buf:
                batches.append(buf)
                buf = ""
            start = 0
            while start < len(sent):
                batches.append(sent[start:start + max_chars])
                if start + max_chars >= len(sent):
                    break
                # 步进 = max_chars - overlap，保证相邻硬切片段有 overlap 重叠
                start = max(0, start + max_chars - overlap)
            i += 1
            continue

        # 累加到 buf，超限则收尾成一批
        if len(buf) + len(sent) > max_chars:
            batches.append(buf)
            # overlap：取上一批末尾 N 字符作为下一批开头，确保跨批边界实体类型不丢
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = tail + sent
        else:
            buf += sent
        i += 1

    if buf:
        batches.append(buf)

    return [b for b in batches if b.strip()]


# ── 章节结构感知分批 ──
# 供构建规划阶段使用：先正则提取章节标题及位置，再按章节语义单元打包成批，
# 同一章节不跨批，保证「领域/篇章父类型」与「其子类型」落在同一批内。

# 章节标题模式：第X章/第X节/一、二、/1. /1.1 /# 标题
_CHAPTER_PATTERNS = [
    # 第X章 标题（章级）
    re.compile(r'^第[一二三四五六七八九十百千0-9]+章[^\n]{0,40}$', re.M),
    # 第X节 标题（节级）
    re.compile(r'^第[一二三四五六七八九十百千0-9]+节[^\n]{0,40}$', re.M),
    # 数字编号 1. / 1.1 / 1.1.2 标题（至少两级才算结构）
    re.compile(r'^\d+(?:\.\d+)+[ \t\u3000][^\n]{2,40}$', re.M),
]


def extract_headings(text: str) -> list:
    """提取文档的章节标题及字符位置。

    Args:
        text: 原始文本

    Returns:
        [{"title": "第二章 物理域对象模型", "start": 1200, "end": 4200}, ...]
        按出现位置升序；无任何标题时返回 []
    """
    if not text:
        return []
    matches = []
    for pat in _CHAPTER_PATTERNS:
        for m in pat.finditer(text):
            matches.append((m.start(), m.end(), m.group(0).strip()))
    if not matches:
        return []
    matches.sort(key=lambda x: x[0])
    # 去重（同一位置可能被多模式命中）并计算区间
    headings = []
    last_start = -1
    for start, end, title in matches:
        if start == last_start:
            continue
        last_start = start
        headings.append({"title": title, "start": start})
    for i, h in enumerate(headings):
        h["end"] = headings[i + 1]["start"] if i + 1 < len(headings) else len(text)
    return headings


def split_by_headings(text: str, headings: list, max_chars: int, min_chars: int = 3000) -> list:
    """按章节标题把文本打包成分批，同批尽量包含完整章节。

    打包规则：从章节起点切分（首章之前的前言内容并入第一批），
    累加整章直到超过 max_chars；单章超长时章内回退句级切分（split_into_batches）。

    Args:
        text: 原始文本
        headings: extract_headings 的输出
        max_chars: 每批字符数上限
        min_chars: 每批字符数下限（不足时与下一批合并，避免批数过多）

    Returns:
        批次文本列表；headings 为空时返回 None（由调用方回退字符切分）
    """
    if not headings:
        return None

    # 切成"章节段"：第一段 = 文档开头到第一个标题（可能为空）
    segments = []
    first = headings[0]["start"]
    if first > 0:
        segments.append((text[:first], "前言/目录"))
    for h in headings:
        segments.append((text[h["start"]:h["end"]], h["title"]))

    # 章节段累加打包
    batches = []
    buf, buf_titles, buf_len = "", [], 0
    for seg, title in segments:
        if buf_len > 0 and buf_len + len(seg) > max_chars:
            if buf_len < min_chars and len(buf) + len(seg) <= max_chars * 1.2:
                # 不足下限且未严重超限：并入当前批
                buf += seg
                buf_titles.append(title)
                buf_len = len(buf)
                continue
            batches.append((buf, buf_titles))
            buf, buf_titles, buf_len = "", [], 0
        buf += seg
        buf_titles.append(title)
        buf_len = len(buf)
    if buf.strip():
        batches.append((buf, buf_titles))

    # 单章超长（罕见）：章内回退句级切分
    result = []
    for batch_text, titles in batches:
        if len(batch_text) <= max_chars:
            result.append({"text": batch_text, "titles": titles})
        else:
            for sub in split_into_batches(batch_text, max_chars=max_chars, overlap=0):
                result.append({"text": sub, "titles": titles})
    return result
