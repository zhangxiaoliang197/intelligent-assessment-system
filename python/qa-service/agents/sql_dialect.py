"""Database-dialect normalization and prompt guidance for generated SQL."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable


def normalize_database_dialect(
    database_type: str = "", database_product_name: str = ""
) -> str:
    """Map configured driver names and JDBC product names to a stable dialect."""
    product = str(database_product_name or "").casefold()
    product_compact = re.sub(r"[\s_.-]+", "", product)
    raw = " ".join(
        part for part in (database_product_name, database_type) if str(part or "").strip()
    ).casefold()
    compact = re.sub(r"[\s_.-]+", "", raw)
    if "mariadb" in compact or "mysql" in compact:
        return "mysql"
    if "oracle" in compact:
        return "oracle"
    if "postgres" in compact:
        return "postgresql"
    if "sqlserver" in compact or "mssql" in compact or "microsoftsql" in compact:
        return "sqlserver"
    if (
        "达梦" in raw
        or "dameng" in compact
        or compact.startswith("dmjdbc")
        or product_compact.startswith("dmdbms")
    ):
        return "dameng"
    if "sqlite" in compact:
        return "sqlite"
    if compact.startswith("h2") or "h2database" in compact:
        return "h2"
    return "ansi"


def database_profile_from_schemas(
    schemas: Iterable[Dict[str, Any]],
    *,
    database_type: str = "",
    database_product_name: str = "",
    database_product_version: str = "",
    identifier_quote_string: str = "",
) -> Dict[str, str]:
    """Read the JDBC database profile carried by table-schema responses."""
    profile = {
        "databaseType": str(database_type or "").strip(),
        "databaseProductName": str(database_product_name or "").strip(),
        "databaseProductVersion": str(database_product_version or "").strip(),
        "identifierQuoteString": str(identifier_quote_string or "").strip(),
    }
    for schema in schemas or []:
        if not isinstance(schema, dict):
            continue
        for key in tuple(profile):
            if not profile[key] and schema.get(key) is not None:
                profile[key] = str(schema.get(key) or "").strip()
    profile["dialect"] = normalize_database_dialect(
        profile["databaseType"], profile["databaseProductName"]
    )
    return profile


def sql_dialect_prompt(profile: Dict[str, Any]) -> str:
    """Return strict, database-specific SQL generation rules."""
    dialect = normalize_database_dialect(
        str(profile.get("databaseType") or ""),
        str(profile.get("databaseProductName") or ""),
    )
    product = str(
        profile.get("databaseProductName")
        or profile.get("databaseType")
        or "未识别数据库"
    )
    version = str(profile.get("databaseProductVersion") or "").strip()
    heading = f"当前目标数据库：{product}{' ' + version if version else ''}；SQL 方言：{dialect}。"

    rules = {
        "mysql": (
            "必须使用 MySQL 语法。日期解析/格式化使用 STR_TO_DATE、DATE_FORMAT，"
            "空值使用 IFNULL/COALESCE，字符串拼接使用 CONCAT，聚合拼接使用 GROUP_CONCAT。"
            "禁止使用 Oracle 的 ROWNUM、NVL、TO_DATE、LISTAGG 和 FETCH FIRST。"
            "普通标识符优先不加引号，确需引用时使用反引号，不能把双引号当标识符引号。"
            "只有问题明确要求 Top-N/分页时才可使用 LIMIT。"
        ),
        "oracle": (
            "必须使用 Oracle SQL 语法。日期使用 TO_DATE、TRUNC、SYSDATE/CURRENT_DATE，"
            "空值使用 NVL/COALESCE，字符串拼接使用 ||，聚合拼接使用 LISTAGG ... WITHIN GROUP。"
            "禁止使用 MySQL 的 LIMIT、反引号、IFNULL、DATE_FORMAT、STR_TO_DATE、GROUP_CONCAT。"
            "表别名不能写 AS；普通标识符优先不加引号，确需引用时使用双引号并保持元数据中的大小写。"
            "只有问题明确要求 Top-N 时才使用 ROWNUM；不要假设数据库支持 LIMIT。"
        ),
        "postgresql": (
            "必须使用 PostgreSQL 语法。日期使用 TO_DATE、DATE_TRUNC、CURRENT_DATE，"
            "空值使用 COALESCE，字符串拼接使用 ||，聚合拼接使用 STRING_AGG。"
            "禁止使用反引号、IFNULL、NVL、DATE_FORMAT、ROWNUM 和 SQL Server TOP。"
            "普通标识符优先不加引号，确需引用时使用双引号。只有明确要求分页时才可使用 LIMIT/OFFSET。"
        ),
        "sqlserver": (
            "必须使用 SQL Server T-SQL。日期使用 CAST/CONVERT、DATEADD、DATEDIFF、GETDATE，"
            "空值使用 ISNULL/COALESCE，Top-N 使用 TOP，分页使用 OFFSET ... FETCH。"
            "禁止使用 LIMIT、ROWNUM、NVL、TO_DATE、DATE_FORMAT 和 PostgreSQL 的 :: 类型转换。"
            "普通标识符优先不加引号，确需引用时使用方括号。"
        ),
        "dameng": (
            "必须使用达梦数据库 SQL 方言，并优先采用其 Oracle 兼容语法："
            "日期使用 TO_DATE/TRUNC，空值使用 NVL/COALESCE，字符串拼接使用 ||。"
            "禁止使用 MySQL 的 LIMIT、反引号、IFNULL、DATE_FORMAT 和 STR_TO_DATE。"
            "普通标识符优先不加引号，确需引用时使用双引号并保持元数据中的大小写。"
        ),
        "sqlite": (
            "必须使用 SQLite 语法。日期使用 date/datetime/strftime，空值使用 COALESCE/IFNULL，"
            "字符串拼接使用 ||。禁止使用 TO_DATE、DATE_FORMAT、NVL、ROWNUM 和 TOP。"
        ),
        "h2": (
            "必须使用 H2/ANSI SQL 语法，只使用当前版本明确支持的函数。"
            "优先使用 CURRENT_DATE、COALESCE、CAST，避免 Oracle/MySQL 专用函数。"
        ),
        "ansi": (
            "数据库产品未能可靠识别，只能使用保守的 ANSI SQL：CURRENT_DATE、COALESCE、CAST、"
            "CASE WHEN、标准 JOIN/GROUP BY。禁止使用 LIMIT、ROWNUM、TOP、反引号以及任何厂商专用日期函数。"
        ),
    }
    return heading + "\n" + rules[dialect]
