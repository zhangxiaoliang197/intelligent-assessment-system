---
id: category-comparison-analysis
order: 26
name: 分类对比分析
description: 按部门、地区、类型、状态等分类维度对比数量或指标差异。
category: 统计分析
triggers:
- 分类对比
- 分组对比
- 各类别比较
- 部门对比
- 地区对比
recommendedQuestions:
- 按主要分类对比数量和指标
- 比较各部门或地区的数据差异
steps:
- id: comparison
  name: 执行分类汇总
  description: 按用户指定分类维度聚合数量或指标，并按结果降序排列。
  datasetKeywords:
  - 分类
  - 部门
  - 地区
  - 类型
  - 状态
visualization:
  enabled: true
  preferredType: bar
outputInstruction: 输出各分类的数值、占比、差距和排序，并生成柱状图突出主要差异。
---

# 分类对比分析

按部门、地区、类型、状态等分类维度对比数量或指标差异。

## 基本信息

- Skill ID：`category-comparison-analysis`
- 分类：统计分析

## 触发词

- 分类对比
- 分组对比
- 各类别比较
- 部门对比
- 地区对比

## 推荐问题

- 按主要分类对比数量和指标
- 比较各部门或地区的数据差异

## 执行步骤

### 1. 执行分类汇总

按用户指定分类维度聚合数量或指标，并按结果降序排列。

- 步骤 ID：`comparison`
- 数据集关键词：`分类`、`部门`、`地区`、`类型`、`状态`
- 操作：`dataset_query`

## 可视化

- 启用：是
- 首选类型：`bar`

## 输出要求

输出各分类的数值、占比、差距和排序，并生成柱状图突出主要差异。
