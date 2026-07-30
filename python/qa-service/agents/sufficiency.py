"""
数据充分性评估模块。

============================================================
模块在系统架构中的位置
============================================================
本模块位于 qa-service 的多智能体框架层（agents/），在指标分析流水线
的「SQL 执行」与「结果预览」之间插入一个**确定性判定阶段**。

它不依赖 LLM，而是基于指标定义（fieldMapping / _field_hints / formula）
与查询结果列的归一化匹配，精确统计每个指标的数据覆盖情况，并据此判定
当前结果属于四种场景之一：

  - no_data        数据库中无相关数据（查询成功但返回 0 行，或查询技术失败）
  - insufficient   数据可用但不充分（部分指标缺数据，或行数低于意图阈值）
  - sufficient     数据充分

判定结果（sufficiency_report）写入 EvaluationState，驱动 analyst 选择
对应的场景化 Prompt，从而实现「判定与解读分离」：
  - 判定用确定性规则（可测试、可解释）
  - 自然语言解读才用 LLM

============================================================
设计原则
============================================================
1. 纯 Python 规则，零 LLM 调用，零外部 IO
2. 复用 indicator_query 中的名称归一化逻辑（消除大小写/下划线/标点差异）
3. 阈值常量支持环境变量覆盖，便于不同业务场景调优
"""
import json
import os
import re
import logging

logger = logging.getLogger("evaluation.sufficiency")

# ============================================================
# 阈值常量（支持环境变量覆盖）
# ============================================================

# 趋势分析所需最少时间点数（低于此值无法呈现变化方向）
MIN_ROWS_TREND = int(os.getenv("MIN_ROWS_TREND", "3"))

# 对比分析所需最少分组数（至少两组才能比较）
MIN_ROWS_COMPARE = int(os.getenv("MIN_ROWS_COMPARE", "2"))

# 通用行数下限（非趋势/对比场景下，低于此值视为样本不足）
INSUFFICIENT_ROWS_THRESHOLD = int(os.getenv("INSUFFICIENT_ROWS_THRESHOLD", "3"))

# 取整位数（供 Prompt 与下游引用；LLM 在生成时遵循）
PERCENT_DECIMALS = int(os.getenv("PERCENT_DECIMALS", "1"))        # 百分比小数位
COUNT_DECIMALS = int(os.getenv("COUNT_DECIMALS", "0"))           # 计数小数位
QUANTITY_DECIMALS = int(os.getenv("QUANTITY_DECIMALS", "2"))     # 金额/物理量小数位


# ============================================================
# 共享辅助函数
# ============================================================

def _normalize_name(name: str) -> str:
    """名称归一化：去空格、标点、转小写，便于中文/英文混合匹配。

    与 indicator_query.py 中的 _normalize_name 保持一致，消除全半角括号、
    引号、连接符等差异。此处复制一份以避免与 indicator_query 产生循环依赖。
    """
    if not name:
        return ""
    return re.sub(
        r'[\s\u3000（）()【】\[\]《》<>「」“”‘’\-_·、，。！？：；]+',
        '', name).lower()


# ============================================================
# 指标类型识别
# ============================================================

# 计算型信号关键词（比率/均值类）
_COMPUTED_KEYWORDS = ("率", "比", "占比", "百分比", "均", "每", "平均", "比值", "系数")


def classify_indicator(ind: dict) -> str:
    """判定指标是直接查询型还是计算型。

    依据指标的 formula 与 calculationMethod 字段：
      - formula 含算术运算符（/ * + -）→ 计算型
      - formula 或 calculationMethod 含比率/均值关键词 → 计算型
      - 否则 → 直接查询型（单列聚合或纯查询）

    Args:
        ind: 指标定义字典，含 formula / calculationMethod / _calc_method 等字段

    Returns:
        "direct"（直接查询型）或 "computed"（计算型）
    """
    formula = ind.get("formula") or ""
    calc_method = ind.get("calculationMethod") or ind.get("_calc_method") or ""
    text = f"{formula} {calc_method}"

    # 信号1：除法 /（最强的跨字段计算信号）
    if '/' in formula:
        return "computed"
    # 信号2：乘法 *（仅当邻接数字/中文/英文字母，排除 count(*) 的通配符）
    if re.search(r'[\d一-龥A-Za-z]\s*\*|\*\s*[\d一-龥A-Za-z]', formula):
        return "computed"
    # 信号3：加法 +（仅当两侧邻接操作数，排除单独的 + 号）
    if re.search(r'[\d一-龥A-Za-z)]\s*\+\s*[\d一-龥A-Za-z(]', formula):
        return "computed"
    # 信号4：比率/均值关键词
    if re.search(r'率|比|占比|百分比|均|每|平均|比值|系数', text):
        return "computed"
    return "direct"


# ============================================================
# 意图启发式
# ============================================================

# 趋势分析信号词
_TREND_KEYWORDS = ("趋势", "变化", "走势", "历年", "同比", "环比", "逐年")
# 对比分析信号词
_COMPARE_KEYWORDS = ("对比", "比较", "差异", "相比", "异同", "分布")


