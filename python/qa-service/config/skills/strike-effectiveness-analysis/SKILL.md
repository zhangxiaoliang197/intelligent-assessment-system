---
id: strike-effectiveness-analysis
order: 3
name: 火力打击效能分析
description: 从任务计划、打击战果到武器使用情况逐层核验火力打击效果。
category: 火力打击
triggers:
- 打击效能
- 火力打击
- 毁伤效果
- 命中率
recommendedQuestions:
- 评估本轮火力打击效能，分析命中和摧毁效果
steps:
- id: mission
  name: 查询打击任务
  description: 核验任务规模、目标与执行状态。
  datasetKeywords:
  - 任务
  - mission
  - 行动
  - 出动
  - 目标任务
- id: combat-result
  name: 查询打击战果
  description: 统计命中数、摧毁数和目标达成情况。
  datasetKeywords:
  - 战果
  - 命中
  - 摧毁
  - 打击结果
- id: weapon
  name: 查询武器使用
  description: 分析武器类型、发射数量与实际贡献。
  datasetKeywords:
  - 武器
  - weapon
  - 弹药
  - 火力
  - 装备效能
outputInstruction: 给出任务完成率、命中摧毁表现和武器使用效率，并指出低效环节。
---

# 火力打击效能分析

从任务计划、打击战果到武器使用情况逐层核验火力打击效果。

## 基本信息

- Skill ID：`strike-effectiveness-analysis`
- 分类：火力打击

## 触发词

- 打击效能
- 火力打击
- 毁伤效果
- 命中率

## 推荐问题

- 评估本轮火力打击效能，分析命中和摧毁效果

## 执行步骤

### 1. 查询打击任务

核验任务规模、目标与执行状态。

- 步骤 ID：`mission`
- 数据集关键词：`任务`、`mission`、`行动`、`出动`、`目标任务`
- 操作：`dataset_query`

### 2. 查询打击战果

统计命中数、摧毁数和目标达成情况。

- 步骤 ID：`combat-result`
- 数据集关键词：`战果`、`命中`、`摧毁`、`打击结果`
- 操作：`dataset_query`

### 3. 查询武器使用

分析武器类型、发射数量与实际贡献。

- 步骤 ID：`weapon`
- 数据集关键词：`武器`、`weapon`、`弹药`、`火力`、`装备效能`
- 操作：`dataset_query`

## 输出要求

给出任务完成率、命中摧毁表现和武器使用效率，并指出低效环节。
