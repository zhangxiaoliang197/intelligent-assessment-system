"""指标规格编译器、查询规划器与就绪度检查（Preflight）。

本模块是"配置优先 + 运行期确定化"方案的核心：
  - `compile_indicator_spec`：把指标规格（Indicator Spec）翻译为 SQL 片段；
  - `plan_indicators`：按聚合粒度分组，生成查询计划（可能多条 SQL）；
  - `preflight_indicators`：查询前的就绪度检查，替代后验充分性判定。

设计约束：
  - JOIN 只认 spec.keyMappings，不猜表关系；
  - 绑定引用的表列必须真实存在（校验 sourceTables / keyMappings / bindings）；
  - 参数占位符 `=参数(x)` 由调用方（LLM 窄任务）解析后替换；
  - 找不到绑定 / 绑定不齐 → 明确报缺口，不静默跳过。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("evaluation.indicator_engine")


def _norm(s: str) -> str:
    if not s:
        return ""
    return re.sub(r'[\s\u3000（）()【】\[\]《》<>「」“”‘’\-_·、，。！？：；]+', '', s).lower()


def _as_list(v: Any) -> List[Dict[str, Any]]:
    return v if isinstance(v, list) else []


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def _safe_ident(name: str) -> str:
    """SQL 标识符白名单：仅允许字母/数字/下划线，防止注入。"""
    if not re.fullmatch(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*", name or ""):
        raise ValueError(f"非法 SQL 标识符: {name!r}")
    return name


def _safe_ref(ref: str) -> str:
    """校验并规范化 别名.列名 引用。"""
    alias, _, col = (ref or "").partition(".")
    if not alias or not col:
        raise ValueError(f"非法引用: {ref!r}（应为 别名.列名）")
    return f"{_safe_ident(alias)}.{_safe_ident(col)}"


def _quote_style_for(db_type: str) -> str:
    """数据库类型 → 标识符引用风格：mysql 用反引号，其余（oracle/达梦/pg/sqlserver）用双引号。"""
    t = (db_type or "").lower()
    if "mysql" in t or "maria" in t:
        return "backtick"
    if t:
        return "double"
    return "none"


def _qi(ident: str, quote_style: str) -> str:
    """按引用风格包裹标识符（白名单校验后）。"""
    if quote_style in ("backtick", "double"):
        # 引用模式允许表名含空格（达梦/Oracle 表名如 "income statement"）
        if not re.fullmatch(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff .]*", ident or ""):
            raise ValueError(f"非法 SQL 标识符: {ident!r}")
        safe = ident
    else:
        safe = _safe_ident(ident)
    if quote_style == "backtick":
        return "`" + safe + "`"
    if quote_style == "double":
        return '"' + safe + '"'
    return safe


def _quote_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _normalize_agg(agg: str) -> str:
    a = (agg or "").strip().upper()
    allowed = {"COUNT", "SUM", "AVG", "MIN", "MAX", "COUNT_DISTINCT"}
    if a not in allowed:
        raise ValueError(f"不支持的聚合: {agg}")
    return a


def _expr_for_binding(b: Dict[str, Any], table_alias: str,
                      quote_style: str = "none",
                      check_schema: Optional[Dict[str, List[str]]] = None,
                      preagg_names: Optional[set] = None) -> str:
    """绑定 → SQL 表达式（仅聚合/列/字面量三类，无自由 SQL）。"""
    kind = _str(b.get("kind"))
    if kind == "scoped":
        # scoped：对 base 绑定套过滤后计数
        base = _as_dict(b.get("base"))
        if not base:
            raise ValueError("scoped 绑定缺少 base")
        inner_table = _safe_ident(_str(base.get("table")))
        inner_col = _safe_ident(_str(base.get("column")))
        base_agg = _normalize_agg(_str(base.get("agg")))
        scope = _as_dict(b.get("scope"))
        scope_table = _qi(_str(scope.get("table")), quote_style) if _str(scope.get("table")) else inner_table
        scope_col = _safe_ident(_str(scope.get("column")))
        op = _str(scope.get("operator")) or "="
        val = scope.get("value")
        if val is None or val == "":
            # 参数未填充 → 退化为 0 匹配（查询计划可展示，执行由参数替换补全）
            cond = "1=0"
        else:
            cond = f"{scope_table}.{scope_col} {op} {_quote_literal(str(val))}"
        expr = (
            f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END)"
            if base_agg in ("COUNT", "COUNT_DISTINCT")
            else f"{base_agg}(CASE WHEN {cond} THEN {inner_table}.{inner_col} END)"
        )
        # scoped 表达式的表引用来自 base（其表已 JOIN）
        return f"{expr} AS {_qi(_str(b.get('term')) or 'scoped', quote_style)}"

    if kind == "expr":
        # 表达式绑定：白名单表达式（可引用 别名.列 与 preagg(预聚合, 列)），
        # 子查询只能走 preAggregations CTE，禁止语句级关键字（SELECT/FROM/WHERE 等）。
        raw = _str(b.get("expr"))
        def _sub_preagg(m: "re.Match[str]") -> str:
            name, col = m.group(1), m.group(2)
            if name not in preagg_names:
                raise ValueError(f"expr 引用了未定义的 preagg: {name}")
            return f"{_safe_ident(name)}.{_safe_ident(col)}"
        try:
            expr = re.sub(
                r"\bpreagg\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
                _sub_preagg, raw)
            expr = _validate_expr(expr, table_alias, check_schema, preagg_names)
        except ValueError as e:
            raise ValueError(f"表达式绑定: {e}") from e
        return f"{expr} AS {_qi(_str(b.get('term')) or 'value', quote_style)}"

    table = _safe_ident(_str(b.get("table")))
    column = _safe_ident(_str(b.get("column")))
    agg = _normalize_agg(_str(b.get("agg")))
    alias = _qi(_str(b.get("term")) or "value", quote_style)
    if agg == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {table}.{column}) AS {alias}"
    if agg == "COUNT":
        return f"COUNT({table}.{column}) AS {alias}"
    return f"{agg}({table}.{column}) AS {alias}"


_EXPR_KEYWORDS = {
    "CASE", "WHEN", "THEN", "ELSE", "END", "AND", "OR", "NOT",
    "IS", "NULL", "AS", "IN", "EXISTS", "BETWEEN", "LIKE", "TRUE", "FALSE",
}
_EXPR_FUNCS = {
    "COUNT", "SUM", "AVG", "MIN", "MAX", "DISTINCT",
    "DATEDIFF", "ABS", "ROUND", "NULLIF", "COALESCE", "CONCAT",
    "YEAR", "MONTH", "DAY", "DATE_FORMAT",
}


def _validate_expr(expr: str, table_by_alias: Dict[str, str],
                   check_schema: Optional[Dict[str, List[str]]] = None,
                   preagg_names: Optional[set] = None) -> str:
    """校验并规范化表达式：仅白名单关键字/函数、数字、运算符与 别名.列 引用。

    不允许 SELECT/FROM/WHERE 等语句级关键字（子查询只能走 preAggregations CTE）；
    传入 check_schema 时，引用的列必须在 schema 目录中存在。
    """
    tokens = re.findall(
        r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*|\d+\.?\d*|<=|>=|<>|!=|[+\-*/%(),.<>=]",
        expr or "")
    if not tokens:
        raise ValueError("表达式为空")
    preagg = set(preagg_names or [])
    out: List[str] = []
    i, n = 0, len(tokens)
    def _is_word(s: str) -> bool:
        return bool(s) and (s[-1].isalnum() or s[-1] == "_")
    while i < n:
        t = tokens[i]
        def _emit(s: str) -> None:
            ops = {"+", "-", "*", "/", "%", "<", ">", "=", "<=", ">=", "<>", "!="}
            if not out:
                out.append(s)
                return
            prev = out[-1]
            if s in ops:
                if prev not in ops | {"(", ","}:
                    out.append(" ")
                out.append(s)
                out.append(" ")
            elif s in {"(", ","}:
                if s == ",":
                    out.append(", ")
                else:
                    out.append(s)
            elif s == ")":
                out.append(s)
            else:
                if _is_word(prev) and _is_word(s):
                    out.append(" ")
                out.append(s)
        if re.fullmatch(r"\d+\.?\d*", t):
            _emit(t)
            i += 1
            continue
        if t in {"+", "-", "*", "/", "%", ",", "(", ")", "<", ">", "=", "<=", ">=", "<>", "!="}:
            _emit(t)
            i += 1
            continue
        if t == ".":
            raise ValueError("表达式中的 . 只能用于 别名.列 引用")
        up = t.upper()
        if up in _EXPR_KEYWORDS or up in _EXPR_FUNCS:
            _emit(up if up in _EXPR_KEYWORDS else t)
            i += 1
            continue
        # 别名.列 引用
        if (i + 2 < n and tokens[i + 1] == "."
                and re.fullmatch(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*",
                                 tokens[i + 2])):
            alias, col = t, tokens[i + 2]
            tbl = table_by_alias.get(alias)
            if tbl is None and alias not in preagg:
                raise ValueError(f"表达式引用了未声明的别名: {alias}")
            if check_schema is not None and tbl is not None \
                    and col not in check_schema.get(tbl, []):
                raise ValueError(f"表达式列不存在: {alias}.{col}")
            _emit(f"{_safe_ident(alias)}.{_safe_ident(col)}")
            i += 3
            continue
        raise ValueError(f"表达式含非法标识符: {t}")
    return "".join(out)


def _quote_qualified_refs(expr: str, quote_style: str) -> str:
    """只给 别名.列名 形式的引用加标识符引号（函数名/关键字不加引号）。"""
    if quote_style == "none":
        return expr

    def _wrap(m):
        alias, col = m.group(1), m.group(2)
        return f"{_qi(alias, quote_style)}.{_qi(col, quote_style)}"

    return re.sub(r"\b([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*)\."
                  r"([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*)",
                  _wrap, expr)


_PREAGG_TOKEN_RE = re.compile(
    r"^(?:[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*"
    r"|[0-9]+(?:\.[0-9]+)?|\(|\)|,|\+|-|\*|/|%|\s"
    r"|'[^']*')+$")


def _safe_preagg(pa: Dict[str, Any], quote_style: str) -> str:
    """预聚合（CTE）子查询校验：仅白名单 token，防注入。"""
    table = _str(pa.get("table"))
    agg_col = _str(pa.get("aggColumn"))
    agg = _normalize_agg(_str(pa.get("agg")))
    group_by = _str(pa.get("groupBy"))
    if not table or not agg_col or not group_by:
        raise ValueError("preAggregations 项缺少 table/aggColumn/agg/groupBy")
    if not _safe_ident(agg_col) or not _safe_ident(group_by):
        raise ValueError("preAggregations 标识符合法性校验失败")
    t = _qi(table, quote_style)
    ta = _safe_ident(_str(pa.get("tableAlias")) or table)
    jt = _str(pa.get("joinTable"))
    jo = _str(pa.get("joinOn"))
    expr = f"COUNT(DISTINCT {ta}.{_safe_ident(agg_col)})" if agg == "COUNT_DISTINCT" \
        else f"{agg}({ta}.{_safe_ident(agg_col)})"
    ja = _safe_ident(_str(pa.get("joinAlias")) or jt) if jt and jo else ""
    join_group_by = _str(pa.get("groupByJoin"))
    group_expr = f"{ja}.{_safe_ident(join_group_by)}" if (join_group_by and jt and jo) \
        else f"{ta}.{_safe_ident(group_by)}"
    sql = f"SELECT {group_expr} AS gk, {expr} AS cnt FROM {t} AS {ta}"
    if jt and jo:
        sql += (f" JOIN {_qi(jt, quote_style)} AS {ja}"
                f" ON {ta}.{_safe_ident(jo)} = {ja}.{_safe_ident(jo)}")
    fcol = _str(pa.get("filterColumn"))
    fval = _str(pa.get("filterValue"))
    if fcol and fval:
        sql += f" WHERE {ta}.{_safe_ident(fcol)} = {_quote_literal(fval)}"
    sql += f" GROUP BY {group_expr}"
    return sql


def _resolve_param_value(param: Dict[str, Any], question: str,
                         params: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """解析参数值：显式传入 > 问题文本关键词命中 > None（未填充）。"""
    name = _str(param.get("name"))
    term = _str(param.get("term"))
    if params and name in params:
        v = params.get(name)
        if v is not None and str(v) != "":
            return str(v)
    if question and term:
        m = re.search(re.escape(term) + r"[：:为是]?\s*([^\s，。；,!?]{1,30})", question)
        if m:
            return m.group(1).strip()
    return None


def _apply_param_bindings(bindings: List[Dict[str, Any]],
                          param_values: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 `=参数(x)` 占位符替换为具体值（返回新列表）。"""
    out = []
    for b in bindings:
        nb = dict(b)
        if _str(nb.get("kind")) == "scoped":
            scope = dict(_as_dict(nb.get("scope")))
            val = _str(scope.get("value"))
            m = re.fullmatch(r"=参数\((.+?)\)", val)
            if m:
                pname = m.group(1).strip()
                pval = param_values.get(pname)
                scope["value"] = pval if pval is not None else ""
            nb["scope"] = scope
        out.append(nb)
    return out


