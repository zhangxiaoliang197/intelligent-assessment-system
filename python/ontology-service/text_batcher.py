"""长文本分批切分模块。

借鉴 knowledge-service chunk_text 的"分隔符切分 + 累加合并"思路，
但参数为 LLM 调优（每批 9000 字、重叠 500 字），用于 Step 1 概念提取的分批处理。

设计要点：
- 句子边界优先，避免切在半句话中间
- 相邻批重叠 overlap 字符，确保跨批边界概念不丢
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
            # overlap：取上一批末尾 N 字符作为下一批开头，确保跨批边界概念不丢
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = tail + sent
        else:
            buf += sent
        i += 1

    if buf:
        batches.append(buf)

    return [b for b in batches if b.strip()]
