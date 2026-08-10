---
id: force-readiness-assessment
order: 10
name: 部队战备水平评估
description: 依次核验人员兵力、装备完好和维修保障，判断战备水平。
category: 保障评估
triggers:
- 战备水平
- 战备状态
- 可用兵力
- 装备完好率
recommendedQuestions:
- 评估各单位当前战备水平并给出排序
steps:
- id: force
  name: 查询人员兵力
  description: 统计编制、在位和可出动人员。
  datasetKeywords:
  - 兵力
  - force
  - 人员
  - unit
  - 编制
- id: equipment
  name: 查询装备完好
  description: 统计装备在位、可用与故障数量。
  datasetKeywords:
  - 装备
  - equipment
  - 完好
  - 可用装备
  - 器材
- id: maintenance
  name: 查询维修保障
  description: 统计待修、在修和预计恢复情况。
  datasetKeywords:
  - 维修
  - maintenance
  - 检修
  - 故障
  - 备件
outputInstruction: 按人员到位、装备完好和恢复能力给出战备等级、单位排序与优先整备建议。
---

# 部队战备水平评估

依次核验人员兵力、装备完好和维修保障，判断战备水平。

## 基本信息

- Skill ID：`force-readiness-assessment`
- 分类：保障评估

## 触发词

- 战备水平
- 战备状态
- 可用兵力
- 装备完好率

## 推荐问题

- 评估各单位当前战备水平并给出排序

## 执行步骤

### 1. 查询人员兵力

统计编制、在位和可出动人员。

- 步骤 ID：`force`
- 数据集关键词：`兵力`、`force`、`人员`、`unit`、`编制`
- 操作：`dataset_query`

### 2. 查询装备完好

统计装备在位、可用与故障数量。

- 步骤 ID：`equipment`
- 数据集关键词：`装备`、`equipment`、`完好`、`可用装备`、`器材`
- 操作：`dataset_query`

### 3. 查询维修保障

统计待修、在修和预计恢复情况。

- 步骤 ID：`maintenance`
- 数据集关键词：`维修`、`maintenance`、`检修`、`故障`、`备件`
- 操作：`dataset_query`

## 输出要求

按人员到位、装备完好和恢复能力给出战备等级、单位排序与优先整备建议。
