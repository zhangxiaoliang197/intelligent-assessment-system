"""
工具函数：从 Java admin-service 获取数据源、表结构、指标定义，以及 SQL 执行。

============================================================
模块在系统架构中的位置
============================================================

本模块位于 qa-service 的多智能体框架层（agents/），是评估工作流与
Java admin-service 之间的 HTTP 通信层（Communication Layer）。

它封装了所有对 admin-service REST API 的调用，提供以下能力：
1. 数据源管理：获取数据库配置列表、表名列表
2. 表结构查询：通过 JDBC 元数据读取当前数据源的真实列信息
3. SQL 代理执行：将 SQL 转发到 admin-service，由后者在目标数据库上执行
4. 数据集/指标管理：获取用户管理的数据集、指标定义及其关联关系

============================================================
跨服务通信说明
============================================================

admin-service 是 Java Spring Boot 服务，监听端口 10258。
本模块通过 HTTP GET/POST 与其通信（使用标准库 urllib，零外部依赖）。

在 Docker 环境中，ADMIN_SERVICE_URL 通过环境变量覆盖为容器名：
  - 本地开发：http://localhost:10258
  - Docker：   http://assessment-admin:10258

============================================================
安全说明
============================================================
- SSL 证书校验已关闭（_ssl_ctx），因为内网 Docker 环境使用自签名证书
- SQL 执行通过 admin-service 代理，由 Java 端做参数化查询防护
- 所有 API 调用都有超时限制（GET 30s，POST 120s），防止连接挂死
"""
import hashlib
import json
import urllib.request
import urllib.error
import urllib.parse
import ssl
import os
import logging
import re
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("evaluation.tools")

_DATABASE_PROFILE_KEYS = (
    "databaseType",
    "databaseProductName",
    "databaseProductVersion",
    "identifierQuoteString",
)

# admin-service 的基地址，支持通过环境变量覆盖（Docker 部署时设为容器名）
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")

# 创建 SSL 上下文并关闭证书校验
# 原因：内网 Docker 环境中使用自签名证书，无需严格校验证书链
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False  # 不验证主机名
_ssl_ctx.verify_mode = ssl.CERT_NONE  # 不验证证书


# ============================================================
# 内部 HTTP 通信基元
# ============================================================

def _api_get(path: str, timeout: int = 30) -> dict:
    """向 admin-service 发送 GET 请求。

    所有 GET 类型的工具函数最终都调用此函数与 admin-service 通信。

    Args:
        path:    API 路径（相对于 /api/admin/，例如 "database/list"）
        timeout: 请求超时时间（秒），默认 30 秒

    Returns:
        API 响应的 JSON 字典。成功时包含业务数据，失败时包含 {"success": False, "message": "..."}
    """
    # 拼接完整 URL：{ADMIN_SERVICE_URL}/api/admin/{path}
    url = f"{ADMIN_SERVICE_URL}/api/admin/{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"API GET {path} 失败: {e}")
        # 返回统一错误格式，调用方通过 success 字段判断是否成功
        return {"success": False, "message": str(e)}


def _api_post(path: str, body: dict, timeout: int = 120) -> dict:
    """向 admin-service 发送 POST 请求。

    所有 POST 类型的工具函数（主要是 SQL 执行）最终调用此函数。

    Args:
        path:    API 路径（相对于 /api/admin/）
        body:    请求体字典（将被 JSON 序列化）
        timeout: 请求超时时间（秒），默认 120 秒（SQL 执行可能较慢）

    Returns:
        API 响应的 JSON 字典。成功时包含业务数据，失败时包含 {"success": False, "message": "..."}
    """
    url = f"{ADMIN_SERVICE_URL}/api/admin/{path}"
    data = json.dumps(body).encode("utf-8")  # 将请求体序列化为 UTF-8 字节
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"API POST {path} failed: {e}")
        return {"success": False, "message": str(e)}


