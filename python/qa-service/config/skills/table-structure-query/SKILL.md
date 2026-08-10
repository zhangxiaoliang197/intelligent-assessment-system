---
id: table-structure-query
order: 18
name: 表结构查询
description: 读取指定表或当前数据源所有表的字段名、数据类型、空值约束、主键和字段说明。
category: 元数据查询
triggers:
- 表结构
- 字段结构
- 字段类型
- 列信息
- 查看字段
recommendedQuestions:
- 查看当前数据源的表结构
- 查询指定表有哪些字段及字段类型
steps:
- id: table-structure
  name: 读取表字段结构
  description: 通过只读 JDBC 元数据读取用户点名表；未点名时汇总所有表的字段结构。
  datasetKeywords:
  - 表结构
  - 字段
  - column
  - schema
  - 数据类型
  operation: table_structure
outputInstruction: 逐表输出字段名、数据类型、是否可空、是否主键、字段注释和业务含义；用户点名表时只展示目标表。
---

# 表结构查询

读取指定表或当前数据源所有表的字段名、数据类型、空值约束、主键和字段说明。

## 基本信息

- Skill ID：`table-structure-query`
- 分类：元数据查询

## 触发词

- 表结构
- 字段结构
- 字段类型
- 列信息
- 查看字段

## 推荐问题

- 查看当前数据源的表结构
- 查询指定表有哪些字段及字段类型

## 执行步骤

### 1. 读取表字段结构

通过只读 JDBC 元数据读取用户点名表；未点名时汇总所有表的字段结构。

- 步骤 ID：`table-structure`
- 数据集关键词：`表结构`、`字段`、`column`、`schema`、`数据类型`
- 操作：`table_structure`

## 输出要求

逐表输出字段名、数据类型、是否可空、是否主键、字段注释和业务含义；用户点名表时只展示目标表。