def _infer_intent(question: str) -> str:
    """从问题文本启发式判断是否隐含趋势/对比分析意图。

    Args:
        question: 用户原始问题

    Returns:
        "trend"（趋势）/ "compare"（对比）/ "general"（通用）
    """
    if not question:
        return "general"
    q = question.lower()
    if any(k in q for k in _TREND_KEYWORDS):
        return "trend"
    if any(k in q for k in _COMPARE_KEYWORDS):
        return "compare"
    return "general"


# ============================================================
# 字段匹配
# ============================================================

def _extract_match_tokens(ind: dict) -> list:
    """提取用于匹配结果列的候选 token：指标名 + 中文概念词 + 物理字段名。

    匹配结果列时，SQL 输出列常用指标名或概念词作别名，因此将指标名与
    fieldMapping 的中文 key 一并纳入候选，提高覆盖判定的召回率。

    优先级：
      1. 指标 name（最可靠：SQL 输出列常以指标名作别名）
      2. fieldMapping（JSON: {"中文计算项": "表名.字段名"}）→ 同时取中文 key 与字段名
      3. _field_hints（分号连接字符串，格式 '{词}' -> 表名.字段名 (注释)）
         → 同时提取中文概念词与物理字段名
      4. formula 中文/英文词（兜底）

    Returns:
        候选 token 列表（去重，保留顺序）
    """
    tokens = []

    # 1. 指标名（SQL 输出列常以指标名作别名，优先级最高）
    name = ind.get("name", "")
    if name:
        tokens.append(name)

    # 2. fieldMapping → 中文概念词（key）+ 物理字段名（value）
    fm = ind.get("fieldMapping") or ""
    if isinstance(fm, str) and fm.strip() not in ("", "{}"):
        try:
            mapping = json.loads(fm)
            if isinstance(mapping, dict):
                for cn_term, col_path in mapping.items():
                    # 中文概念词（key）
                    cn = str(cn_term).strip()
                    if cn and cn not in tokens:
                        tokens.append(cn)
                    # 物理字段名（value，取 . 后的部分）
                    col_path_str = str(col_path) if col_path else ""
                    fname = (col_path_str.split(".")[-1]
                             if "." in col_path_str else col_path_str)
                    if fname and fname not in tokens:
                        tokens.append(fname)
        except (json.JSONDecodeError, ValueError, TypeError) as ex:
            logger.debug(f"fieldMapping 解析失败: {ex}")

    # 3. _field_hints → 中文概念词 + 物理字段名
    hints_str = ind.get("_field_hints") or ""
    if isinstance(hints_str, str) and hints_str:
        # 中文概念词：'词' -> ...
        for m in re.finditer(r"'([^']+)'", hints_str):
            w = m.group(1).strip()
            if w and w not in tokens:
                tokens.append(w)
        # 物理字段名：-> 表名.字段名
        for m in re.finditer(r"->\s*([\w.]+)", hints_str):
            col_path = m.group(1)
            fname = col_path.split(".")[-1] if "." in col_path else col_path
            if fname and fname not in tokens:
                tokens.append(fname)

    # 4. formula 词（兜底，仅当上述均无结果时）
    if not tokens:
        formula = ind.get("formula") or ""
        tokens = re.findall(r'[一-龥a-zA-Z_]{2,}', formula)[:10]

    return tokens


def _match_column(required_norm: str, result_cols_norm: dict) -> str:
    """归一化匹配单个 token 到结果列。

    匹配策略（按优先级）：
      1. 精确匹配（归一化后相等）
      2. 子串包含（双向，双方长度均 ≥ 3，避免短词误匹配）

    Args:
        required_norm:    归一化后的待匹配 token
        result_cols_norm: {归一化列名: 原始列名} 字典

    Returns:
        命中的原始列名；未命中返回 None
    """
    if not required_norm:
        return None
    # 精确匹配
    for cn, orig in result_cols_norm.items():
        if cn == required_norm:
            return orig
    # 子串包含（双向）
    if len(required_norm) >= 3:
        for cn, orig in result_cols_norm.items():
            if len(cn) >= 3 and (required_norm in cn or cn in required_norm):
                return orig
    return None


# ============================================================
# 主评估函数
# ============================================================

