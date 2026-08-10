# 数据源 / 数据库功能测试套件

针对系统「数据源」与数据库管理功能的自动化测试，覆盖 admin-service（Java）与
qa-service（Python）对外暴露的全部数据源相关接口，以及 5 种数据库方言
（MySQL / PostgreSQL / Oracle / SQL Server / 达梦 V8.1）的 SQL 归一化与校验逻辑。

## 测试范围

| 模块 | 覆盖内容 |
|------|----------|
| `test_unit_dialect.py` | 方言归一化、SQL 交叉校验矩阵、提示词规则、意图路由（离线单测，无需服务） |
| `test_admin_db_config.py` | 数据库配置 CRUD、密码脱敏、默认值、5 种类型注册 |
| `test_admin_connection.py` | 连接测试：可达库成功、不可达库/缺驱动优雅失败 |
| `test_admin_tables.py` | 表列表、列元数据、表结构、主键标记、非法表名 |
| `test_admin_sql_execution.py` | SQL 执行安全门（只读校验、危险关键字/函数/包）、真实查询 |
| `test_admin_dataset_indicator.py` | 数据集 CRUD、字段标注、指标 CRUD、指标-数据集关联、LLM 导出 |
| `test_qa_data_sources.py` | qa-service 数据源代理、Skill 目录、健康检查 |
| `test_edge_cases.py` | 空密码、中文/特殊字符名、未知类型、端口 0、去重 |

## 运行前提

1. **admin-service（:10258）和 qa-service（:10253）已启动**（本地开发模式）。
2. **至少一个可连接的数据库配置**（当前环境：MySQL 指向元数据库 `assessment`，
   已连接）。没有可连接库时，涉及真实库的用例会自动跳过，其余用例仍可运行。
3. 使用项目 venv（已含 `requests`）。

## 运行方式

在项目根目录执行：

```powershell
# 全部用例
.\.venv\Scripts\python.exe tests\database\run_tests.py

# 详细输出
.\.venv\Scripts\python.exe tests\database\run_tests.py -v

# 只跑某几个模块
.\.venv\Scripts\python.exe tests\database\run_tests.py dialect sql_execution

# 指定服务地址
.\.venv\Scripts\python.exe tests\database\run_tests.py --admin-url http://localhost:10258 --qa-url http://localhost:10253
```

等价地，也可直接：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests\database -v
```

## 约定

- 测试创建的所有临时数据库配置 / 数据集 / 指标均以 `db_` / `ds_` / `ind_` 为前缀，
  并在 `tearDownClass` 中自动清理，不影响现有数据。
- 集成用例直接打运行中的服务（真实 HTTP），断言与 admin-service / qa-service 代码
  中的硬编码中文消息一一对应；若后端文案调整，需同步更新断言。
