---
id: target-priority-analysis
order: 13
name: 目标价值与打击优先级分析
description: 依次核验目标价值、情报可信度和可用打击手段，生成优先级建议。
category: 火力打击
triggers:
- 目标优先级
- 打击顺序
- 目标价值
- 先打哪个
recommendedQuestions:
- 综合目标价值和可打击性，给出目标优先级建议
steps:
- id: target
  name: 查询目标价值
  description: 获取目标类型、价值等级、位置和状态。
  datasetKeywords:
  - 目标
  - target
  - 威胁
  - threat
  - 目标价值
- id: intelligence
  name: 核验目标情报
  description: 核验目标发现时间、来源和可信度。
  datasetKeywords:
  - 情报
  - intelligence
  - 侦察
  - recon
  - 探测
- id: weapon
  name: 查询打击手段
  description: 匹配射程、数量和适用目标类型。
  datasetKeywords:
  - 武器
  - weapon
  - 火力
  - 装备
  - 弹药
outputInstruction: 综合价值、紧迫性、情报可信度和可打击性输出优先级，并说明排序依据与约束。
---

# 目标价值与打击优先级分析

依次核验目标价值、情报可信度和可用打击手段，生成优先级建议。

## 基本信息

- Skill ID：`target-priority-analysis`
- 分类：火力打击

## 触发词

- 目标优先级
- 打击顺序
- 目标价值
- 先打哪个

## 推荐问题

- 综合目标价值和可打击性，给出目标优先级建议

## 执行步骤

### 1. 查询目标价值

获取目标类型、价值等级、位置和状态。

- 步骤 ID：`target`
- 数据集关键词：`目标`、`target`、`威胁`、`threat`、`目标价值`
- 操作：`dataset_query`

### 2. 核验目标情报

核验目标发现时间、来源和可信度。

- 步骤 ID：`intelligence`
- 数据集关键词：`情报`、`intelligence`、`侦察`、`recon`、`探测`
- 操作：`dataset_query`

### 3. 查询打击手段

匹配射程、数量和适用目标类型。

- 步骤 ID：`weapon`
- 数据集关键词：`武器`、`weapon`、`火力`、`装备`、`弹药`
- 操作：`dataset_query`

## 输出要求

综合价值、紧迫性、情报可信度和可打击性输出优先级，并说明排序依据与约束。
