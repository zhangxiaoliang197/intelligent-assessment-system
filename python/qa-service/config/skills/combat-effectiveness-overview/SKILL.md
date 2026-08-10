---
id: combat-effectiveness-overview
order: 1
name: 作战效能综合评估
description: 依次核验战果、战损与资源消耗，形成整体作战效能结论。
category: 综合评估
triggers:
- 整体作战效能
- 综合评估
- 作战效果
- 效能怎么样
recommendedQuestions:
- 综合评估本次作战行动的整体效能，并指出主要短板
steps:
- id: combat-result
  name: 核验战果
  description: 统计命中、摧毁和任务成果，识别主要贡献单位。
  datasetKeywords:
  - 战果
  - 打击效果
  - 命中
  - 摧毁
- id: combat-loss
  name: 核验战损
  description: 统计装备与人员损失，分析损失原因和时间分布。
  datasetKeywords:
  - 战损
  - 损失
  - 伤亡
  - 损毁
- id: resource-consume
  name: 核验资源消耗
  description: 统计弹药、燃料与物资消耗，评估投入产出。
  datasetKeywords:
  - 消耗
  - 弹药
  - 燃料
  - 物资
outputInstruction: 从目标达成、损失代价、资源效率三个维度给出结论，并明确优势、短板和改进建议。
---

# 作战效能综合评估

依次核验战果、战损与资源消耗，形成整体作战效能结论。

## 基本信息

- Skill ID：`combat-effectiveness-overview`
- 分类：综合评估

## 触发词

- 整体作战效能
- 综合评估
- 作战效果
- 效能怎么样

## 推荐问题

- 综合评估本次作战行动的整体效能，并指出主要短板

## 执行步骤

### 1. 核验战果

统计命中、摧毁和任务成果，识别主要贡献单位。

- 步骤 ID：`combat-result`
- 数据集关键词：`战果`、`打击效果`、`命中`、`摧毁`
- 操作：`dataset_query`

### 2. 核验战损

统计装备与人员损失，分析损失原因和时间分布。

- 步骤 ID：`combat-loss`
- 数据集关键词：`战损`、`损失`、`伤亡`、`损毁`
- 操作：`dataset_query`

### 3. 核验资源消耗

统计弹药、燃料与物资消耗，评估投入产出。

- 步骤 ID：`resource-consume`
- 数据集关键词：`消耗`、`弹药`、`燃料`、`物资`
- 操作：`dataset_query`

## 输出要求

从目标达成、损失代价、资源效率三个维度给出结论，并明确优势、短板和改进建议。