def compile_indicator_spec(spec: Dict[str, Any],
                           params: Optional[Dict[str, Any]] = None,
                           check_schema: Optional[Dict[str, Dict[str, List[str]]]] = None,
                           quote_style: str = "none"
                           ) -> Tuple[bool, Dict[str, Any]]:
    """把指标规格编译为可执行 SQL 计划。

    Args:
        spec: 指标规格 JSON（sourceTables / keyMappings / dimensions /
              parameters / bindings / grain / output）
        params: 参数值（LLM 窄任务抽取）
        check_schema: 可选 {表名: [列名...]}，用于编译前校验列存在性

    Returns:
        (ok, plan)。plan 含 sql / tables / joins / select_items / gaps / errors。
    """
    errors: List[str] = []
    gaps: List[str] = []
    spec = _as_dict(spec)

    # ── 预聚合（CTE）────────────────────────────────────────────
    preaggs: Dict[str, str] = {}
    for pa_name, pa in (spec.get("preAggregations") or {}).items():
        if not isinstance(pa, dict):
            errors.append(f"preAggregations 项 {pa_name} 不是对象")
            continue
        try:
            preaggs[pa_name] = _safe_preagg(pa, quote_style)
            base_table = _str(pa.get("table"))
            if check_schema and base_table not in check_schema:
                gaps.append(f"预聚合来源表不存在: {base_table}")
            elif check_schema:
                for c in (pa.get("aggColumn"), pa.get("groupBy"), pa.get("filterColumn")):
                    if c and c not in check_schema.get(base_table, []):
                        gaps.append(f"预聚合列不存在: {base_table}.{c}")
        except ValueError as e:
            errors.append(f"preAggregations 项 {pa_name}: {e}")

    # ── 来源表 ──
    sources: List[Dict[str, Any]] = _as_list(spec.get("sourceTables"))
    table_by_alias: Dict[str, str] = {}
    if not sources and not preaggs:
        errors.append("spec 缺少 sourceTables")
    for st in sources:
        alias = _str(st.get("alias"))
        table = _str(st.get("tableName"))
        if not alias or not table:
            errors.append("sourceTables 项缺少 alias 或 tableName")
            continue
        table_by_alias[alias] = table
        if check_schema and table not in check_schema:
            gaps.append(f"表 {table} 不在当前数据源的 schema 目录中")

    # ── 连接键 ──
    joins: List[str] = []
    for km in _as_list(spec.get("keyMappings")):
        left = _str(km.get("left"))
        right = _str(km.get("right"))
        if not left or not right:
            errors.append("keyMappings 项缺少 left/right")
            continue
        for ref in (left, right):
            alias, _, col = ref.partition(".")
            if alias not in table_by_alias:
                errors.append(f"连接键引用未声明别名: {ref}")
            elif check_schema and col not in check_schema.get(table_by_alias[alias], []):
                gaps.append(f"连接键列不存在: {ref}")
        joins.append(f"{_safe_ref(left)} = {_safe_ref(right)}")

    # ── 参数 ──
    param_values: Dict[str, Any] = {}
    question = _str(spec.get("_question"))
    for p in _as_list(spec.get("parameters")):
        v = _resolve_param_value(p, question, params)
        param_values[_str(p.get("name"))] = v

    # ── 绑定 → SELECT 项 ──
    bindings = _apply_param_bindings(_as_list(spec.get("bindings")), param_values)
    select_items: List[str] = []
    for b in bindings:
        term = _str(b.get("term"))
        if not term:
            errors.append("bindings 存在缺少 term 的项")
            continue
        if "column" not in b and b.get("kind") not in ("scoped", "expr"):
            errors.append(f"绑定项「{term}」缺少 column")
            continue
        if check_schema and b.get("kind") not in ("scoped", "expr"):
            b_table = _str(b.get("table"))
            b_col = _str(b.get("column"))
            if b_table not in table_by_alias:
                errors.append(f"绑定项「{term}」引用未声明别名: {b_table}")
            elif b_col not in check_schema.get(table_by_alias[b_table], []):
                gaps.append(f"绑定列不存在: {b_table}.{b_col}")
        try:
            select_items.append(_expr_for_binding(
                b, table_by_alias, quote_style,
                check_schema=check_schema, preagg_names=set(preaggs)))
        except ValueError as e:
            errors.append(f"绑定项「{term}」: {e}")

    # ── 维度 ──
    dim_exprs: List[str] = []
    for d in _as_list(spec.get("dimensions")):
        alias = _str(d.get("alias"))
        table = _str(d.get("table"))
        column = _str(d.get("column"))
        if not alias or not table or not column:
            errors.append("dimensions 项缺少 alias/table/column")
            continue
        if table not in table_by_alias:
            errors.append(f"维度引用未声明别名: {table}")
            continue
        if check_schema and column not in check_schema.get(table_by_alias[table], []):
            gaps.append(f"维度列不存在: {table}.{column}")
        dim_exprs.append(f"{_safe_ident(table)}.{_safe_ident(column)} AS {_safe_ident(alias)}")

    # ── 组装 ──
    from_clause = ", ".join(
        f"{_qi(table, quote_style)} AS {_safe_ident(alias)}"
        for alias, table in table_by_alias.items())
    if not from_clause and preaggs:
        # 仅有预聚合 CTE 时，主查询以 CTE 为数据源（MySQL 要求 FROM 引用 CTE）
        from_clause = next(iter(preaggs))
    where_parts: List[str] = []
    for p in _as_list(spec.get("parameters")):
        pname = _str(p.get("name"))
        val = param_values.get(pname)
        target = _as_dict(p.get("target"))
        if val and target:
            t = _str(target.get("table"))
            c = _str(target.get("column"))
            if t in table_by_alias:
                where_parts.append(f"{_safe_ident(t)}.{_safe_ident(c)} = {_quote_literal(str(val))}")

    ctes = []
    for pa_name, pa_sql in preaggs.items():
        ctes.append(f"{_safe_ident(pa_name)} AS ({pa_sql})")
    sql = ""
    if ctes:
        sql += "WITH " + ", ".join(ctes) + " "
    sql += "SELECT " + ", ".join(dim_exprs + select_items)
    if from_clause:
        sql += f" FROM {from_clause}"
    if joins:
        sql += " WHERE " + " AND ".join(joins)
    if where_parts:
        sql += (" AND " if joins else " WHERE ") + " AND ".join(where_parts)
    if dim_exprs:
        group_cols = [e.split(" AS ")[0] for e in dim_exprs]
        sql += " GROUP BY " + ", ".join(group_cols)

    if not select_items:
        errors.append("没有可编译的绑定项")

    ok = not errors and not gaps
    return ok, {
        "sql": sql,
        "tables": list(dict.fromkeys(table_by_alias.values())),
        "joins": joins,
        "selectItems": select_items,
        "gaps": list(dict.fromkeys(gaps)),
        "errors": errors,
        "parameterValues": {k: v for k, v in param_values.items()},
    }


