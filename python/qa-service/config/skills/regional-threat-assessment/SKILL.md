---
id: regional-threat-assessment
order: 11
name: 区域威胁综合研判
description: 先识别威胁目标，再结合情报和兵力部署形成区域风险判断。
category: 威胁研判
triggers:
- 区域威胁
- 威胁研判
- 风险区域
- 敌情分析
recommendedQuestions:
- 研判目标区域当前主要威胁及风险等级
steps:
- id: threat
  name: 查询威胁目标
  description: 统计目标类型、威胁等级、位置和活动状态。
  datasetKeywords:
  - 威胁
  - threat
  - 目标
  - target
  - 敌情
- id: intelligence
  name: 查询情报证据
  description: 核验侦察来源、可信度和最新发现。
  datasetKeywords:
  - 情报
  - intelligence
  - 侦察
  - recon
  - 探测
- id: deployment
  name: 查询兵力部署
  description: 分析双方单位和装备在区域内的分布。
  datasetKeywords:
  - 部署
  - deployment
  - 兵力
  - force
  - unit
outputInstruction: 给出威胁等级、关键目标、证据充分度和可能影响，并区分事实与推断。
---

# 区域威胁综合研判

先识别威胁目标，再结合情报和兵力部署形成区域风险判断。

## 基本信息

- Skill ID：`regional-threat-assessment`
- 分类：威胁研判

## 触发词

- 区域威胁
- 威胁研判
- 风险区域
- 敌情分析

## 推荐问题

- 研判目标区域当前主要威胁及风险等级

## 执行步骤

### 1. 查询威胁目标

统计目标类型、威胁等级、位置和活动状态。

- 步骤 ID：`threat`
- 数据集关键词：`威胁`、`threat`、`目标`、`target`、`敌情`
- 操作：`dataset_query`

### 2. 查询情报证据

核验侦察来源、可信度和最新发现。

- 步骤 ID：`intelligence`
- 数据集关键词：`情报`、`intelligence`、`侦察`、`recon`、`探测`
- 操作：`dataset_query`

### 3. 查询兵力部署

分析双方单位和装备在区域内的分布。

- 步骤 ID：`deployment`
- 数据集关键词：`部署`、`deployment`、`兵力`、`force`、`unit`
- 操作：`dataset_query`

## 输出要求

给出威胁等级、关键目标、证据充分度和可能影响，并区分事实与推断。
