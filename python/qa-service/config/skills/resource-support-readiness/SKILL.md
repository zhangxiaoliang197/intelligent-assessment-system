---
id: resource-support-readiness
order: 5
name: 资源保障能力评估
description: 按照库存、消耗、补给的顺序评估持续保障能力。
category: 保障评估
triggers:
- 资源保障
- 物资保障
- 弹药够不够
- 持续作战
recommendedQuestions:
- 评估当前资源保障是否能够支撑下一阶段行动
steps:
- id: inventory
  name: 查询现有库存
  description: 核验弹药、燃料、备件与关键物资库存。
  datasetKeywords:
  - 库存
  - inventory
  - 仓储
  - 物资余量
  - 储备
- id: resource-consume
  name: 查询消耗速率
  description: 统计各类资源消耗量和消耗趋势。
  datasetKeywords:
  - 消耗
  - 弹药
  - 燃料
  - 物资
- id: supply
  name: 查询补给能力
  description: 核验补给计划、到货进度和运输能力。
  datasetKeywords:
  - 补给
  - supply
  - 运输
  - 配送
  - 保障计划
outputInstruction: 计算或判断可持续保障时长，列出最紧缺资源、风险时间点和优先补给建议。
---

# 资源保障能力评估

按照库存、消耗、补给的顺序评估持续保障能力。

## 基本信息

- Skill ID：`resource-support-readiness`
- 分类：保障评估

## 触发词

- 资源保障
- 物资保障
- 弹药够不够
- 持续作战

## 推荐问题

- 评估当前资源保障是否能够支撑下一阶段行动

## 执行步骤

### 1. 查询现有库存

核验弹药、燃料、备件与关键物资库存。

- 步骤 ID：`inventory`
- 数据集关键词：`库存`、`inventory`、`仓储`、`物资余量`、`储备`
- 操作：`dataset_query`

### 2. 查询消耗速率

统计各类资源消耗量和消耗趋势。

- 步骤 ID：`resource-consume`
- 数据集关键词：`消耗`、`弹药`、`燃料`、`物资`
- 操作：`dataset_query`

### 3. 查询补给能力

核验补给计划、到货进度和运输能力。

- 步骤 ID：`supply`
- 数据集关键词：`补给`、`supply`、`运输`、`配送`、`保障计划`
- 操作：`dataset_query`

## 输出要求

计算或判断可持续保障时长，列出最紧缺资源、风险时间点和优先补给建议。
