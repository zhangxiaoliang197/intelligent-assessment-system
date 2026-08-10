---
id: chart-visualization-query
order: 30
name: 图表生成与可视化
description: 根据用户指定的分类、时间和指标生成聚合查询结果，并自动选择柱状图、折线图或饼图。
category: 数据可视化
triggers:
- 生成图表
- 画图
- 可视化
- 柱状图
- 折线图
- 饼图
recommendedQuestions:
- 把主要分类及数量生成图表
- 按时间统计指标并生成趋势图
steps:
- id: chart-data
  name: 准备图表数据
  description: 查询一个分类或时间维度及至少一个数值指标，返回适合图表展示的聚合结果。
  datasetKeywords:
  - 数据
  - 统计
  - 指标
  - 分类
  - 时间
visualization:
  enabled: true
  preferredType: auto
outputInstruction: 输出图表、聚合数据和统计口径；时间维度优先折线图，少量分类占比优先饼图，其余使用柱状图。
---

# 图表生成与可视化

根据用户指定的分类、时间和指标生成聚合查询结果，并自动选择柱状图、折线图或饼图。

## 基本信息

- Skill ID：`chart-visualization-query`
- 分类：数据可视化

## 触发词

- 生成图表
- 画图
- 可视化
- 柱状图
- 折线图
- 饼图

## 推荐问题

- 把主要分类及数量生成图表
- 按时间统计指标并生成趋势图

## 执行步骤

### 1. 准备图表数据

查询一个分类或时间维度及至少一个数值指标，返回适合图表展示的聚合结果。

- 步骤 ID：`chart-data`
- 数据集关键词：`数据`、`统计`、`指标`、`分类`、`时间`
- 操作：`dataset_query`

## 可视化

- 启用：是
- 首选类型：`auto`

## 输出要求

输出图表、聚合数据和统计口径；时间维度优先折线图，少量分类占比优先饼图，其余使用柱状图。
