---
id: battle-damage-assessment
order: 4
name: 战损影响评估
description: 先建立参战力量基线，再分析战损，最后结合战果判断损失影响。
category: 损伤评估
triggers:
- 战损影响
- 损失评估
- 伤亡分析
- 损毁情况
recommendedQuestions:
- 分析当前战损对后续作战能力的影响
steps:
- id: force-baseline
  name: 查询兵力基线
  description: 获取单位、人员和装备初始规模。
  datasetKeywords:
  - 兵力
  - force
  - unit
  - 编制
  - 参战力量
- id: combat-loss
  name: 查询战损明细
  description: 按单位、装备、原因和时间统计损失。
  datasetKeywords:
  - 战损
  - 损失
  - 伤亡
  - 损毁
- id: combat-result
  name: 查询同期战果
  description: 结合取得的战果判断损失代价是否可接受。
  datasetKeywords:
  - 战果
  - 命中
  - 摧毁
  - 任务成果
outputInstruction: 量化损失比例和受影响能力，判断是否影响后续任务，并提出补充与调整建议。
---

# 战损影响评估

先建立参战力量基线，再分析战损，最后结合战果判断损失影响。

## 基本信息

- Skill ID：`battle-damage-assessment`
- 分类：损伤评估

## 触发词

- 战损影响
- 损失评估
- 伤亡分析
- 损毁情况

## 推荐问题

- 分析当前战损对后续作战能力的影响

## 执行步骤

### 1. 查询兵力基线

获取单位、人员和装备初始规模。

- 步骤 ID：`force-baseline`
- 数据集关键词：`兵力`、`force`、`unit`、`编制`、`参战力量`
- 操作：`dataset_query`

### 2. 查询战损明细

按单位、装备、原因和时间统计损失。

- 步骤 ID：`combat-loss`
- 数据集关键词：`战损`、`损失`、`伤亡`、`损毁`
- 操作：`dataset_query`

### 3. 查询同期战果

结合取得的战果判断损失代价是否可接受。

- 步骤 ID：`combat-result`
- 数据集关键词：`战果`、`命中`、`摧毁`、`任务成果`
- 操作：`dataset_query`

## 输出要求

量化损失比例和受影响能力，判断是否影响后续任务，并提出补充与调整建议。
