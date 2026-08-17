"""本体分步构建的 Prompt 模板（五阶段）。

集中管理五步 LLM 调用的 prompt，便于迭代调优：
- Step 0 (meta): 根据文档推荐本体模型（实体类型 + 关系类型）
- Step 1: 从文档提取实体类型清单（类型层，含属性骨架 property_schema）
- Step 2: 从文档提取实体+属性（实例层，instance_of 指向 step1 实体类型）
- Step 3: 在已确认实体间建立关系（分组 + 跨组补充）
- Step 4: LLM 自检验证（标记存疑项）

设计原则：
- 每步输出严格 JSON，便于程序解析
- 每个实体类型/实体/属性/关系必须带原文出处 source_snippet，防幻觉
- 实体名、关系类型必须受本体模型约束
- 三档粒度（coarse/medium/fine）通过数量区间软约束提取数量
- 阶段提示词 stage_hints 注入到对应步骤 prompt 末尾
- temperature=0.3，提升结构化输出稳定性

注：字符串内的中文强调一律使用角引号「」，避免与 Python 字符串分隔符 " 冲突。
"""
import json
import config
from typing import Optional

SYSTEM_BASE = "你是本体工程专家，擅长从领域文档中构建结构化本体。请严格按照要求输出 JSON，不要包含任何解释文字或 markdown 标记。"

# 默认调色板（本体模型推荐时分配颜色）
DEFAULT_COLORS = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272", "#fc8452", "#9a60b4"]


def _granularity_hint(granularity: str, kind: str) -> str:
    """根据粒度预设生成数量区间提示文本。

    Args:
        granularity: coarse | medium | fine
        kind: "concepts"（step1）| "entities"（step2）

    Returns:
        如「通常提取 10-20 个」，未知粒度返回空串（不约束）
    """
    ranges = config.GRANULARITY_RANGES.get(granularity, {})
    rng = ranges.get(kind)
    if not rng:
        return ""
    return f"通常提取 {rng[0]}-{rng[1]} 个"


def _stage_hint_text(stage_hint: str) -> str:
    """格式化阶段提示词追加段（无提示词则返回空串）。"""
    if not stage_hint or not stage_hint.strip():
        return ""
    return f"\n\n【用户特别提示】{stage_hint.strip()}"