def plan_indicators(indicators: List[Dict[str, Any]],
                    params: Optional[Dict[str, Any]] = None,
                    check_schema: Optional[Dict[str, List[str]]] = None,
                    quote_style: str = "none"
                    ) -> Dict[str, Any]:
    """对一组指标生成查询计划。

    粒度（grain）一致 → 单条 SQL；不一致 → 按 grain 分组生成多条 SQL。
    没有 indicatorSpec 的指标 → 标记未就绪，进 gaps。
    """
    if check_schema is None:
        check_schema = {}
    groups: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    unready: List[Dict[str, Any]] = []
    for ind in indicators or []:
        spec_raw = ind.get("indicatorSpec") or ind.get("_spec") or ""
        spec = None
        if isinstance(spec_raw, str) and spec_raw.strip():
            try:
                spec = json.loads(spec_raw)
            except json.JSONDecodeError as e:
                unready.append({"name": ind.get("name", ""), "reason": f"indicatorSpec JSON 解析失败: {e}"})
                continue
        elif isinstance(spec_raw, dict):
            spec = spec_raw
        if not spec:
            unready.append({"name": ind.get("name", ""),
                            "reason": "未配置 indicatorSpec（可走即时绑定或管理端配置）"})
            continue
        grain = json.dumps(spec.get("grain") or {}, ensure_ascii=False, sort_keys=True)
        if grain not in groups:
            groups[grain] = []
            order.append(grain)
        groups[grain].append({"indicator": ind, "spec": spec})

    plans = []
    all_gaps = []
    for grain in order:
        items = groups[grain]
        specs = [dict(it["spec"], _question=it["indicator"].get("_question", "")) for it in items]
        # 合并：多指标共享 JOIN（keyMappings 合并），SELECT 项拼接
        merged = _merge_specs(specs)
        ok, plan = compile_indicator_spec(merged, params=params,
                                          check_schema=check_schema,
                                          quote_style=quote_style)
        # 连通性校验：合并后若出现游离表（无连接键连通），按单指标拆分为独立计划
        if ok:
            split = _split_disconnected(specs, check_schema, params, quote_style)
            if split is not None:
                for sub in split:
                    sub["grain"] = json.loads(grain) if grain else {}
                    sub["indicatorNames"] = sub.pop("_names", [])
                    plans.append(sub)
                    all_gaps.extend(sub.get("gaps", []))
                    all_gaps.extend(sub.get("errors", []))
                continue
        plan["grain"] = json.loads(grain) if grain else {}
        plan["indicatorNames"] = [it["indicator"].get("name", "") for it in items]
        plan["ok"] = ok
        plans.append(plan)
        all_gaps.extend(plan.get("gaps", []))
        all_gaps.extend(plan.get("errors", []))

    return {
        "ok": all(p.get("ok") for p in plans) and not unready,
        "plans": plans,
        "unready": unready,
        "gaps": list(dict.fromkeys(all_gaps)),
    }