def assess_data_sufficiency(raw_results: list,
                            enhanced_indicators: list,
                            question: str,
                            technical_failure: bool = False,
                            error_msg: str = "") -> dict:
    """基于 fieldMapping/_field_hints 精确判定数据充分性。

    对每个指标，提取其所需字段 token，与查询结果列做归一化匹配，
    统计非空行数，从而判断该指标是否有数据。再结合用户问题意图
    （趋势/对比）与行数阈值，判定整体场景。

    Args:
        raw_results:          SQL 执行返回的行列表（list[dict]）
        enhanced_indicators:  经 build_field_hints 增强后的指标列表，每个指标
                              含 _field_hints / _calc_method / formula / fieldMapping
        question:             用户原始问题（用于判断是否隐含趋势/对比意图）
        technical_failure:    是否为查询技术失败（SQL 生成/执行失败）。
                              True 时 no_data 场景的 reason 标注为技术失败。
        error_msg:            技术失败时的错误信息文本

    Returns:
        评估报告字典，结构：
        {
            "scenario": "no_data" | "insufficient" | "sufficient",
            "total_rows": int,
            "per_indicator": [
                {
                    "name": str,
                    "type": "direct" | "computed",
                    "has_data": bool,
                    "row_count": int,            # 该指标相关列的非空行数
                    "matched_columns": [str],    # 命中的结果列名
                    "missing_dimensions": [str], # 缺失的 token / 维度说明
                    "weight": float
                }
            ],
            "coverage_ratio": float,   # 有数据指标数 / 总指标数
            "indicators_with_data": int,
            "indicators_total": int,
            "intent": "trend" | "compare" | "general",
            "reason": str              # 判定理由（供 Prompt 注入）
        }
    """
    total_rows = len(raw_results) if raw_results else 0

    # 构建结果列归一化索引：{归一化列名: 原始列名}
    result_columns = []
    if raw_results and isinstance(raw_results[0], dict):
        result_columns = list(raw_results[0].keys())
    result_cols_norm = {_normalize_name(c): c for c in result_columns if c}

    per_indicator = []
    for ind in (enhanced_indicators or []):
        name = ind.get("name", "")
        ind_type = classify_indicator(ind)
        tokens = _extract_match_tokens(ind)

        matched_columns = []
        missing_dimensions = []
        for tok in tokens:
            matched = _match_column(_normalize_name(tok), result_cols_norm)
            if matched and matched not in matched_columns:
                matched_columns.append(matched)
            else:
                missing_dimensions.append(tok)

        # 统计该指标相关列的非空行数（至少一个匹配列非空即计入）
        row_count = 0
        if matched_columns and raw_results:
            for r in raw_results:
                if any(r.get(mc) not in (None, "", [], {}) for mc in matched_columns):
                    row_count += 1

        # 判定该指标是否有数据
        if not matched_columns:
            has_data = False
            if not missing_dimensions:
                missing_dimensions = ["未识别到所需字段"]
        elif row_count == 0:
            # 有匹配列但全为空值
            has_data = False
            missing_dimensions = ["字段存在但全为空值"]
        else:
            has_data = True

        per_indicator.append({
            "name": name,
            "type": ind_type,
            "has_data": has_data,
            "row_count": row_count,
            "matched_columns": matched_columns,
            "missing_dimensions": missing_dimensions,
            "weight": ind.get("weight"),
        })

    indicators_total = len(per_indicator)
    indicators_with_data = sum(1 for p in per_indicator if p["has_data"])
    coverage_ratio = (indicators_with_data / indicators_total) if indicators_total else 1.0
    intent = _infer_intent(question)

    # ── 场景判定 ──
    if total_rows == 0:
        scenario = "no_data"
        if technical_failure:
            reason = (f"查询技术失败：{error_msg[:120]}"
                      if error_msg else "查询技术失败，未能获取数据")
        else:
            reason = "查询成功但返回 0 行，数据库中无相关数据"
    elif indicators_total > 0 and coverage_ratio < 1.0:
        # 部分指标无数据 → 不足
        scenario = "insufficient"
        missing_names = [p["name"] for p in per_indicator if not p["has_data"]]
        reason = (f"部分指标无数据：{', '.join(missing_names)}"
                  f"（覆盖率 {indicators_with_data}/{indicators_total}）")
    elif intent == "trend" and total_rows < MIN_ROWS_TREND:
        scenario = "insufficient"
        reason = (f"趋势分析需至少 {MIN_ROWS_TREND} 个时间点，"
                  f"当前仅 {total_rows} 行")
    elif intent == "compare" and total_rows < MIN_ROWS_COMPARE:
        scenario = "insufficient"
        reason = (f"对比分析需至少 {MIN_ROWS_COMPARE} 个分组，"
                  f"当前仅 {total_rows} 行")
    elif total_rows < INSUFFICIENT_ROWS_THRESHOLD:
        scenario = "insufficient"
        reason = (f"数据量偏少（{total_rows} 行），不足以支撑综合分析")
    else:
        scenario = "sufficient"
        reason = (f"数据充分（{total_rows} 行，"
                  f"{indicators_with_data}/{indicators_total} 个指标有数据）")

    logger.info(
        f"[sufficiency] scenario={scenario}, rows={total_rows}, "
        f"coverage={indicators_with_data}/{indicators_total}, intent={intent}")

    return {
        "scenario": scenario,
        "total_rows": total_rows,
        "per_indicator": per_indicator,
        "coverage_ratio": coverage_ratio,
        "indicators_with_data": indicators_with_data,
        "indicators_total": indicators_total,
        "intent": intent,
        "reason": reason,
    }


def build_indicator_types(enhanced_indicators: list) -> dict:
    """构建指标名 → 类型的映射，供 analyst Prompt 注入。

    Args:
        enhanced_indicators: 增强后的指标列表

    Returns:
        {指标名: "direct" | "computed"}
    """
    return {ind.get("name", ""): classify_indicator(ind)
            for ind in (enhanced_indicators or []) if ind.get("name")}
