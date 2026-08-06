"""本体分步构建的 Prompt 模板。

集中管理四步 LLM 调用的 prompt，便于迭代调优：
- Step 0 (meta): 根据文档推荐元模型（实体类型 + 关系类型）
- Step 1: 从文档提取概念清单（约束于已确认的元模型）
- Step 2: 把概念清单整理成层次结构（实体 + 关系）
- Step 3: 最终序列化（直接复用已确认的元模型，不再调 LLM 推荐元模型）

设计原则：
- 每步输出严格 JSON，便于程序解析
- Step 1 每个概念必须带原文出处 source_snippet，防幻觉
- Step 2 实体名和关系类型必须受元模型约束
- temperature=0.3，提升结构化输出稳定性
"""
import json

SYSTEM_BASE = "你是本体工程专家，擅长从领域文档中构建结构化本体模型。请严格按照要求输出 JSON，不要包含任何解释文字或 markdown 标记。"

# 默认调色板（元模型推荐时分配颜色）
DEFAULT_COLORS = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272", "#fc8452", "#9a60b4"]


def build_meta_messages(doc_text: str, name: str) -> list:
    """Step 0: 根据文档推荐元模型（实体类型 + 关系类型）。

    在 upload 时调用，LLM 分析文档领域特征，推荐一套适合该文档的元模型标准。
    这套标准确认后，后续 step1/step2 的 LLM 调用必须遵守，不能自行修改。

    Args:
        doc_text: 文档纯文本（已截断）
        name: 用户输入的本体名称

    Returns:
        OpenAI 格式的 messages 列表
    """
    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是分析文档内容，为本体「" + name + "」推荐一套合适的元模型。"
        + "\n元模型定义了本体内允许的实体类型和关系类型，是后续构建概念和关系的基础约束。"
    )

    user_prompt = (
        f"请分析以下文档，推荐一套适合该领域的元模型。\n\n"
        f"文档内容：\n---\n{doc_text}\n---\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"entity_types": [{{"name": "类型名", "color": "#hex颜色", "description": "类型说明"}}], '
        f'"relation_types": [{{"name": "关系名", "description": "关系说明"}}]}}\n\n'
        f"要求：\n"
        f"1. entity_types 推荐 3-6 个类型，应覆盖文档中的核心概念分类（如：概念、实体、属性、事件、指标等）\n"
        f"2. relation_types 推荐 3-6 个关系，应反映文档中的语义关联（如：包含、关联、影响、衡量、继承等）\n"
        f"3. 类型名简洁中文，2-4 个字\n"
        f"4. color 从以下调色板选择: {', '.join(DEFAULT_COLORS)}\n"
        f"5. 只返回 JSON，不要任何解释"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step1_messages(doc_text: str, name: str, entity_types: list) -> list:
    """Step 1: 从文档提取概念清单。

    约束于 Step 0 已确认的 entity_types，每个概念必须带原文出处。

    Args:
        doc_text: 文档纯文本（已截断）
        name: 本体名称
        entity_types: 已确认的实体类型列表 [{"name":"...","color":"..."}]

    Returns:
        OpenAI 格式的 messages 列表
    """
    type_names = [t["name"] for t in entity_types]
    types_str = "、".join(type_names)

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是从文档中提取概念清单，为本体「" + name + "」构建概念基础。"
    )

    user_prompt = (
        f"请从以下文档中提取核心概念清单。\n\n"
        f"文档内容：\n---\n{doc_text}\n---\n\n"
        f"允许的实体类型（必须从中选择，不可自创）: {types_str}\n\n"
        f"请返回 JSON 数组，每个元素格式如下：\n"
        f'{{"name": "概念名", "type": "类型（必须从允许的类型中选择）", '
        f'"description": "概念的简要释义", "source_snippet": "从原文摘录的支撑句子"}}\n\n'
        f"要求：\n"
        f"1. 提取文档中的核心概念、实体、属性、事件等，不要遗漏重要概念\n"
        f"2. 每个概念必须从原文摘录 source_snippet（原文中的原话），用于核实，防止编造\n"
        f"3. name 简洁规范，2-8 个字，避免重复\n"
        f"4. type 必须从允许的类型中选择，不可自创\n"
        f"5. description 用一句话解释该概念的含义\n"
        f"6. 通常提取 8-20 个概念\n"
        f"7. 只返回 JSON 数组，不要任何解释"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step2_messages(concepts: list, entity_types: list, relation_types: list) -> list:
    """Step 2: 把概念清单整理成层次结构（实体 + 关系）。

    约束于 Step 0 已确认的 relation_types。

    Args:
        concepts: Step 1 已确认的概念清单 [{"name","type","description","source_snippet"}]
        entity_types: 已确认的实体类型
        relation_types: 已确认的关系类型 [{"name":"..."}]

    Returns:
        OpenAI 格式的 messages 列表
    """
    type_names = [t["name"] for t in entity_types]
    rel_names = [t["name"] for t in relation_types]
    concepts_str = json.dumps(concepts, ensure_ascii=False, indent=2)

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是把已确认的概念清单整理成有上下级关系的层次结构，"
        + "建立实体之间的语义关系。"
    )

    user_prompt = (
        f"已确认的概念清单如下：\n{concepts_str}\n\n"
        f"允许的实体类型: {'、'.join(type_names)}\n"
        f"允许的关系类型（必须从中选择，不可自创）: {'、'.join(rel_names)}\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"entities": [{{"name": "实体名", "type": "类型", "properties": {{"key": "value"}}, "parent": "父实体名（无则空字符串）"}}], '
        f'"relations": [{{"source": "源实体名", "target": "目标实体名", "relation_type": "关系类型", "weight": 1.0}}]}}\n\n'
        f"要求：\n"
        f"1. entities 的 name 必须来自上述概念清单，不可新增或改名\n"
        f"2. entities 的 type 必须从允许的实体类型中选择\n"
        f"3. parent 表示上下级包含关系，指向另一个实体的 name；顶层概念的 parent 为空字符串\n"
        f"4. relations 的 source 和 target 必须是 entities 中已定义的实体名\n"
        f"5. relation_type 必须从允许的关系类型中选择，不可自创\n"
        f"6. weight 表示关系的紧密程度，0-1 之间的小数\n"
        f"7. properties 可包含从概念 description 和 source_snippet 中提取的关键属性\n"
        f"8. 关系应体现层级包含、影响、关联等语义，通常 5-15 条关系\n"
        f"9. 只返回 JSON，不要任何解释"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step3_messages(entities: list, relations: list, entity_types: list, relation_types: list) -> list:
    """Step 3: 最终序列化。

    直接复用已确认的元模型，不调 LLM 推荐元模型。
    LLM 的职责仅限于：检查实体/关系与元模型的一致性，补充缺失的 properties，输出最终格式。

    Args:
        entities: Step 2 已确认的实体列表
        relations: Step 2 已确认的关系列表
        entity_types: 已确认的实体类型
        relation_types: 已确认的关系类型

    Returns:
        OpenAI 格式的 messages 列表
    """
    entities_str = json.dumps(entities, ensure_ascii=False, indent=2)
    relations_str = json.dumps(relations, ensure_ascii=False, indent=2)

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是对已确认的层次结构做最终序列化，检查一致性并补充属性。"
    )

    user_prompt = (
        f"已确认的实体列表：\n{entities_str}\n\n"
        f"已确认的关系列表：\n{relations_str}\n\n"
        f"已确认的元模型：\n"
        f"实体类型: {json.dumps(entity_types, ensure_ascii=False)}\n"
        f"关系类型: {json.dumps(relation_types, ensure_ascii=False)}\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"entities": [{{"name": "...", "type": "...", "properties": {{"key": "value"}}}}], '
        f'"relations": [{{"source": "...", "target": "...", "relation_type": "...", "weight": 1.0}}]}}\n\n'
        f"要求：\n"
        f"1. 保持已确认的实体和关系不变，不可新增、删除或改名\n"
        f"2. 检查每个实体的 type 是否在元模型范围内，如有不一致则修正为最接近的类型\n"
        f"3. 检查每个关系的 relation_type 是否在元模型范围内，如有不一致则修正为最接近的类型\n"
        f"4. 为每个实体补充或完善 properties（从概念描述中提取关键属性）\n"
        f"5. 保持 relations 的 weight 值不变\n"
        f"6. 只返回 JSON，不要任何解释"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step1_batch_messages(
    doc_text: str, name: str, entity_types: list,
    batch_idx: int, total_batches: int
) -> list:
    """Step 1 分批版本：明确告知 LLM 这是第 X/N 批，只提取本批内概念。

    与 build_step1_messages 的差异：
    1. user_prompt 顶部增加批次提示，防止 LLM 跨批脑补或遗漏本批概念
    2. 去掉"通常提取 8-20 个概念"的硬性数量约束（改为按本批内容自然提取），
       避免长文档单批被强制压到 20 个
    3. 保留 source_snippet 要求，强调必须来自本批原文

    Args:
        doc_text: 本批文档纯文本
        name: 本体名称
        entity_types: 已确认的实体类型列表
        batch_idx: 当前批次索引（0-based）
        total_batches: 总批数

    Returns:
        OpenAI 格式的 messages 列表
    """
    type_names = [t["name"] for t in entity_types]
    types_str = "、".join(type_names)

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是从文档中提取概念清单，为本体「" + name + "」构建概念基础。"
    )

    batch_hint = (
        f"【分批提示】本文档较长，已分为 {total_batches} 批处理。"
        f"当前是第 {batch_idx + 1}/{total_batches} 批。"
        f"请只从本批文本中提取概念，不要补提其他批次可能存在的概念，也不要遗漏本批内的概念。\n\n"
        if total_batches > 1
        else ""
    )

    user_prompt = (
        f"{batch_hint}"
        f"请从以下文档中提取核心概念清单。\n\n"
        f"文档内容（第 {batch_idx + 1}/{total_batches} 批）：\n---\n{doc_text}\n---\n\n"
        f"允许的实体类型（必须从中选择，不可自创）: {types_str}\n\n"
        f"请返回 JSON 数组，每个元素格式如下：\n"
        f'{{"name": "概念名", "type": "类型（必须从允许的类型中选择）", '
        f'"description": "概念的简要释义", "source_snippet": "从本批原文摘录的支撑句子"}}\n\n'
        f"要求：\n"
        f"1. 提取本批文档中的核心概念、实体、属性、事件等，不要遗漏重要概念\n"
        f"2. 每个概念必须从本批原文摘录 source_snippet（原文中的原话），用于核实，防止编造\n"
        f"3. name 简洁规范，2-8 个字，避免与本批内其他概念重复\n"
        f"4. type 必须从允许的类型中选择，不可自创\n"
        f"5. description 用一句话解释该概念的含义\n"
        f"6. 按本批内容自然提取，数量不限（跨批去重由系统自动完成）\n"
        f"7. 只返回 JSON 数组，不要任何解释"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step2_cross_group_messages(
    entities: list, existing_relations: list,
    entity_types: list, relation_types: list
) -> list:
    """Step 2 跨组关系补充：分组合并后，由 LLM 补充跨组实体间的关系。

    分组构建时同组内关系已完整，但跨组实体间的关系会丢失。本函数发起一次额外 LLM 调用，
    输入合并后的实体清单（仅 name+type，控制长度）+ 已有组内关系 + 关系类型，
    LLM 输出补充的跨组关系。

    Args:
        entities: 合并去重后的所有实体 [{"name","type",...}]（仅用 name+type 字段）
        existing_relations: 已有组内关系 [{"source","target","relation_type","weight"}]
        entity_types: 已确认的实体类型
        relation_types: 已确认的关系类型

    Returns:
        OpenAI 格式的 messages 列表
    """
    rel_names = [t["name"] for t in relation_types]

    # 实体清单：仅 name+type，避免 properties 撑爆 prompt；用 JSON 结构化输出
    entities_compact = [{"name": e.get("name", ""), "type": e.get("type", "")} for e in entities]
    entities_str = json.dumps(entities_compact, ensure_ascii=False, indent=2)

    # 已有关系：用 JSON 结构化，避免特殊符号触发模型异常
    existing_signature = [
        {"source": r.get("source", ""), "target": r.get("target", ""), "relation_type": r.get("relation_type", "")}
        for r in existing_relations
    ]
    existing_str = json.dumps(existing_signature, ensure_ascii=False, indent=2)

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是为已构建层次结构的本体补充跨组实体之间的关系。"
        + "同组实体间的关系已完成，你现在只需补充不同组实体之间可能存在的语义关系。"
    )

    user_prompt = (
        f"以下是本体中的全部实体清单：\n{entities_str}\n\n"
        f"允许的关系类型（必须从中选择，不可自创）: {'、'.join(rel_names)}\n\n"
        f"已有的组内关系（不要重复这些）：\n{existing_str}\n\n"
        f"请补充跨组实体之间的关系，返回 JSON：\n"
        f'{{"relations": [{{"source": "实体名", "target": "实体名", '
        f'"relation_type": "关系类型", "weight": 0.5}}]}}\n\n'
        f"要求：\n"
        f"1. source 和 target 必须是上述实体清单中已定义的实体名\n"
        f"2. relation_type 必须从允许的关系类型中选择，不可自创\n"
        f"3. 只补充跨组关系（不同类型/不同分组的实体间关系），不要重复已有组内关系\n"
        f"4. 关系应有明确的语义依据，不要强行凑数；若实体间确无跨组关系，返回空数组\n"
        f"5. weight 表示关系紧密程度，0-1 之间的小数\n"
        f"6. 通常补充 3-15 条跨组关系\n"
        f"7. 只返回 JSON，不要任何解释"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
