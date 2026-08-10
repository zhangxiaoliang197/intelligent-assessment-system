---
id: defense-survivability-assessment
order: 12
name: 防御生存能力评估
description: 从防护配置、实际战损与保障恢复三个层面评估生存能力。
category: 损伤评估
triggers:
- 生存能力
- 防御能力
- 防护效果
- 抗毁能力
recommendedQuestions:
- 评估当前防御体系的生存与恢复能力
steps:
- id: defense
  name: 查询防护配置
  description: 核验防御单元、覆盖范围和防护等级。
  datasetKeywords:
  - 防御
  - defense
  - 防护
  - 工事
  - 拦截
- id: combat-loss
  name: 查询实际战损
  description: 统计受损对象、损失原因与区域分布。
  datasetKeywords:
  - 战损
  - 损失
  - 损毁
  - 伤亡
- id: support
  name: 查询恢复保障
  description: 统计维修、补给和替补恢复能力。
  datasetKeywords:
  - 维修
  - maintenance
  - 补给
  - supply
  - 保障
outputInstruction: 评估防护有效性、易损环节和战损恢复速度，提出加固与冗余配置建议。
---

# 防御生存能力评估

从防护配置、实际战损与保障恢复三个层面评估生存能力。

## 基本信息

- Skill ID：`defense-survivability-assessment`
- 分类：损伤评估

## 触发词

- 生存能力
- 防御能力
- 防护效果
- 抗毁能力

## 推荐问题

- 评估当前防御体系的生存与恢复能力

## 执行步骤

### 1. 查询防护配置

核验防御单元、覆盖范围和防护等级。

- 步骤 ID：`defense`
- 数据集关键词：`防御`、`defense`、`防护`、`工事`、`拦截`
- 操作：`dataset_query`

### 2. 查询实际战损

统计受损对象、损失原因与区域分布。

- 步骤 ID：`combat-loss`
- 数据集关键词：`战损`、`损失`、`损毁`、`伤亡`
- 操作：`dataset_query`

### 3. 查询恢复保障

统计维修、补给和替补恢复能力。

- 步骤 ID：`support`
- 数据集关键词：`维修`、`maintenance`、`补给`、`supply`、`保障`
- 操作：`dataset_query`

## 输出要求

评估防护有效性、易损环节和战损恢复速度，提出加固与冗余配置建议。
