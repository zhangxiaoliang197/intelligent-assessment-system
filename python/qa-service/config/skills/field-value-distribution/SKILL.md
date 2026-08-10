---
id: field-value-distribution
order: 21
name: 字段取值分布
description: 统计分类字段各取值的数量、占比和集中程度，帮助快速理解数据构成。
category: 统计分析
triggers:
- 取值分布
- 值分布
- 分类分布
- 各类型占比
- 频次分布
recommendedQuestions:
- 统计指定字段的取值分布和占比
- 这个分类字段主要有哪些值
steps:
- id: distribution
  name: 统计字段分布
  description: 按用户指定分类字段分组，统计各取值数量并按数量降序排列。
  datasetKeywords:
  - 分类
  - 类型
  - 状态
  - 等级
  - 分布
outputInstruction: 输出取值、数量、占比、Top 取值和长尾情况，并单独标注空值。
---

# 字段取值分布

统计分类字段各取值的数量、占比和集中程度，帮助快速理解数据构成。

## 基本信息

- Skill ID：`field-value-distribution`
- 分类：统计分析

## 触发词

- 取值分布
- 值分布
- 分类分布
- 各类型占比
- 频次分布

## 推荐问题

- 统计指定字段的取值分布和占比
- 这个分类字段主要有哪些值

## 执行步骤

### 1. 统计字段分布

按用户指定分类字段分组，统计各取值数量并按数量降序排列。

- 步骤 ID：`distribution`
- 数据集关键词：`分类`、`类型`、`状态`、`等级`、`分布`
- 操作：`dataset_query`

## 输出要求

输出取值、数量、占比、Top 取值和长尾情况，并单独标注空值。
