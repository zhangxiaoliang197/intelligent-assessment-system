---
id: joint-operation-coordination
order: 14
name: 联合作战协同评估
description: 从联合任务、指挥协同和保障协同三个方面评估体系协作效果。
category: 任务评估
triggers:
- 联合作战
- 协同效率
- 军兵种协同
- 体系协同
recommendedQuestions:
- 评估本次联合作战各力量之间的协同效果
steps:
- id: joint-mission
  name: 查询联合任务
  description: 统计参与力量、任务依赖与完成情况。
  datasetKeywords:
  - 联合任务
  - 任务
  - mission
  - 协同任务
- id: command
  name: 查询指挥协同
  description: 分析命令传递、任务变更和响应时延。
  datasetKeywords:
  - 指挥
  - command
  - 指令
  - order
  - 协同
- id: support
  name: 查询保障协同
  description: 分析跨单位资源、补给和支援情况。
  datasetKeywords:
  - 保障
  - support
  - 补给
  - supply
  - 资源
outputInstruction: 按任务衔接、指挥响应和保障共享评价协同水平，列出接口瓶颈与改进措施。
---

# 联合作战协同评估

从联合任务、指挥协同和保障协同三个方面评估体系协作效果。

## 基本信息

- Skill ID：`joint-operation-coordination`
- 分类：任务评估

## 触发词

- 联合作战
- 协同效率
- 军兵种协同
- 体系协同

## 推荐问题

- 评估本次联合作战各力量之间的协同效果

## 执行步骤

### 1. 查询联合任务

统计参与力量、任务依赖与完成情况。

- 步骤 ID：`joint-mission`
- 数据集关键词：`联合任务`、`任务`、`mission`、`协同任务`
- 操作：`dataset_query`

### 2. 查询指挥协同

分析命令传递、任务变更和响应时延。

- 步骤 ID：`command`
- 数据集关键词：`指挥`、`command`、`指令`、`order`、`协同`
- 操作：`dataset_query`

### 3. 查询保障协同

分析跨单位资源、补给和支援情况。

- 步骤 ID：`support`
- 数据集关键词：`保障`、`support`、`补给`、`supply`、`资源`
- 操作：`dataset_query`

## 输出要求

按任务衔接、指挥响应和保障共享评价协同水平，列出接口瓶颈与改进措施。
