---
id: relationship-analysis
order: 29
name: 跨表关联线索分析
description: 分别查询两个相关数据集，再基于共同业务键、时间或分类维度汇总关联线索。
category: 关联分析
triggers:
- 跨表关联
- 关联分析
- 两个表对比
- 数据关联
- 关系分析
recommendedQuestions:
- 分析两个相关数据集之间的关联线索
- 对比主表和明细表的共同业务维度
steps:
- id: primary-data
  name: 查询主数据
  description: 查询主数据中的业务键、分类、时间和核心指标摘要。
  datasetKeywords:
  - 主数据
  - 主表
  - 基础表
  - master
  - 主体
- id: related-data
  name: 查询关联数据
  description: 查询关联数据中的共同业务键、分类、时间和指标摘要。
  datasetKeywords:
  - 明细
  - 关联表
  - 从表
  - detail
  - 记录
outputInstruction: 严格基于两个单表查询结果指出共同键、覆盖差异和关联线索；没有行级连接证据时不得声称已完成精确关联。
---

# 跨表关联线索分析

分别查询两个相关数据集，再基于共同业务键、时间或分类维度汇总关联线索。

## 基本信息

- Skill ID：`relationship-analysis`
- 分类：关联分析

## 触发词

- 跨表关联
- 关联分析
- 两个表对比
- 数据关联
- 关系分析

## 推荐问题

- 分析两个相关数据集之间的关联线索
- 对比主表和明细表的共同业务维度

## 执行步骤

### 1. 查询主数据

查询主数据中的业务键、分类、时间和核心指标摘要。

- 步骤 ID：`primary-data`
- 数据集关键词：`主数据`、`主表`、`基础表`、`master`、`主体`
- 操作：`dataset_query`

### 2. 查询关联数据

查询关联数据中的共同业务键、分类、时间和指标摘要。

- 步骤 ID：`related-data`
- 数据集关键词：`明细`、`关联表`、`从表`、`detail`、`记录`
- 操作：`dataset_query`

## 输出要求

严格基于两个单表查询结果指出共同键、覆盖差异和关联线索；没有行级连接证据时不得声称已完成精确关联。
