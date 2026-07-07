"""
工具函数：从 Java admin-service 获取数据源、表结构、指标定义，以及 SQL 执行
"""
import json
import urllib.request
import urllib.error
import ssl
import os
import logging

logger = logging.getLogger("evaluation.tools")

ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _api_get(path: str, timeout: int = 30) -> dict:
    url = f"{ADMIN_SERVICE_URL}/api/admin/{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"API GET {path} failed: {e}")
        return {"success": False, "message": str(e)}


def _api_post(path: str, body: dict, timeout: int = 120) -> dict:
    url = f"{ADMIN_SERVICE_URL}/api/admin/{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"API POST {path} failed: {e}")
        return {"success": False, "message": str(e)}


# ===========================
# 数据源（数据库配置）相关
# ===========================

def fetch_all_databases() -> list:
    """获取所有数据库配置列表"""
    resp = _api_get("database/list")
    return resp.get("databases", []) if resp.get("success") else []


def fetch_database_tables(db_id: str) -> list:
    """获取指定数据库中的所有表名"""
    resp = _api_get(f"database/{db_id}/tables")
    if resp.get("success"):
        return [t.get("tableName", "") for t in resp.get("tables", [])]
    return []


def fetch_table_structure(db_id: str, table_name: str) -> dict:
    """
    读取数据库中指定表的结构（通过 read-structure 或 execute-sql）
    使用 information_schema 查询列信息
    """
    # 通过执行 SQL 获取列信息
    sql = (
        f"SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_COMMENT "
        f"FROM information_schema.COLUMNS "
        f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}' "
        f"ORDER BY ORDINAL_POSITION"
    )
    result = execute_sql_on_database(db_id, sql)
    if result.get("success"):
        columns = []
        # Java admin-service 返回 {"rows": [...], "columns": [...]}
        rows = result.get("rows", result.get("data", result.get("results", [])))
        for row in rows:
            if isinstance(row, dict):
                col_name = row.get("COLUMN_NAME", "") or row.get("column_name", "")
                data_type = row.get("DATA_TYPE", "") or row.get("data_type", "")
                is_nullable = row.get("IS_NULLABLE", "") or row.get("is_nullable", "")
                col_key = row.get("COLUMN_KEY", "") or row.get("column_key", "")
                comment = row.get("COLUMN_COMMENT", "") or row.get("column_comment", "")
            elif isinstance(row, list):
                # 降级：按列位置解析
                col_name = row[0] if len(row) > 0 else ""
                data_type = row[1] if len(row) > 1 else ""
                is_nullable = row[2] if len(row) > 2 else ""
                col_key = row[3] if len(row) > 3 else ""
                comment = row[4] if len(row) > 4 else ""
            else:
                continue
            columns.append({
                "columnName": col_name,
                "dataType": data_type,
                "isPrimaryKey": "PRI" in (col_key or ""),
                "isNullable": "YES" in (is_nullable or ""),
                "comment": comment or "",
            })
        logger.info(f"Table [{table_name}]: got {len(columns)} columns via information_schema")
        return {"tableName": table_name, "columns": columns, "count": len(columns)}

    logger.warning(f"Failed to get structure for {table_name} on db {db_id}: {result.get('message', '')}")
    return {"tableName": table_name, "columns": [], "count": 0}


def execute_sql_on_database(db_id: str, sql: str) -> dict:
    """在指定数据库上执行 SQL"""
    return _api_post(f"database/{db_id}/execute-sql", {"sql": sql}, timeout=120)


# ===========================
# 数据集 / 指标（补充上下文）
# ===========================

def fetch_datasets_for_database(db_id: str) -> list:
    """获取与指定数据库关联的所有数据集（用户管理的补充信息）"""
    resp = _api_get("dataset/list")
    if not resp.get("success"):
        return []
    return [ds for ds in resp.get("datasets", []) if ds.get("databaseId") == db_id]


def fetch_all_indicators() -> list:
    resp = _api_get("indicator/list")
    return resp.get("indicators", []) if resp.get("success") else []


