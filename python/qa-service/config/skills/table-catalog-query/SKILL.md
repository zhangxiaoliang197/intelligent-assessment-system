---
id: table-catalog-query
order: 17
name: 数据表目录查询
description: 列出当前数据源中的物理表、数据集名称、Schema、Catalog 和字段数量。
category: 元数据查询
triggers:
- 有哪些表
- 表目录
- 表清单
- 数据表列表
- 所有表
recommendedQuestions:
- 列出当前数据源中的所有表
- 当前数据库有哪些表及各表字段数量
steps:
- id: table-catalog
  name: 读取数据表目录
  description: 通过只读 JDBC 元数据列出当前数据源中的全部可见物理表。
  datasetKeywords:
  - 数据表
  - table
  - 表目录
  - 表清单
  - 物理表
  operation: table_catalog
outputInstruction: 按表名排序输出表名、业务数据集名称、来源、Schema、Catalog 和字段数量。
---

# 数据表目录查询

列出当前数据源中的物理表、数据集名称、Schema、Catalog 和字段数量。

## 基本信息

- Skill ID：`table-catalog-query`
- 分类：元数据查询

## 触发词

- 有哪些表
- 表目录
- 表清单
- 数据表列表
- 所有表

## 推荐问题

- 列出当前数据源中的所有表
- 当前数据库有哪些表及各表字段数量

## 执行步骤

### 1. 读取数据表目录

通过只读 JDBC 元数据列出当前数据源中的全部可见物理表。

- 步骤 ID：`table-catalog`
- 数据集关键词：`数据表`、`table`、`表目录`、`表清单`、`物理表`
- 操作：`table_catalog`

## 输出要求

按表名排序输出表名、业务数据集名称、来源、Schema、Catalog 和字段数量。
