---
id: recon-warning-capability
order: 8
name: 侦察预警能力评估
description: 按侦察发现、预警处置、能力验证的顺序评估感知链路。
category: 空中作战
triggers:
- 侦察预警
- 探测能力
- 预警时间
- 感知能力
recommendedQuestions:
- 评估当前侦察预警链路的发现与响应能力
steps:
- id: recon
  name: 查询侦察发现
  description: 统计侦察覆盖、发现数量和识别准确率。
  datasetKeywords:
  - 侦察
  - recon
  - 情报
  - intelligence
  - 探测
- id: warning
  name: 查询预警处置
  description: 统计预警提前量、告警等级和处置状态。
  datasetKeywords:
  - 预警
  - warning
  - 告警
  - 雷达
  - 响应时间
- id: air-capability
  name: 核验感知能力
  description: 使用空中能力数据验证侦察预警分项表现。
  datasetKeywords:
  - 空中能力
  - 侦察能力
  - 探测精度
  - 感知
outputInstruction: 从覆盖范围、发现概率、识别准确率和预警提前量评估能力，指出链路薄弱点。
---

# 侦察预警能力评估

按侦察发现、预警处置、能力验证的顺序评估感知链路。

## 基本信息

- Skill ID：`recon-warning-capability`
- 分类：空中作战

## 触发词

- 侦察预警
- 探测能力
- 预警时间
- 感知能力

## 推荐问题

- 评估当前侦察预警链路的发现与响应能力

## 执行步骤

### 1. 查询侦察发现

统计侦察覆盖、发现数量和识别准确率。

- 步骤 ID：`recon`
- 数据集关键词：`侦察`、`recon`、`情报`、`intelligence`、`探测`
- 操作：`dataset_query`

### 2. 查询预警处置

统计预警提前量、告警等级和处置状态。

- 步骤 ID：`warning`
- 数据集关键词：`预警`、`warning`、`告警`、`雷达`、`响应时间`
- 操作：`dataset_query`

### 3. 核验感知能力

使用空中能力数据验证侦察预警分项表现。

- 步骤 ID：`air-capability`
- 数据集关键词：`空中能力`、`侦察能力`、`探测精度`、`感知`
- 操作：`dataset_query`

## 输出要求

从覆盖范围、发现概率、识别准确率和预警提前量评估能力，指出链路薄弱点。