def _split_disconnected(specs: List[Dict[str, Any]], check_schema, params,
                        quote_style: str = "none"):
    """检测合并规格中是否存在游离表；若存在，改为逐指标编译（放弃合并）。"""
    merged = _merge_specs(specs)
    table_by_alias = {_str(st.get("alias")): _str(st.get("tableName"))
                      for st in _as_list(merged.get("sourceTables"))}
    edges: Dict[str, set] = {a: set() for a in table_by_alias}
    for km in _as_list(merged.get("keyMappings")):
        left = _str(km.get("left")).partition(".")[0]
        right = _str(km.get("right")).partition(".")[0]
        if left in edges and right in edges and left != right:
            edges[left].add(right)
            edges[right].add(left)
    if not edges:
        return None
    start = next(iter(edges))
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nb in edges.get(node, set()):
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    if len(seen) == len(edges):
        return None  # 连通，合并安全

    subs = []
    for it in specs:
        spec = it["spec"]
        ok, plan = compile_indicator_spec(dict(spec, _question=""), params=params,
                                          check_schema=check_schema,
                                          quote_style=quote_style)
        plan["ok"] = ok
        plan["_names"] = [it["indicator"].get("name", "")]
        subs.append(plan)
    return subs


def _merge_specs(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """合并同一 grain 的多个指标规格（并集 sourceTables/keyMappings/bindings/dimensions）。"""
    if len(specs) == 1:
        return specs[0]
    merged: Dict[str, Any] = {}
    source_map: Dict[str, str] = {}
    for spec in specs:
        for st in _as_list(spec.get("sourceTables")):
            alias = _str(st.get("alias"))
            if alias and alias not in source_map:
                source_map[alias] = _str(st.get("tableName"))
    merged["sourceTables"] = [{"alias": a, "tableName": t} for a, t in source_map.items()]

    key_set = set()
    key_mappings = []
    for spec in specs:
        for km in _as_list(spec.get("keyMappings")):
            left, right = _str(km.get("left")), _str(km.get("right"))
            k = f"{left}|{right}"
            if k not in key_set:
                key_set.add(k)
                key_mappings.append(km)
    merged["keyMappings"] = key_mappings

    dim_set = set()
    dims = []
    for spec in specs:
        for d in _as_list(spec.get("dimensions")):
            k = f"{_str(d.get('alias'))}|{_str(d.get('table'))}|{_str(d.get('column'))}"
            if k not in dim_set:
                dim_set.add(k)
                dims.append(d)
    merged["dimensions"] = dims
    merged["parameters"] = [p for spec in specs for p in _as_list(spec.get("parameters"))]
    merged["bindings"] = [b for spec in specs for b in _as_list(spec.get("bindings"))]
    merged["grain"] = specs[0].get("grain") or {}
    return merged


def preflight_indicators(indicators: List[Dict[str, Any]],
                         check_schema: Optional[Dict[str, List[str]]] = None,
                         table_row_counts: Optional[Dict[str, int]] = None,
                         question: str = "",
                         quote_style: str = "none") -> Dict[str, Any]:
    """查询前的指标就绪度检查（Preflight），替代后验充分性判定。

    对每个指标输出：
      - ready / missing_binding / schema_gap / no_join / empty_source
      - 缺失项与建议动作
    """
    if check_schema is None:
        check_schema = {}
    table_row_counts = table_row_counts or {}
    per_indicator = []
    for ind in indicators or []:
        name = ind.get("name", "")
        spec_raw = ind.get("indicatorSpec") or ind.get("_spec") or ""
        spec = None
        if isinstance(spec_raw, str) and spec_raw.strip():
            try:
                spec = json.loads(spec_raw)
            except json.JSONDecodeError as e:
                per_indicator.append({
                    "name": name, "status": "missing_binding",
                    "reason": f"indicatorSpec JSON 解析失败: {e}",
                    "suggestion": "检查管理端指标规格配置", "rowCount": 0})
                continue
        elif isinstance(spec_raw, dict):
            spec = spec_raw
        if not spec:
            per_indicator.append({
                "name": name, "status": "missing_binding",
                "reason": "未配置 indicatorSpec",
                "suggestion": "在管理端完成公式项绑定，或使用即时绑定并确认", "rowCount": 0})
            continue

        ok, plan = compile_indicator_spec(dict(spec, _question=question),
                                          check_schema=check_schema,
                                          quote_style=quote_style)
        if not ok:
            per_indicator.append({
                "name": name, "status": "missing_binding",
                "reason": "；".join(plan["errors"]) or "绑定不完整",
                "suggestion": "补齐绑定后重新保存规格", "rowCount": 0})
            continue
        if plan.get("gaps"):
            per_indicator.append({
                "name": name, "status": "schema_gap",
                "reason": "；".join(plan["gaps"]),
                "suggestion": "检查数据源表结构或更新语义目录", "rowCount": 0})
            continue

        known_counts = [table_row_counts[t] for t in plan.get("tables", [])
                        if t in table_row_counts]
        if known_counts and min(known_counts) == 0:
            status = "empty_source"
            reason = f"来源表无数据（{plan['tables']}）"
            suggestion = "扩大时间范围或补充数据"
            row_count = 0
        else:
            status = "ready"
            reason = ""
            suggestion = ""
            row_count = min(known_counts) if known_counts else 0
        per_indicator.append({
            "name": name, "status": status,
            "reason": reason, "suggestion": suggestion, "rowCount": row_count})

    ready = sum(1 for p in per_indicator if p["status"] == "ready")
    return {
        "scenario": "ready" if ready == len(per_indicator) and per_indicator else "insufficient",
        "total": len(per_indicator),
        "ready": ready,
        "per_indicator": per_indicator,
        "gaps": [p["reason"] for p in per_indicator if p["status"] != "ready"],
    }


def build_check_schema(schemas: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """从表结构列表构建 {表名: [列名...]} 校验索引。"""
    out: Dict[str, List[str]] = {}
    for s in schemas or []:
        t = _str(s.get("tableName"))
        if not t:
            continue
        cols = []
        for c in _as_list(s.get("columns")):
            cn = _str(c.get("columnName"))
            if cn and cn not in cols:
                cols.append(cn)
        out[t] = cols
    return out