# ============================================================
# 数据源（数据库配置）相关
# ============================================================
# 以下函数封装了对 admin-service 中 "数据库配置" 管理模块的调用。
# 数据库配置是用户在管理后台录入的目标数据库连接信息，
# 评估系统通过这些配置连接到用户的实际业务数据库。

def fetch_all_databases() -> list:
    """获取所有数据库配置列表。

    调用 admin-service 的 GET /api/admin/database/list 接口。

    Returns:
        数据库配置对象列表，每个元素包含 id/name/type/host/port/databaseName 等字段。
        调用失败时返回空列表 []。
    """
    resp = _api_get("database/list")
    return resp.get("databases", []) if resp.get("success") else []


def fetch_database_config(db_id: str) -> dict:
    """获取单个数据库配置（含 type 字段，用于判断数据库方言）。

    从 fetch_all_databases() 的结果中按 id 过滤。

    Args:
        db_id: 数据库配置 ID

    Returns:
        数据库配置字典，包含 id/name/type/host/port/databaseName 等字段。
        未找到时返回空字典 {}。
    """
    dbs = fetch_all_databases()
    for db in dbs:
        if db.get("id") == db_id:
            return db
    return {}


def fetch_database_tables(
    db_id: str, include_columns: bool = False, strict: bool = False
) -> list:
    """获取指定数据库中的所有表名。

    调用 admin-service 的 GET /api/admin/database/{db_id}/tables 接口。
    admin-service 会连接目标数据库，通过 JDBC 元数据获取实际表名。

    在工作流中的角色：这是数据探查（Discovery）阶段的第一步，
    为后续的表结构读取和 SQL 生成提供可用表列表。

    Args:
        db_id: 数据库配置 ID

    Returns:
        表名字符串列表，如 ["t_combat_record", "t_equipment", "t_mission"]。
        调用失败或数据库无表时返回空列表 []。
    """
    query = "?includeColumns=true" if include_columns else ""
    resp = _api_get(f"database/{urllib.parse.quote(str(db_id), safe='')}/tables{query}")
    if resp.get("success"):
        tables = [
            table for table in resp.get("tables", [])
            if isinstance(table, dict) and table.get("tableName")
        ]
        if include_columns:
            profile = {key: resp.get(key, "") for key in _DATABASE_PROFILE_KEYS}
            for table in tables:
                table.update(profile)
            return tables
        return [table.get("tableName", "") for table in tables]
    if strict:
        raise RuntimeError(resp.get("message") or "无法读取数据源中的物理表")
    return []


def fetch_table_structure(db_id: str, table_name: str) -> dict:
    """通过 JDBC 元数据读取当前数据源中的真实表结构。

    数据库类型、数据库名和系统目录差异由 admin-service/JDBC 驱动处理；
    这里不拼接任何数据库方言专用的系统表查询。
    """
    if (
        not isinstance(table_name, str)
        or not table_name.strip()
        or len(table_name) > 256
        or re.search(r"['\"`;\x00-\x1f\x7f]", table_name)
        or "--" in table_name
        or "/*" in table_name
        or "*/" in table_name
    ):
        logger.warning("读取元数据时拒绝不安全的表名")
        return {"tableName": "", "columns": [], "count": 0}
    safe_table_name = table_name.strip()
    query = urllib.parse.urlencode({"tableName": safe_table_name})
    result = _api_get(
        f"database/{urllib.parse.quote(str(db_id), safe='')}/table-structure?{query}"
    )
    if result.get("success"):
        columns = result.get("columns", [])
        columns = columns if isinstance(columns, list) else []
        structure = {
            "tableName": result.get("tableName") or safe_table_name,
            "columns": columns,
            "count": len(columns),
        }
        for key in _DATABASE_PROFILE_KEYS:
            structure[key] = result.get(key, "")
        return structure

    logger.warning(
        "Failed to get structure for %s on db %s: %s",
        safe_table_name,
        db_id,
        result.get("message", ""),
    )
    return {"tableName": safe_table_name, "columns": [], "count": 0}