def _template_hint_text(template: Optional[dict], stage: str, template_mode: str = "soft_constraint") -> str:
    """格式化本体模型提示词，按阶段裁剪输出（v3）。

    本体模型使用模式：
    - hard_constraint：用户已「载入本体模型」，LLM 必须严格按本体模型 schema 提取，不得增删改
    - soft_constraint（默认）：本体模型作参考，LLM 可结合本文档特征增删改

    v3 变更：
    - 读取 template.entity_types（v2 读 template.concepts，已合并）
    - 实体类型带 parent_entity_type_name 层级信息
    - 新增 entity_type_relations 参考

    Args:
        template: OntologyTemplateModel.dict() 快照，None 或无 id 时返回空串（向后兼容）
        stage: "meta" | "concepts" | "entities" | "relations" | "verification"
        template_mode: soft_constraint | hard_constraint | skip_step1

    Returns:
        追加到 user_prompt 末尾的本体模型提示文本，无本体模型时返回空串
    """
    if not template or not template.get("id"):
        return ""
    hard = template_mode == "hard_constraint"
    name = template.get("name", "")
    if hard:
        header = f"\n\n【已载入本体模型（强制约束）】用户已载入本体模型「{name}」，后续提取必须严格遵循该本体模型，不得偏离。"
    else:
        header = f"\n\n【参考本体模型】用户已选择「{name}」作为参考本体模型，"

    # v3：优先读 entity_types，回退 concepts（兼容旧本体模型快照）
    entity_types = template.get("entity_types", []) or []
    if not entity_types:
        entity_types = template.get("concepts", []) or []

    if stage == "meta":
        et_names = "、".join(t.get("name", "") for t in entity_types if t.get("name"))
        rt_names = "、".join(t.get("name", "") for t in template.get("relation_types", []) if t.get("name"))
        if hard:
            return (
                header
                + "本体的实体类型与关系类型必须严格采用以下定义，不得新增、删除或修改：\n"
                + f"- 实体类型：{et_names}\n"
                + f"- 关系类型：{rt_names}"
            )
        return (
            header
            + "该本体模型的实体类型和关系类型如下，请在参考的基础上结合本文档特征增删改：\n"
            + f"- 实体类型：{et_names}\n"
            + f"- 关系类型：{rt_names}"
        )

    if stage == "concepts":
        # v3 step1：实体类型提取
        if not entity_types:
            return header + "该本体模型未定义实体类型，请结合本文档自行提取。"
        # 实体类型超过 30 个时截断，避免 prompt 过长
        truncated = entity_types[:30]
        lines = []
        for c in truncated:
            ps = c.get("property_schema", []) or []
            ps_names = "、".join(p.get("name", "") for p in ps if p.get("name"))
            parent = c.get("parent_entity_type_name") or c.get("parent_concept_name") or ""
            line = f"  - {c.get('name', '')}"
            if parent:
                line += f"（父类型：{parent}）"
            if ps_names:
                line += f"：{ps_names}"
            lines.append(line)
        suffix = ""
        if len(entity_types) > 30:
            suffix = f"\n  ... 等共 {len(entity_types)} 个实体类型"
        # v3 新增：类型间关系参考
        et_rels = template.get("entity_type_relations", []) or []
        rel_lines = []
        for etr in et_rels[:15]:
            rel_lines.append(
                f"  - {etr.get('source_entity_type_name', '')} "
                f"—[{etr.get('relation_type', '')}]→ "
                f"{etr.get('target_entity_type_name', '')}"
            )
        rel_section = ""
        if rel_lines:
            rel_section = "\n该本体模型定义的实体类型间关系：\n" + "\n".join(rel_lines)
        if hard:
            return (
                header
                + "你必须严格按照该本体模型定义的实体类型层级、属性骨架与类型间关系进行提取：\n"
                + "\n".join(lines)
                + suffix
                + rel_section
                + "\n\n硬性约束：不得新增、删除、改名或调整任何实体类型的层级；"
                + "每个实体类型的 property_schema 必须与本本体模型一致；"
                + "实体类型间关系必须与本本体模型一致。若文档未涉及某个实体类型可省略该类型，"
                + "但不得自行发明本体模型之外的类型、属性或关系。"
            )
        return (
            header
            + "该本体模型已定义以下实体类型及其属性骨架，请参考（可增删改，保持类似粒度和命名风格）：\n"
            + "\n".join(lines)
            + suffix
            + rel_section
        )

    if stage == "entities":
        if hard:
            return (
                header
                + "实体必须 instance_of 该本体模型定义的实体类型，"
                + "且每个实体必须严格按对应实体类型在本体模型中的 property_schema 填充属性，"
                + "不得自创属性名，也不得改变属性的分类（descriptive/metric）或单位。"
            )
        return (
            header
            + "实体类型清单已基于本体模型生成，请按各实体类型的 property_schema 填充属性，"
            + "属性名与分类尽量与本体模型属性骨架对齐。"
        )

    if stage == "relations":
        rt_names = "、".join(t.get("name", "") for t in template.get("relation_types", []) if t.get("name"))
        if hard:
            return (
                header
                + "关系类型必须严格在本体模型定义范围内选择，不得新增或自创：" + rt_names
            )
        return (
            header
            + "关系类型应在本体模型定义的范围内：" + rt_names
            + "（若本文档确有其他重要关系可酌情增加，但优先使用本体模型关系类型）"
        )

    if stage == "verification":
        if hard:
            return (
                header
                + "请对照本体模型 schema 检查实体类型覆盖度、属性骨架一致性与关系类型合规性，"
                + "任何偏离本体模型（新增/删除类型、属性骨架不一致、关系类型超出范围）的项都必须标记为存疑项。"
            )
        return (
            header
            + "请对照本体模型 schema 检查实体类型覆盖度与属性骨架一致性，"
            + "标记与本体模型的差异项（新增/删除的实体类型、属性骨架偏差等）为存疑项。"
        )

    return ""


