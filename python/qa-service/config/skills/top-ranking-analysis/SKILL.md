---
id: top-ranking-analysis
order: 27
name: Top N 排名分析
description: 按用户指定指标生成对象排名、Top N 清单和头部集中度。
category: 统计分析
triggers:
- top n
- 排行榜
- 排名分析
- 最高的
- 前十名
recommendedQuestions:
- 按指定指标查询排名前十的对象
- 生成数量最多的 Top 10 排名
steps:
- id: ranking
  name: 生成指标排名
  description: 按用户指定指标降序排序并返回限定数量的对象及指标值。
  datasetKeywords:
  - 排名
  - 指标
  - 对象
  - 数量
  - 绩效
visualization:
  enabled: true
  preferredType: bar
outputInstruction: 输出排名、对象、指标值、Top N 合计及头部集中度，并生成易读的柱状图。
---

# Top N 排名分析

按用户指定指标生成对象排名、Top N 清单和头部集中度。

## 基本信息

- Skill ID：`top-ranking-analysis`
- 分类：统计分析

## 触发词

- top n
- 排行榜
- 排名分析
- 最高的
- 前十名

## 推荐问题

- 按指定指标查询排名前十的对象
- 生成数量最多的 Top 10 排名

## 执行步骤

### 1. 生成指标排名

按用户指定指标降序排序并返回限定数量的对象及指标值。

- 步骤 ID：`ranking`
- 数据集关键词：`排名`、`指标`、`对象`、`数量`、`绩效`
- 操作：`dataset_query`

## 可视化

- 启用：是
- 首选类型：`bar`

## 输出要求

输出排名、对象、指标值、Top N 合计及头部集中度，并生成易读的柱状图。