def execute_sql_on_database(db_id: str, sql: str) -> dict:
    """在指定数据库上执行 SQL 查询。

    通过 admin-service 的 POST /api/admin/database/{db_id}/execute-sql 接口
    代理执行 SQL。admin-service（Java 端）负责 SQL 注入防护和连接池管理。

    在工作流中的角色：这是执行（Execution）阶段的核心函数，
    由 LLM 生成的 SQL 经安全校验后通过此函数实际执行。

    Args:
        db_id:   数据库配置 ID
        sql:     要执行的 SQL 语句（仅允许 SELECT/WITH 开头）

    Returns:
        字典，包含 success / columns / rows 等字段。
        success 为 True 时包含查询结果，为 False 时包含 message 错误信息。
    """
    return _api_post(f"database/{db_id}/execute-sql", {"sql": sql}, timeout=120)


# ============================================================
# 数据集 / 指标（用户管理的补充上下文）
# ============================================================
# 数据集（Dataset）是用户在管理后台定义的业务数据资产，
# 它将物理表与业务描述、字段标注关联起来。
# 指标（Indicator）是用户预定义的计算规则，如命中率、摧毁率等。
# 这些补充信息帮助 LLM 更准确地理解表结构并生成正确的 SQL。

def fetch_datasets_for_database(db_id: str, strict: bool = False) -> list:
    """获取与指定数据库关联的所有数据集（用户管理的补充信息）。

    先调用 GET /api/admin/dataset/list 获取全部数据集，
    然后按 databaseId 过滤，只返回与目标数据库关联的数据集。

    数据集包含对表的业务描述和字段标注，比纯技术表结构更有助于
    LLM 理解数据的业务含义。

    Args:
        db_id: 数据库配置 ID

    Returns:
        与该数据库关联的数据集对象列表。
        每个数据集包含 id/name/tableName/description/databaseId 等字段。
        无关联数据集时返回空列表 []。
    """
    resp = _api_get("dataset/list")
    if not resp.get("success"):
        if strict:
            raise RuntimeError(resp.get("message") or "数据集目录服务不可用")
        return []
    # 按 databaseId 过滤：只保留与目标数据库关联的数据集
    return [ds for ds in resp.get("datasets", []) if ds.get("databaseId") == db_id]


