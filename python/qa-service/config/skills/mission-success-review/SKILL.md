---
id: mission-success-review
order: 6
name: 任务完成质量复盘
description: 从任务执行记录出发，对照战果与战损复盘任务完成质量。
category: 任务评估
triggers:
- 任务复盘
- 任务完成率
- 行动复盘
- 执行质量
recommendedQuestions:
- 复盘近期任务完成质量，找出未完成任务的共性原因
steps:
- id: mission
  name: 查询任务执行
  description: 统计任务状态、完成时长与未完成原因。
  datasetKeywords:
  - 任务
  - mission
  - 行动
  - 执行记录
  - 任务完成
- id: combat-result
  name: 查询任务战果
  description: 核验任务对应的命中、摧毁和目标达成。
  datasetKeywords:
  - 战果
  - 任务成果
  - 命中
  - 摧毁
- id: combat-loss
  name: 查询任务代价
  description: 统计任务期间的人员装备损失。
  datasetKeywords:
  - 战损
  - 损失
  - 伤亡
  - 损毁
outputInstruction: 按完成质量、耗时、成果和代价复盘，归纳失败模式并给出可执行改进项。
---

# 任务完成质量复盘

从任务执行记录出发，对照战果与战损复盘任务完成质量。

## 基本信息

- Skill ID：`mission-success-review`
- 分类：任务评估

## 触发词

- 任务复盘
- 任务完成率
- 行动复盘
- 执行质量

## 推荐问题

- 复盘近期任务完成质量，找出未完成任务的共性原因

## 执行步骤

### 1. 查询任务执行

统计任务状态、完成时长与未完成原因。

- 步骤 ID：`mission`
- 数据集关键词：`任务`、`mission`、`行动`、`执行记录`、`任务完成`
- 操作：`dataset_query`

### 2. 查询任务战果

核验任务对应的命中、摧毁和目标达成。

- 步骤 ID：`combat-result`
- 数据集关键词：`战果`、`任务成果`、`命中`、`摧毁`
- 操作：`dataset_query`

### 3. 查询任务代价

统计任务期间的人员装备损失。

- 步骤 ID：`combat-loss`
- 数据集关键词：`战损`、`损失`、`伤亡`、`损毁`
- 操作：`dataset_query`

## 输出要求

按完成质量、耗时、成果和代价复盘，归纳失败模式并给出可执行改进项。
