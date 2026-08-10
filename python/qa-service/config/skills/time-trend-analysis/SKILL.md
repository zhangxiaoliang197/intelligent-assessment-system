---
id: time-trend-analysis
order: 25
name: 时间趋势分析
description: 按日、周、月或年汇总目标指标，识别增长、下降、周期性和突变趋势。
category: 趋势分析
triggers:
- 时间趋势
- 趋势变化
- 按月统计
- 按天统计
- 走势图
recommendedQuestions:
- 按月分析指定指标的变化趋势
- 查看最近一段时间的数据走势
steps:
- id: trend
  name: 汇总时间序列
  description: 按用户要求的时间粒度汇总目标指标并按时间升序返回。
  datasetKeywords:
  - 时间
  - 日期
  - 记录
  - 历史
  - 趋势
visualization:
  enabled: true
  preferredType: line
outputInstruction: 输出时间序列、环比变化、主要拐点和可能异常，并生成折线图；没有足够时间跨度时明确说明。
---

# 时间趋势分析

按日、周、月或年汇总目标指标，识别增长、下降、周期性和突变趋势。

## 基本信息

- Skill ID：`time-trend-analysis`
- 分类：趋势分析

## 触发词

- 时间趋势
- 趋势变化
- 按月统计
- 按天统计
- 走势图

## 推荐问题

- 按月分析指定指标的变化趋势
- 查看最近一段时间的数据走势

## 执行步骤

### 1. 汇总时间序列

按用户要求的时间粒度汇总目标指标并按时间升序返回。

- 步骤 ID：`trend`
- 数据集关键词：`时间`、`日期`、`记录`、`历史`、`趋势`
- 操作：`dataset_query`

## 可视化

- 启用：是
- 首选类型：`line`

## 输出要求

输出时间序列、环比变化、主要拐点和可能异常，并生成折线图；没有足够时间跨度时明确说明。