def fetch_skill_datasets_for_database(
    db_id: str, strict: bool = False, include_columns: bool = True
) -> list:
    """构建 Skill 使用的当前数据源目录。

    已登记 Dataset 只作为业务名称、描述和字段标注的增强信息。目录的
    基础始终来自用户当前选择的数据源中的真实物理表，因此新环境无需先
    按开发环境的数据库名或表名重建 Dataset 记录。
    """
    table_query = "?includeColumns=true" if include_columns else ""
    table_path = (
        f"database/{urllib.parse.quote(str(db_id), safe='')}/tables{table_query}"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        dataset_future = pool.submit(_api_get, "dataset/list")
        table_future = pool.submit(_api_get, table_path)
        dataset_response = dataset_future.result()
        table_response = table_future.result()
    dataset_ok = bool(dataset_response.get("success"))
    table_ok = bool(table_response.get("success"))
    if strict and not dataset_ok and not table_ok:
        message = table_response.get("message") or dataset_response.get("message")
        raise RuntimeError(message or "数据集目录与物理表目录均不可用")

    configured = [
        item for item in dataset_response.get("datasets", [])
        if isinstance(item, dict)
        and str(item.get("databaseId") or "") == str(db_id)
        and item.get("tableName")
    ] if dataset_ok else []
    physical_tables = [
        item for item in table_response.get("tables", [])
        if isinstance(item, dict) and item.get("tableName")
    ] if table_ok else []
    physical_by_name = {
        str(item["tableName"]).casefold(): item for item in physical_tables
    }
    database_profile = {
        key: table_response.get(key, "") for key in _DATABASE_PROFILE_KEYS
    }

    merged = []
    covered_tables = set()
    for item in configured:
        table_name = str(item.get("tableName") or "").strip()
        physical = physical_by_name.get(table_name.casefold())
        # 当物理目录可读时，不让已失效的旧 Dataset 绑定进入当前数据源。
        if table_ok and physical is None:
            continue
        dataset = dict(item)
        dataset["source"] = "configured"
        dataset["isLiveTable"] = False
        if physical:
            dataset["columns"] = physical.get("columns", [])
            dataset["schemaName"] = physical.get("schemaName", "")
            dataset["catalogName"] = physical.get("catalogName", "")
        dataset.update(database_profile)
        merged.append(dataset)
        covered_tables.add(table_name.casefold())

    for table in physical_tables:
        table_name = str(table.get("tableName") or "").strip()
        if not table_name or table_name.casefold() in covered_tables:
            continue
        stable_key = hashlib.sha256(
            f"{db_id}\0{table_name}".encode("utf-8")
        ).hexdigest()[:24]
        live_dataset = {
            "id": f"live-{stable_key}",
            "name": table_name,
            "tableName": table_name,
            "description": "当前数据源实时发现的物理表",
            "databaseId": db_id,
            "source": "live",
            "isLiveTable": True,
            "columns": table.get("columns", []),
            "schemaName": table.get("schemaName", ""),
            "catalogName": table.get("catalogName", ""),
        }
        live_dataset.update(database_profile)
        merged.append(live_dataset)
    return merged


def fetch_all_indicators() -> list:
    """获取系统中所有指标定义。

    调用 GET /api/admin/indicator/list 接口。

    Returns:
        指标对象列表，每个包含 id/name/formula/description/datasetId 等字段。
        调用失败时返回空列表 []。
    """
    resp = _api_get("indicator/list")
    return resp.get("indicators", []) if resp.get("success") else []


def fetch_indicators_for_datasets(dataset_ids: list) -> list:
    """获取关联到指定数据集的指标定义。

    先从 admin-service 获取全部指标，然后按 datasetId 过滤。
    如果 dataset_ids 为空列表，则返回全部指标（不做过滤）。

    指标定义了业务计算逻辑（如命中率 = 命中次数 / 攻击次数），
    LLM 可据此生成包含聚合计算的 SQL。

    Args:
        dataset_ids: 数据集 ID 列表（用于过滤关联的指标）

    Returns:
        与指定数据集关联的指标对象列表。
        如果 dataset_ids 为空，返回全部指标。
    """
    all_indicators = fetch_all_indicators()
    # 如果未指定数据集 ID，返回全部指标
    if not dataset_ids:
        return all_indicators
    result = []
    for ind in all_indicators:
        ind_ds_id = ind.get("datasetId", "")
        # 指标的 datasetId 在 dataset_ids 列表中 → 保留
        if ind_ds_id and ind_ds_id in dataset_ids:
            result.append(ind)
    return result


def _fetch_dataset_structure_inner(dataset_id: str) -> dict:
    """通过数据集 ID 获取表结构（含用户标注的字段信息）。

    这是获取表结构的"增强路径"：不仅读取物理表结构，还合并用户在
    管理后台为字段添加的业务标注（annotation/businessMeaning/dataCategory）。
    优先于直接读取 JDBC 元数据的 fetch_table_structure。

    实现步骤（并行优化后）：
    1. 并行调用 dataset/{id}/structure 和 dataset/{id}/fields（2→1 个HTTP往返）
    2. 将两者按 columnName 合并，标注信息覆盖物理结构信息

    Args:
        dataset_id: 数据集 ID

    Returns:
        字典，包含：
        - tableName: 物理表名
        - columns:   合并后的列信息列表，每列额外含 annotation/businessMeaning/dataCategory
        - count:     列数量
    """
    # 步骤 1：并行获取物理表结构和字段标注（2→1 个HTTP往返）
    with ThreadPoolExecutor(max_workers=2) as pool:
        struct_future = pool.submit(_api_get, f"dataset/{dataset_id}/structure")
        fields_future = pool.submit(_api_get, f"dataset/{dataset_id}/fields")

    struct_resp = struct_future.result()
    fields_resp = fields_future.result()
    columns = struct_resp.get("columns", []) if struct_resp.get("success") else []

    # 以 columnName 为 key 建立标注字典，便于快速查找
    annotations = {}
    if fields_resp.get("success"):
        for fa in fields_resp.get("fields", []):
            annotations[fa.get("columnName", "")] = fa

    # 步骤 2：合并物理结构与用户标注
    merged = []
    for col in columns:
        ann = annotations.get(col.get("columnName", ""), {})
        # 标注信息优先于物理结构信息（如 isPrimaryKey 以标注为准）
        merged.append({
            "columnName": col.get("columnName", ""),
            "dataType": col.get("dataType", ""),
            "isPrimaryKey": ann.get("isPrimaryKey", col.get("isPrimaryKey", False)),
            "comment": ann.get("columnComment", col.get("comment", "")),
            "annotation": ann.get("annotation", ""),        # 用户自定义标注
            "businessMeaning": ann.get("businessMeaning", ""),  # 业务含义说明
            "dataCategory": ann.get("dataCategory", ""),    # 数据分类（如 战果/战损/资源）
        })
    structure = {
        "tableName": struct_resp.get("tableName", ""),
        "columns": merged,
        "count": len(merged),
    }
    for key in _DATABASE_PROFILE_KEYS:
        structure[key] = struct_resp.get(key, "")
    return structure


def fetch_indicator_detail(indicator_id: str) -> dict:
    """获取单个指标的详细信息（含关联的字段映射和计算方法）。

    先调用 indicator/{id} 获取指标基本信息，
    再调用 indicator/{id}/linkage 获取指标与数据集的联动配置。
    两次调用的结果合并为一个完整的指标详情字典。

    联动配置（linkage）说明：
    指标需要关联到具体的数据集字段才能计算。linkage 记录了：
    - linkedDatasetId/Name: 关联的数据集
    - linkedFields: 指标使用到哪些字段
    - fieldMapping: 字段映射关系（JSON 字符串）
    - calculationMethod: 计算方法的自然语言描述

    Args:
        indicator_id: 指标 ID

    Returns:
        合并后的指标详情字典。如果 indicator_id 无效，返回空字典 {}。
    """
    # 获取指标基本信息
    resp = _api_get(f"indicator/{indicator_id}")
    if not resp.get("success"):
        return {}
    ind = resp.get("data", {})

    # 获取指标联动配置（关联的数据集、字段映射等）
    linkage_resp = _api_get(f"indicator/{indicator_id}/linkage")
    if linkage_resp.get("success"):
        linkage = linkage_resp.get("data", {})
        # 将联动信息合并到指标对象中
        ind["linkedDatasetId"] = linkage.get("datasetId", "")
        ind["linkedDatasetName"] = linkage.get("datasetName", "")
        ind["linkedFields"] = linkage.get("linkedFields", [])
        # fieldMapping 和 calculationMethod 优先使用指标自身配置，其次用联动配置
        ind["fieldMapping"] = ind.get("fieldMapping") or linkage.get("fieldMapping", "{}")
        ind["calculationMethod"] = ind.get("calculationMethod") or linkage.get("calculationMethod", "")
    return ind


def search_knowledge_base(query: str, top_k: int = 3) -> list:
    """通过 HTTP 调用 knowledge-service 的知识库搜索接口。

    Args:
        query: 搜索查询字符串
        top_k: 返回的最多结果数（默认 3）

    Returns:
        搜索结果的 list，搜索失败返回空列表 []。
    """
    KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:10252")
    try:
        body = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
        req = urllib.request.Request(
            f"{KNOWLEDGE_SERVICE_URL}/knowledge/search",
            data=body,
            method="POST"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("results", [])
    except Exception as e:
        logger.error(f"knowledge_base 搜索失败: {e}")
        return []


def fetch_evaluation_context_for_database(db_id: str, selected_tables: list = None) -> dict:
    """获取评估所需的完整上下文信息。

    这是数据探查（Discovery）阶段的"一站式"聚合函数，一次调用即可获取
    评估工作流所需的全部元数据。它整合了以下信息：
    1. 数据库中所有表的结构（从 JDBC 元数据实时读取）
    2. 用户管理的数据集标注（业务描述、字段标注）
    3. 用户管理的指标定义（计算规则、字段映射）

    表结构获取优先级：数据集标注 > JDBC 元数据直接查询。
    如果某个表有对应的数据集，则使用带标注的增强结构；
    如果没有，则使用 JDBC 返回的标准结构。

    在工作流中的角色：这是 orchestrator_node 之后、sql_generator_node 之前
    调用的核心函数，为 LLM 提供完整的数据库元数据上下文。

    Args:
        db_id:           数据库配置 ID
        selected_tables: 可选，要限制读取的表名列表。为 None 时读取全部表。
                         用于在 combat_effectiveness/air_superiority 模式中
                         只读取 SQL 模板中用到的表，减少 token 消耗。

    Returns:
        字典，包含：
        - schemas:       表结构列表（每个元素含 tableName/columns/datasetName 等）
        - indicators:    关联的指标定义列表
        - all_tables:    数据库中所有表名列表
        - database_name: 数据库名称（当前未填充，预留字段）
    """
    # 步骤 1：获取数据库中的所有表名
    all_tables = fetch_database_tables(db_id)
    if selected_tables:
        # 如果指定了表名列表，只保留实际存在的表（过滤无效表名）
        target_tables = [t for t in selected_tables if t in all_tables]
    else:
        target_tables = all_tables

    # 步骤 2：找到与该数据库关联的数据集（用户管理的补充信息）
    linked_datasets = fetch_datasets_for_database(db_id)
    # 建立表名 → 数据集对象的映射，便于快速查找每个表是否有对应的数据集
    dataset_table_map = {ds.get("tableName", ""): ds for ds in linked_datasets}

    # 步骤 3：找到关联的指标定义
    linked_ds_ids = [ds.get("id") for ds in linked_datasets]
    linked_indicators = fetch_indicators_for_datasets(linked_ds_ids)

    # 步骤 4：逐个读取每个表的结构
    # 优先级：有数据集的表用增强结构（含业务标注），无数据集的表用 JDBC 元数据
    schemas = []
    for table_name in target_tables:
        ds = dataset_table_map.get(table_name)
        if ds:
            # 有数据集：使用增强路径，合并用户标注信息
            schema = _fetch_dataset_structure_inner(ds.get("id"))
            schema["datasetName"] = ds.get("name", "")
            schema["datasetId"] = ds.get("id", "")
            schema["description"] = ds.get("description", "")
        else:
            # 无数据集：使用标准路径，直接从 JDBC 元数据读取
            schema = fetch_table_structure(db_id, table_name)
            schema["datasetName"] = table_name      # 无数据集时以表名作为显示名
            schema["datasetId"] = ""                 # 无关联数据集 ID
            schema["description"] = ""
        schemas.append(schema)

    return {
        "schemas": schemas,              # 表结构列表（含业务标注）
        "indicators": linked_indicators,  # 关联的指标定义
        "all_tables": all_tables,        # 数据库完整表名列表
        "database_name": ""              # 数据库名称（预留字段，当前未填充）
    }