def build_meta_messages(doc_text: str, name: str, template: Optional[dict] = None, template_mode: str = "soft_constraint") -> list:
    """Step 0: 根据文档推荐本体模型（实体类型 + 关系类型）。

    在 upload 时调用，LLM 分析文档领域特征，推荐一套适合该文档的本体模型标准。
    这套标准确认后，后续 step1/step2 的 LLM 调用必须遵守，不能自行修改。

    Args:
        doc_text: 文档纯文本（已截断）
        name: 用户输入的本体名称
        template: 参考模板快照（TemplateModel.dict()），注入 prompt 作约束，None 则不注入
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是分析文档内容，为本体「" + name + "」推荐一套合适的本体模型。"
        + "\n本体模型定义了本体内允许的实体类型和关系类型，是后续构建实体类型和关系的基础约束。"
    )

    user_prompt = (
        f"请分析以下文档，推荐一套适合该领域的本体模型。\n\n"
        f"文档内容：\n---\n{doc_text}\n---\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"entity_types": [{{"name": "类型名", "color": "#hex颜色", "description": "类型说明"}}], '
        f'"relation_types": [{{"name": "关系名", "description": "关系说明"}}]}}\n\n'
        f"要求：\n"
        f"1. entity_types 推荐 3-6 个类型，应覆盖文档中的核心实体类型分类（如：实体类型、实体、属性、事件、指标等）\n"
        f"2. relation_types 推荐 3-6 个关系，应反映文档中的语义关联（如：包含、关联、影响、衡量、继承等）\n"
        f"3. 类型名简洁中文，2-4 个字\n"
        f"4. color 从以下调色板选择: {', '.join(DEFAULT_COLORS)}\n"
        f"5. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "meta", template_mode)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step1_messages(
    doc_text: str, name: str, entity_types: list,
    granularity: str = "medium", stage_hint: str = "",
    template: Optional[dict] = None, template_mode: str = "soft_constraint"
) -> list:
    """Step 1: 实体类型提取（v3 类型层，含层级 + 属性骨架 + 类型间关系）。

    v3 重构：原 step1 实体类型提取 + step0 本体模型推荐合并为此步。
    从文档提取「实体类型」（抽象类型定义，如「企业」「上市企业」「财务指标」），
    形成树状层级（parent_entity_type_name），携带 property_schema（属性骨架），
    并总结实体类型之间的关系（EntityTypeRelation，为图谱类型层展示做准备）。

    不提取具体实例（如「A公司」「张三」留到 step2）。

    Args:
        doc_text: 文档纯文本（已截断）
        name: 本体名称
        entity_types: v3 中仅为兼容保留（模板已加载到 template 参数），通常为空列表
        granularity: 粒度预设，控制实体类型数量区间
        stage_hint: 用户为该阶段注入的提示词
        template: 本体模型快照，注入 prompt 作约束
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    count_hint = _granularity_hint(granularity, "concepts")

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是从文档中提取【实体类型】（类型层），为本体「" + name + "」构建类型基础。"
        + "\n实体类型是抽象的类型定义（如「企业」「上市企业」「人物」「城市」「事件」），"
        + "不是具体实例（如「A公司」「张三」留到下一步）。"
        + "\n实体类型形成树状层级：一级实体类型 → 二级实体类型 → ... ，"
        + "最低层级实体类型由实体实例组成（step2 提取）。"
        + "\n子实体类型自动继承父类型的属性骨架（并集），可补充独有属性。"
    )

    user_prompt = (
        f"请从以下文档中提取核心【实体类型】（类型定义，非具体实例），"
        f"构建实体类型层级，并总结类型间的关系。\n\n"
        f"文档内容：\n---\n{doc_text}\n---\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"entity_types": [{{'
        f'"name": "类型名", '
        f'"description": "类型释义", '
        f'"parent_entity_type_name": "父类型名（无则空字符串）", '
        f'"property_schema": [{{"name": "属性名", "category": "descriptive|metric", '
        f'"data_type": "string|number|date|enum", "unit": "单位（如%万元，无则空）", '
        f'"required": false, "description": "属性说明"}}], '
        f'"source_snippet": "从原文摘录的支撑句子"}}], '
        f'"entity_type_relations": [{{'
        f'"source_entity_type_name": "源类型名", '
        f'"target_entity_type_name": "目标类型名", '
        f'"relation_type": "关系类型（如包含/关联/影响/衡量）", '
        f'"description": "关系说明", '
        f'"source_snippet": "原文出处"}}]}}\n\n'
        f"要求：\n"
        f"1. 提取文档中的核心实体类型（抽象类别，如「企业」「人物」「财务指标」），不要提取具体实例\n"
        f"2. 每个实体类型必须从原文摘录 source_snippet（原文原话），用于核实防编造\n"
        f"3. name 简洁规范，2-8 个字，避免重复\n"
        f"4. description 用一句话解释该类型的含义\n"
        f"5. property_schema 列出该类实体应具备的关键属性骨架：\n"
        f"   - 指标型（category=metric）属性如「资产负债率」「营收」，需带 unit\n"
        f"   - 描述型（category=descriptive）属性如「主营业务」「成立日期」\n"
        f"   - 通常每个类型 2-5 个属性\n"
        f"6. 【实体类型层级】根据文档内容构建树状层级：\n"
        f"   - 若文档明确区分某类型的子类型（如「企业」分为「上市企业」「非上市企业」），"
        f"为子类型创建独立实体类型，parent_entity_type_name 指向父类型名\n"
        f"   - 子类型可补充父类型没有的独有属性（继承父类型属性由系统自动处理）\n"
        f"   - 层级深度通常 1-3 层，避免过度细化\n"
        f"   - 文档未明确区分子类型时，不要强行创建层级（parent_entity_type_name 留空）\n"
        f"   - parent_entity_type_name 必须指向同一批次内已定义的另一个类型名，不可自创\n"
        f"7. 【实体类型间关系】总结类型之间的语义关联：\n"
        f"   - 如「企业」关联「财务指标」「企业」包含「子公司」「人物」任职于「企业」\n"
        f"   - relation_type 用简洁中文（如包含/关联/影响/衡量/属于）\n"
        f"   - 这些关系为图谱类型层展示和实例关系建模提供参考\n"
        f"   - 若文档无明确的类型间关系，返回空数组\n"
        + (f"8. {count_hint}实体类型\n" if count_hint else "8. 通常提取 10-20 个实体类型\n")
        + f"9. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "concepts", template_mode)
        + _stage_hint_text(stage_hint)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step1_batch_messages(
    doc_text: str, name: str, entity_types: list,
    batch_idx: int, total_batches: int,
    granularity: str = "medium", stage_hint: str = "",
    template: Optional[dict] = None, template_mode: str = "soft_constraint"
) -> list:
    """Step 1 分批版本（v3）：从本批文档提取实体类型 + 类型间关系。

    与 build_step1_messages 的差异：
    1. user_prompt 顶部增加批次提示，防止 LLM 跨批脑补或遗漏本批实体类型
    2. 去掉硬性数量约束（改为按本批内容自然提取），避免长文档单批被强制压到固定数
    3. 保留 source_snippet + property_schema 要求，强调必须来自本批原文
    4. 粒度区间作为整体参考（跨批去重后的总数），不限制单批
    5. parent_entity_type_name 仅可指向本批内已定义的类型

    Args:
        doc_text: 本批文档纯文本
        name: 本体名称
        entity_types: 兼容保留，v3 中通常为空列表
        batch_idx: 当前批次索引（0-based）
        total_batches: 总批数
        granularity: 粒度预设（作为整体参考，不限制单批）
        stage_hint: 用户为该阶段注入的提示词
        template: 本体模型快照，注入 prompt 作约束
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是从文档中提取【实体类型】（类型层），为本体「" + name + "」构建类型基础。"
        + "\n实体类型是抽象的类型定义（如「企业」「上市企业」「人物」「事件」），不是具体实例。"
        + "\n实体类型形成树状层级，子类型自动继承父类型属性骨架。"
    )

    batch_hint = (
        f"【分批提示】本文档较长，已分为 {total_batches} 批处理。"
        f"当前是第 {batch_idx + 1}/{total_batches} 批。"
        f"请只从本批文本中提取实体类型和类型间关系，不要补提其他批次可能存在的内容，"
        f"也不要遗漏本批内的实体类型。\n\n"
        if total_batches > 1
        else ""
    )

    user_prompt = (
        f"{batch_hint}"
        f"请从以下文档中提取核心【实体类型】（类型定义，非具体实例），"
        f"构建类型层级，并总结类型间的关系。\n\n"
        f"文档内容（第 {batch_idx + 1}/{total_batches} 批）：\n---\n{doc_text}\n---\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"entity_types": [{{'
        f'"name": "类型名", '
        f'"description": "类型释义", '
        f'"parent_entity_type_name": "父类型名（无则空字符串，仅可指向本批内已定义的类型）", '
        f'"property_schema": [{{"name": "属性名", "category": "descriptive|metric", '
        f'"data_type": "string|number|date|enum", "unit": "单位（无则空）", '
        f'"required": false, "description": "属性说明"}}], '
        f'"source_snippet": "从本批原文摘录的支撑句子"}}], '
        f'"entity_type_relations": [{{'
        f'"source_entity_type_name": "源类型名", '
        f'"target_entity_type_name": "目标类型名", '
        f'"relation_type": "关系类型", '
        f'"description": "关系说明", '
        f'"source_snippet": "原文出处"}}]}}\n\n'
        f"要求：\n"
        f"1. 提取本批文档中的核心实体类型（抽象类别），不要提取具体实例\n"
        f"2. 每个实体类型必须从本批原文摘录 source_snippet，用于核实防编造\n"
        f"3. name 简洁规范，2-8 个字，避免与本批内其他类型重复\n"
        f"4. description 用一句话解释该类型的含义\n"
        f"5. property_schema 列出该类实体的关键属性骨架（指标型带 unit，描述型无单位）\n"
        f"6. 【类型层级】若本批文档明确区分某类型的子类型（如「企业」分为「上市企业」），"
        f"为子类型创建独立实体类型并 parent_entity_type_name 指向父类型名；无明确区分时不要强行创建层级\n"
        f"7. 【类型间关系】总结本批内类型之间的语义关联（如包含/关联/影响/衡量）\n"
        f"8. 按本批内容自然提取，数量不限（跨批去重由系统自动完成）\n"
        f"9. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "concepts", template_mode)
        + _stage_hint_text(stage_hint)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step2_messages(
    doc_text: str, name: str, concepts: list, entity_types: list,
    granularity: str = "medium", stage_hint: str = "",
    template: Optional[dict] = None, template_mode: str = "soft_constraint"
) -> list:
    """Step 2: 实体提取 + 实例间关系提取（v3 合并原 step2+step3）。

    v3 重构：原 step2 实体提取 + step3 关系建模合并为此步。
    从文档提取具体实例（如「A公司」「张三」「上海」），每个实体 instance_of 一个 step1 实体类型，
    按实体类型的 property_schema 填充属性，并提取实体实例之间的关系（Relation）。

    指标型属性（如「资产负债率=75%」）作为 Property 填入实体，不作为独立实体。

    Args:
        doc_text: 文档纯文本（已截断）
        name: 本体名称
        concepts: step1 已确认的实体类型清单（含 property_schema + parent_entity_type_name）
        entity_types: 兼容保留，v3 中通常为空列表
        granularity: 粒度预设，控制实体数量区间
        stage_hint: 用户为该阶段注入的提示词
        template: 本体模型快照，注入 prompt 作约束
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    count_hint = _granularity_hint(granularity, "entities")
    # 实体类型清单精简：传 name + parent_entity_type_name + property_schema
    # 含 parent_entity_type_name 让 LLM 知道类型层级，便于实体归属到最具体的子类型
    concepts_compact = [
        {
            "name": c.get("name", ""),
            "parent_entity_type_name": c.get("parent_entity_type_name")
                or c.get("parent_concept_name") or "",
            "property_schema": c.get("property_schema", []) or [],
        }
        for c in concepts
    ]
    concepts_str = json.dumps(concepts_compact, ensure_ascii=False, indent=2)

    # 关系类型参考：从模板或 step1 类型间关系推导
    rel_type_hints = []
    if template:
        for rt in (template.get("relation_types") or []):
            if rt.get("name"):
                rel_type_hints.append(rt["name"])
        for etr in (template.get("entity_type_relations") or []):
            if etr.get("relation_type") and etr["relation_type"] not in rel_type_hints:
                rel_type_hints.append(etr["relation_type"])
    if template_mode == "hard_constraint" and rel_type_hints:
        rel_types_str = "允许的关系类型（必须从中选择，不可自创）：" + "、".join(rel_type_hints)
    else:
        rel_types_str = "、".join(rel_type_hints) if rel_type_hints else "包含/关联/影响/衡量/属于（可酌情自选）"

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是从文档中提取【实体】（实例层）并建立实体间的关系，为本体「" + name + "」填充具体实例。"
        + "\n实体是具体的人/物/事（如「A公司」「张三」「上海」），每个实体归属一个已确认的实体类型。"
        + "\n指标型数据（如「资产负债率=75%」）必须作为属性填入实体，不可作为独立实体。"
        + "\n若实体类型存在层级（parent_entity_type_name 非空），实体应归属到最具体的子类型。"
        + "\n同时提取实体实例之间的关系（如「A公司」「投资」「B公司」）。"
    )

    rel_types_label = "允许的关系类型" if template_mode == "hard_constraint" else "建议的关系类型参考"
    user_prompt = (
        f"已确认的实体类型清单（实体必须 instance_of 其中一个类型）：\n{concepts_str}\n\n"
        f"{rel_types_label}：{rel_types_str}\n\n"
        f"文档内容：\n---\n{doc_text}\n---\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"entities": [{{'
        f'"name": "实体名", '
        f'"instance_of": "实体类型名（必须来自上述清单，优先选最具体的子类型）", '
        f'"properties": [{{"name": "属性名", "value": "属性值", '
        f'"category": "descriptive|metric", "unit": "单位（无则空）", '
        f'"source_snippet": "该属性值的原文出处"}}], '
        f'"source_snippet": "实体出现的原文句子"}}], '
        f'"relations": [{{'
        f'"source": "源实体名", '
        f'"target": "目标实体名", '
        f'"relation_type": "关系类型", '
        f'"weight": 0.5, '
        f'"source_snippet": "支撑该关系的原文句子"}}]}}\n\n'
        f"要求：\n"
        f"1. 提取文档中的具体实例（人名、公司名、地名、事件名等），不要提取抽象类型\n"
        f"2. instance_of 必须是上述实体类型清单中已定义的类型名，不可自创\n"
        f"3. 【归属最具体子类型】若存在类型层级（如「企业」→「上市企业」），"
        f"实体应归属到最具体的子类型（如 A公司→上市企业，而非企业），"
        f"子类型未定义时才回退到父类型\n"
        f"4. 每个实体按其 instance_of 类型的 property_schema 填充 properties：\n"
        f"   - 属性值必须从原文摘录或基于原文推导，带 source_snippet\n"
        f"   - 指标型属性（category=metric）必须有 value 和 unit\n"
        f"   - 文档未提及的属性可省略，不要编造\n"
        f"5. name 简洁规范，2-15 个字，避免重复\n"
        f"6. source_snippet 必须是原文原话，用于核实\n"
        f"7. 【实体间关系】提取实体实例之间的语义关系：\n"
        f"   - source 和 target 必须是上述 entities 数组中已定义的实体名\n"
        f"   - relation_type 优先使用建议的关系类型，若文档确有其他重要关系可酌情增加\n"
        f"   - weight 表示关系紧密程度，0-1 之间的小数\n"
        f"   - source_snippet 必须是原文原话支撑该关系，无明确依据不要建立\n"
        f"   - 关系应体现层级包含、影响、关联等语义，不要强行凑数\n"
        + (f"8. {count_hint}实体\n" if count_hint else "8. 通常提取 20-40 个实体\n")
        + f"9. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "entities", template_mode)
        + _stage_hint_text(stage_hint)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step2_batch_messages(
    doc_text: str, name: str, concepts: list, entity_types: list,
    batch_idx: int, total_batches: int,
    granularity: str = "medium", stage_hint: str = "",
    template: Optional[dict] = None, template_mode: str = "soft_constraint"
) -> list:
    """Step 2 分批版本（v3）：从本批文档提取实体+属性+实例间关系。

    与 build_step2_messages 的差异：
    1. 顶部增加批次提示，防止跨批脑补
    2. 去掉硬性数量约束，按本批内容自然提取
    3. 粒度区间作为整体参考，不限制单批
    4. 关系仅提取本批内实体间的关系（跨批关系由系统合并后单独补充）

    Args:
        doc_text: 本批文档纯文本
        name: 本体名称
        concepts: step1 已确认的实体类型清单
        entity_types: 兼容保留，v3 中通常为空列表
        batch_idx: 当前批次索引（0-based）
        total_batches: 总批数
        granularity: 粒度预设（整体参考）
        stage_hint: 用户为该阶段注入的提示词
        template: 本体模型快照，注入 prompt 作约束
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    concepts_compact = [
        {
            "name": c.get("name", ""),
            "parent_entity_type_name": c.get("parent_entity_type_name")
                or c.get("parent_concept_name") or "",
            "property_schema": c.get("property_schema", []) or [],
        }
        for c in concepts
    ]
    concepts_str = json.dumps(concepts_compact, ensure_ascii=False, indent=2)

    # 关系类型参考
    rel_type_hints = []
    if template:
        for rt in (template.get("relation_types") or []):
            if rt.get("name"):
                rel_type_hints.append(rt["name"])
        for etr in (template.get("entity_type_relations") or []):
            if etr.get("relation_type") and etr["relation_type"] not in rel_type_hints:
                rel_type_hints.append(etr["relation_type"])
    if template_mode == "hard_constraint" and rel_type_hints:
        rel_types_str = "允许的关系类型（必须从中选择，不可自创）：" + "、".join(rel_type_hints)
    else:
        rel_types_str = "、".join(rel_type_hints) if rel_type_hints else "包含/关联/影响/衡量/属于（可酌情自选）"

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是从文档中提取【实体】（实例层）并建立实体间关系，为本体「" + name + "」填充具体实例。"
        + "\n实体是具体的人/物/事，指标型数据必须作为属性填入实体，不可作为独立实体。"
        + "\n若实体类型存在层级（parent_entity_type_name 非空），实体应归属到最具体的子类型。"
    )

    batch_hint = (
        f"【分批提示】本文档较长，已分为 {total_batches} 批处理。"
        f"当前是第 {batch_idx + 1}/{total_batches} 批。"
        f"请只从本批文本中提取实体和本批内实体间的关系，不要补提其他批次可能存在的内容，"
        f"也不要遗漏本批内的实体。\n\n"
        if total_batches > 1
        else ""
    )

    rel_types_label = "允许的关系类型" if template_mode == "hard_constraint" else "建议的关系类型参考"
    user_prompt = (
        f"{batch_hint}"
        f"已确认的实体类型清单（实体必须 instance_of 其中一个类型）：\n{concepts_str}\n\n"
        f"{rel_types_label}：{rel_types_str}\n\n"
        f"文档内容（第 {batch_idx + 1}/{total_batches} 批）：\n---\n{doc_text}\n---\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"entities": [{{'
        f'"name": "实体名", '
        f'"instance_of": "实体类型名（优先选最具体的子类型）", '
        f'"properties": [{{"name": "属性名", "value": "属性值", '
        f'"category": "descriptive|metric", "unit": "单位（无则空）", '
        f'"source_snippet": "该属性值的原文出处"}}], '
        f'"source_snippet": "实体出现的原文句子"}}], '
        f'"relations": [{{'
        f'"source": "源实体名", '
        f'"target": "目标实体名", '
        f'"relation_type": "关系类型", '
        f'"weight": 0.5, '
        f'"source_snippet": "支撑该关系的原文句子"}}]}}\n\n'
        f"要求：\n"
        f"1. 提取本批文档中的具体实例，不要提取抽象类型\n"
        f"2. instance_of 必须是实体类型清单中已定义的类型名，优先归属到最具体的子类型\n"
        f"3. 每个实体按其类型的 property_schema 填充 properties（值带 source_snippet，未提及可省略）\n"
        f"4. name 简洁规范，避免与本批内其他实体重复\n"
        f"5. source_snippet 必须是本批原文原话\n"
        f"6. 【实体间关系】提取本批内实体间的关系（source/target 必须是本批 entities 中已定义的实体名）\n"
        f"7. 按本批内容自然提取，数量不限（跨批去重由系统自动完成）\n"
        f"8. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "entities", template_mode)
        + _stage_hint_text(stage_hint)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step3_messages(
    entities: list, relation_types: list, stage_hint: str = "",
    template: Optional[dict] = None, template_mode: str = "soft_constraint"
) -> list:
    """Step 3: 关系建模（单组/整体版本）。

    在已确认的实体间建立关系。实体名和关系类型必须受本体模型约束。
    每条关系带 source_snippet 防幻觉。

    Args:
        entities: step2 已确认的实体清单（仅用 name + instance_of）
        relation_types: 已确认的关系类型 [{"name":"..."}]
        stage_hint: 用户为该阶段注入的提示词
        template: 本体模型快照，注入 prompt 作约束
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    rel_names = [t["name"] for t in relation_types]
    # 实体清单精简：仅 name + instance_of，避免 properties 撑爆 prompt
    entities_compact = [
        {"name": e.get("name", ""), "instance_of": e.get("instance_of", "")}
        for e in entities
    ]
    entities_str = json.dumps(entities_compact, ensure_ascii=False, indent=2)

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是在已确认的实体间建立语义关系。"
        + "关系应有明确的原文依据，不要强行凑数。"
    )

    user_prompt = (
        f"以下是本体中的实体清单：\n{entities_str}\n\n"
        f"允许的关系类型（必须从中选择，不可自创）: {'、'.join(rel_names)}\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"relations": [{{"source": "源实体名", "target": "目标实体名", '
        f'"relation_type": "关系类型", "weight": 0.5, '
        f'"source_snippet": "支撑该关系的原文句子"}}]}}\n\n'
        f"要求：\n"
        f"1. source 和 target 必须是上述实体清单中已定义的实体名\n"
        f"2. relation_type 必须从允许的关系类型中选择，不可自创\n"
        f"3. weight 表示关系紧密程度，0-1 之间的小数\n"
        f"4. source_snippet 必须是原文原话，支撑该关系的成立（若无明确依据则不要建立该关系）\n"
        f"5. 关系应体现层级包含、影响、关联等语义，不要强行凑数\n"
        f"6. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "relations", template_mode)
        + _stage_hint_text(stage_hint)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step3_group_messages(
    entities: list, relation_types: list,
    group_idx: int, total_groups: int, stage_hint: str = "",
    template: Optional[dict] = None, template_mode: str = "soft_constraint"
) -> list:
    """Step 3 分组版本：明确告知 LLM 这是第 X/N 组，只建立组内实体间的关系。

    分组构建时同组内关系已完整，跨组关系由 build_step3_cross_group_messages 补充。

    Args:
        entities: 本组实体清单（仅 name + instance_of）
        relation_types: 已确认的关系类型
        group_idx: 当前组索引（0-based）
        total_groups: 总组数
        stage_hint: 用户为该阶段注入的提示词
        template: 本体模型快照，注入 prompt 作约束
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    rel_names = [t["name"] for t in relation_types]
    entities_compact = [
        {"name": e.get("name", ""), "instance_of": e.get("instance_of", "")}
        for e in entities
    ]
    entities_str = json.dumps(entities_compact, ensure_ascii=False, indent=2)

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是在已确认的实体间建立语义关系。"
        + "同组实体间的关系已完成一部分，你现在只需建立本组内实体间的关系。"
    )

    group_hint = (
        f"【分组提示】实体较多，已分为 {total_groups} 组处理。"
        f"当前是第 {group_idx + 1}/{total_groups} 组。"
        f"请只建立本组内实体间的关系，跨组关系由系统单独补充。\n\n"
        if total_groups > 1
        else ""
    )

    user_prompt = (
        f"{group_hint}"
        f"以下是本组实体清单：\n{entities_str}\n\n"
        f"允许的关系类型（必须从中选择）: {'、'.join(rel_names)}\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"relations": [{{"source": "源实体名", "target": "目标实体名", '
        f'"relation_type": "关系类型", "weight": 0.5, '
        f'"source_snippet": "支撑该关系的原文句子"}}]}}\n\n'
        f"要求：\n"
        f"1. source 和 target 必须是本组实体清单中已定义的实体名\n"
        f"2. relation_type 必须从允许的关系类型中选择\n"
        f"3. weight 表示关系紧密程度，0-1 之间的小数\n"
        f"4. source_snippet 必须是原文原话，支撑该关系\n"
        f"5. 只建立本组内实体间的关系，跨组关系由系统单独补充\n"
        f"6. 关系应有明确依据，不要强行凑数；若组内确无关系，返回空数组\n"
        f"7. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "relations", template_mode)
        + _stage_hint_text(stage_hint)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step3_cross_group_messages(
    entities: list, existing_relations: list, relation_types: list,
    stage_hint: str = "",
    template: Optional[dict] = None, template_mode: str = "soft_constraint"
) -> list:
    """Step 3 跨组关系补充：分组合并后，由 LLM 补充跨组实体间的关系。

    分组构建时同组内关系已完整，但跨组实体间的关系会丢失。本函数发起一次额外 LLM 调用，
    输入合并后的实体清单（仅 name+instance_of）+ 已有组内关系 + 关系类型，
    LLM 输出补充的跨组关系。

    Args:
        entities: 合并去重后的所有实体（仅用 name+instance_of）
        existing_relations: 已有组内关系
        relation_types: 已确认的关系类型
        stage_hint: 用户为该阶段注入的提示词
        template: 本体模型快照，注入 prompt 作约束
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    rel_names = [t["name"] for t in relation_types]

    entities_compact = [
        {"name": e.get("name", ""), "instance_of": e.get("instance_of", "")}
        for e in entities
    ]
    entities_str = json.dumps(entities_compact, ensure_ascii=False, indent=2)

    existing_signature = [
        {"source": r.get("source", ""), "target": r.get("target", ""), "relation_type": r.get("relation_type", "")}
        for r in existing_relations
    ]
    existing_str = json.dumps(existing_signature, ensure_ascii=False, indent=2)

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是为已构建关系的本体补充跨组实体之间的关系。"
        + "同组实体间的关系已完成，你现在只需补充不同组实体之间可能存在的语义关系。"
    )

    user_prompt = (
        f"以下是本体中的全部实体清单：\n{entities_str}\n\n"
        f"允许的关系类型（必须从中选择）: {'、'.join(rel_names)}\n\n"
        f"已有的组内关系（不要重复这些）：\n{existing_str}\n\n"
        f"请补充跨组实体之间的关系，返回 JSON：\n"
        f'{{"relations": [{{"source": "实体名", "target": "实体名", '
        f'"relation_type": "关系类型", "weight": 0.5, '
        f'"source_snippet": "支撑该关系的原文句子"}}]}}\n\n'
        f"要求：\n"
        f"1. source 和 target 必须是上述实体清单中已定义的实体名\n"
        f"2. relation_type 必须从允许的关系类型中选择\n"
        f"3. 只补充跨组关系（不同分组的实体间关系），不要重复已有组内关系\n"
        f"4. source_snippet 必须是原文原话，支撑该关系\n"
        f"5. 关系应有明确的语义依据，不要强行凑数；若实体间确无跨组关系，返回空数组\n"
        f"6. weight 表示关系紧密程度，0-1 之间的小数\n"
        f"7. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "relations", template_mode)
        + _stage_hint_text(stage_hint)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def build_step4_verification_messages(
    concepts: list, entities: list, relations: list, doc_text: str,
    stage_hint: str = "",
    template: Optional[dict] = None, template_mode: str = "soft_constraint"
) -> list:
    """Step 4: 验证（LLM 自检，已移除简报生成）。

    LLM 逐项检查实体/属性/关系是否可溯源，标记存疑项。

    Args:
        concepts: step1 已确认的实体类型清单
        entities: step2 已确认的实体清单（含属性）
        relations: step3 已确认的关系清单
        doc_text: 原文（已截断至 VERIFICATION_MAX_DOC_CHARS）
        stage_hint: 用户为该阶段注入的提示词
        template: 本体模型快照，注入 prompt 作约束
        template_mode: 模板使用模式（soft_constraint | hard_constraint）

    Returns:
        OpenAI 格式的 messages 列表
    """
    # 精简输入：截断过长的 source_snippet，保留关键字段
    concepts_compact = [
        {"name": c.get("name", ""), "entity_type": c.get("entity_type", ""),
         "property_schema": c.get("property_schema", []) or []}
        for c in concepts
    ]
    entities_compact = []
    for e in entities:
        props = []
        for p in (e.get("properties") or []):
            if isinstance(p, dict):
                props.append({"name": p.get("name", ""), "value": p.get("value"),
                              "category": p.get("category", "descriptive"),
                              "source_snippet": (p.get("source_snippet", "") or "")[:80]})
            else:
                props.append({"name": str(p)})
        entities_compact.append({
            "name": e.get("name", ""), "instance_of": e.get("instance_of", ""),
            "source_snippet": (e.get("source_snippet", "") or "")[:80],
            "properties": props,
        })
    relations_compact = [
        {"source": r.get("source", ""), "target": r.get("target", ""),
         "relation_type": r.get("relation_type", ""),
         "source_snippet": (r.get("source_snippet", "") or "")[:80]}
        for r in relations
    ]

    system_prompt = (
        SYSTEM_BASE
        + "\n\n你的任务是对已构建的本体做自检验证。"
        + "\n逐项检查实体/属性/关系是否可溯源到原文，标记存疑项。"
    )

    user_prompt = (
        f"已确认的实体类型清单：\n{json.dumps(concepts_compact, ensure_ascii=False)}\n\n"
        f"已确认的实体清单（含属性）：\n{json.dumps(entities_compact, ensure_ascii=False)}\n\n"
        f"已确认的关系清单：\n{json.dumps(relations_compact, ensure_ascii=False)}\n\n"
        f"原文（用于核实溯源）：\n---\n{doc_text}\n---\n\n"
        f"请返回 JSON，格式如下：\n"
        f'{{"verified_count": 整数, "suspect_count": 整数, '
        f'"suspects": [{{"item_type": "entity|property|relation|concept", '
        f'"item_name": "项名称", "reason": "存疑原因"}}]}}\n\n'
        f"验证要求：\n"
        f"1. 检查每个实体的 source_snippet 是否真实出现在原文（字符串匹配）\n"
        f"2. 检查每个属性值是否可溯源（source_snippet 是否支撑该值）\n"
        f"3. 检查每条关系是否有原文依据\n"
        f"4. 检查实体类型的 property_schema 是否覆盖文档中该类实体的关键属性\n"
        f"5. 存疑项给出具体原因（如「source_snippet 在原文中未找到」「属性值75%与原文72%不符」）\n"
        f"6. verified_count 为通过验证的项数，suspect_count 为存疑项数\n"
        f"7. 只返回 JSON，不要任何解释"
        + _template_hint_text(template, "verification", template_mode)
        + _stage_hint_text(stage_hint)
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


# ──────────────────────────────────────────────────────────────────
# v3 别名：四阶段流程中 step3 = 验证报告（原 step4）
# 旧五阶段 step3 = 关系建模（已合并到 v3 step2），相关函数保留供 legacy 任务使用
# ──────────────────────────────────────────────────────────────────
build_step3_verification_messages = build_step4_verification_messages
