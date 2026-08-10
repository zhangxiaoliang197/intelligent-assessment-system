---
id: command-decision-efficiency
order: 9
name: 指挥决策效率评估
description: 连接指令、任务执行与战果数据，评估决策到行动的效率。
category: 任务评估
triggers:
- 指挥效率
- 决策效率
- 指令响应
- 命令执行
recommendedQuestions:
- 评估指挥决策到任务执行的响应效率
steps:
- id: command
  name: 查询指挥指令
  description: 统计命令下达时间、层级和变更情况。
  datasetKeywords:
  - 指挥
  - command
  - 指令
  - order
  - 决策
- id: mission
  name: 查询任务响应
  description: 统计任务接收、启动、完成时间及状态。
  datasetKeywords:
  - 任务
  - mission
  - 行动
  - 执行
  - 响应
- id: combat-result
  name: 核验决策效果
  description: 用对应战果检验决策执行效果。
  datasetKeywords:
  - 战果
  - 任务成果
  - 命中
  - 摧毁
outputInstruction: 分析决策延迟、执行延迟、变更频率和结果质量，识别主要流程瓶颈。
---

# 指挥决策效率评估

连接指令、任务执行与战果数据，评估决策到行动的效率。

## 基本信息

- Skill ID：`command-decision-efficiency`
- 分类：任务评估

## 触发词

- 指挥效率
- 决策效率
- 指令响应
- 命令执行

## 推荐问题

- 评估指挥决策到任务执行的响应效率

## 执行步骤

### 1. 查询指挥指令

统计命令下达时间、层级和变更情况。

- 步骤 ID：`command`
- 数据集关键词：`指挥`、`command`、`指令`、`order`、`决策`
- 操作：`dataset_query`

### 2. 查询任务响应

统计任务接收、启动、完成时间及状态。

- 步骤 ID：`mission`
- 数据集关键词：`任务`、`mission`、`行动`、`执行`、`响应`
- 操作：`dataset_query`

### 3. 核验决策效果

用对应战果检验决策执行效果。

- 步骤 ID：`combat-result`
- 数据集关键词：`战果`、`任务成果`、`命中`、`摧毁`
- 操作：`dataset_query`

## 输出要求

分析决策延迟、执行延迟、变更频率和结果质量，识别主要流程瓶颈。