def fetch_indicators_for_datasets(dataset_ids: list) -> list:
    """获取关联到指定数据集的指标"""
    all_indicators = fetch_all_indicators()
    if not dataset_ids:
        return all_indicators
    result = []
    for ind in all_indicators:
        ind_ds_id = ind.get("datasetId", "")
        if ind_ds_id and ind_ds_id in dataset_ids:
            result.append(ind)
    return result


def _fetch_dataset_structure_inner(dataset_id: str) -> dict:
    """通过数据集ID获取表结构（含字段标注）"""
    struct_resp = _api_get(f"dataset/{dataset_id}/structure")
    columns = struct_resp.get("columns", []) if struct_resp.get("success") else []
    fields_resp = _api_get(f"dataset/{dataset_id}/fields")
    annotations = {}
    if fields_resp.get("success"):
        for fa in fields_resp.get("fields", []):
            annotations[fa.get("columnName", "")] = fa
    merged = []
    for col in columns:
        ann = annotations.get(col.get("columnName", ""), {})
        merged.append({
            "columnName": col.get("columnName", ""),
            "dataType": col.get("dataType", ""),
            "isPrimaryKey": ann.get("isPrimaryKey", col.get("isPrimaryKey", False)),
            "comment": ann.get("columnComment", col.get("comment", "")),
            "annotation": ann.get("annotation", ""),
            "businessMeaning": ann.get("businessMeaning", ""),
            "dataCategory": ann.get("dataCategory", ""),
        })
    return {"tableName": struct_resp.get("tableName", ""), "columns": merged, "count": len(merged)}


def fetch_indicator_detail(indicator_id: str) -> dict:
    resp = _api_get(f"indicator/{indicator_id}")
    if not resp.get("success"):
        return {}
    ind = resp.get("data", {})
    linkage_resp = _api_get(f"indicator/{indicator_id}/linkage")
    if linkage_resp.get("success"):
        linkage = linkage_resp.get("data", {})
        ind["linkedDatasetId"] = linkage.get("datasetId", "")
        ind["linkedDatasetName"] = linkage.get("datasetName", "")
        ind["linkedFields"] = linkage.get("linkedFields", [])
        ind["fieldMapping"] = ind.get("fieldMapping") or linkage.get("fieldMapping", "{}")
        ind["calculationMethod"] = ind.get("calculationMethod") or linkage.get("calculationMethod", "")
    return ind


def fetch_evaluation_context_for_database(db_id: str, selected_tables: list = None) -> dict:
    """
    获取评估所需的完整上下文：
    - 从数据库实时读取所有表的 DDL
    - 从数据集管理获取补充标注
    - 从指标管理获取指标定义
    """
    # 1. 获取数据库中的所有表
    all_tables = fetch_database_tables(db_id)
    if selected_tables:
        target_tables = [t for t in selected_tables if t in all_tables]
    else:
        target_tables = all_tables

    # 2. 找到与该数据库关联的数据集（补充信息）
    linked_datasets = fetch_datasets_for_database(db_id)
    dataset_table_map = {ds.get("tableName", ""): ds for ds in linked_datasets}

    # 3. 找到关联的指标
    linked_ds_ids = [ds.get("id") for ds in linked_datasets]
    linked_indicators = fetch_indicators_for_datasets(linked_ds_ids)

    # 4. 读取每个表的结构（优先从数据集标注，其次直接读 information_schema）
    schemas = []
    for table_name in target_tables:
        ds = dataset_table_map.get(table_name)
        if ds:
            schema = _fetch_dataset_structure_inner(ds.get("id"))
            schema["datasetName"] = ds.get("name", "")
            schema["datasetId"] = ds.get("id", "")
            schema["description"] = ds.get("description", "")
        else:
            schema = fetch_table_structure(db_id, table_name)
            schema["datasetName"] = table_name
            schema["datasetId"] = ""
            schema["description"] = ""
        schemas.append(schema)

    return {
        "schemas": schemas,
        "indicators": linked_indicators,
        "all_tables": all_tables,
        "database_name": ""
    }
