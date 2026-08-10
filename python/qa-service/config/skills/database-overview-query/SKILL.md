---
id: database-overview-query
order: 16
name: 数据库基础信息查询
description: 读取当前数据源的数据库类型、产品版本、物理表数量和数据集登记情况。
category: 数据库基础
triggers:
- 数据库基础信息
- 数据库概览
- 数据库版本
- 数据库信息
- 数据源概览
recommendedQuestions:
- 查看当前数据源的数据库基础信息
- 当前数据库是什么类型和版本，有多少张表
steps:
- id: database-overview
  name: 读取数据库概览
  description: 通过只读 JDBC 元数据汇总数据库产品、版本、物理表和数据集数量。
  datasetKeywords:
  - 数据库
  - database
  - 数据源
  - 基础信息
  - 概览
  operation: database_overview
outputInstruction: 以清单形式输出数据库名称、类型、产品、版本、物理表数量、已登记数据集数量和实时发现表数量。
---

# 数据库基础信息查询

读取当前数据源的数据库类型、产品版本、物理表数量和数据集登记情况。

## 基本信息

- Skill ID：`database-overview-query`
- 分类：数据库基础

## 触发词

- 数据库基础信息
- 数据库概览
- 数据库版本
- 数据库信息
- 数据源概览

## 推荐问题

- 查看当前数据源的数据库基础信息
- 当前数据库是什么类型和版本，有多少张表

## 执行步骤

### 1. 读取数据库概览

通过只读 JDBC 元数据汇总数据库产品、版本、物理表和数据集数量。

- 步骤 ID：`database-overview`
- 数据集关键词：`数据库`、`database`、`数据源`、`基础信息`、`概览`
- 操作：`database_overview`

## 输出要求

以清单形式输出数据库名称、类型、产品、版本、物理表数量、已登记数据集数量和实时发现表数量。
