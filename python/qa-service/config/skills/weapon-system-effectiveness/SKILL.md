---
id: weapon-system-effectiveness
order: 7
name: 武器系统效能评估
description: 先查武器系统基础信息，再用战果和故障损失数据验证实际效能。
category: 火力打击
triggers:
- 武器效能
- 装备效能
- 武器系统
- 哪种武器
recommendedQuestions:
- 对比各型武器系统的实际作战效能和可靠性
steps:
- id: weapon
  name: 查询武器系统
  description: 获取型号、数量、能力参数和使用记录。
  datasetKeywords:
  - 武器
  - weapon
  - 装备
  - equipment
  - 火力系统
- id: combat-result
  name: 查询贡献战果
  description: 按武器型号统计命中、摧毁与任务贡献。
  datasetKeywords:
  - 战果
  - 命中
  - 摧毁
  - 打击效果
- id: maintenance-loss
  name: 查询故障与损失
  description: 统计故障、维修和战损情况。
  datasetKeywords:
  - 维修
  - maintenance
  - 故障
  - 战损
outputInstruction: 比较各型号的任务贡献、命中摧毁效果和可靠性，给出使用与保障优先级。
---

# 武器系统效能评估

先查武器系统基础信息，再用战果和故障损失数据验证实际效能。

## 基本信息

- Skill ID：`weapon-system-effectiveness`
- 分类：火力打击

## 触发词

- 武器效能
- 装备效能
- 武器系统
- 哪种武器

## 推荐问题

- 对比各型武器系统的实际作战效能和可靠性

## 执行步骤

### 1. 查询武器系统

获取型号、数量、能力参数和使用记录。

- 步骤 ID：`weapon`
- 数据集关键词：`武器`、`weapon`、`装备`、`equipment`、`火力系统`
- 操作：`dataset_query`

### 2. 查询贡献战果

按武器型号统计命中、摧毁与任务贡献。

- 步骤 ID：`combat-result`
- 数据集关键词：`战果`、`命中`、`摧毁`、`打击效果`
- 操作：`dataset_query`

### 3. 查询故障与损失

统计故障、维修和战损情况。

- 步骤 ID：`maintenance-loss`
- 数据集关键词：`维修`、`maintenance`、`故障`、`战损`
- 操作：`dataset_query`

## 输出要求

比较各型号的任务贡献、命中摧毁效果和可靠性，给出使用与保障优先级。
