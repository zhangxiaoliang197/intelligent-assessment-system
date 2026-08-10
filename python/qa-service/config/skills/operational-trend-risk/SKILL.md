---
id: operational-trend-risk
order: 15
name: 作战态势趋势与风险研判
description: 串联历史任务、战果、战损和资源数据，研判态势趋势与近期风险。
category: 综合评估
triggers:
- 态势趋势
- 风险预测
- 趋势分析
- 后续风险
recommendedQuestions:
- 基于近期数据研判作战态势趋势和下一阶段主要风险
steps:
- id: mission-history
  name: 查询任务趋势
  description: 统计任务数量、类型、完成率和周期变化。
  datasetKeywords:
  - 任务
  - mission
  - 历史任务
  - 行动
  - 执行记录
- id: combat-result
  name: 查询战果趋势
  description: 统计命中、摧毁和目标达成的时间变化。
  datasetKeywords:
  - 战果
  - 命中
  - 摧毁
  - 打击效果
- id: combat-loss
  name: 查询战损趋势
  description: 统计损失数量、对象和原因的时间变化。
  datasetKeywords:
  - 战损
  - 损失
  - 伤亡
  - 损毁
- id: resource-consume
  name: 查询资源趋势
  description: 统计关键资源消耗与剩余保障压力。
  datasetKeywords:
  - 消耗
  - 弹药
  - 燃料
  - 物资
outputInstruction: 区分已发生事实与趋势推断，给出上升或下降信号、主要风险、证据和建议观察指标。
---

# 作战态势趋势与风险研判

串联历史任务、战果、战损和资源数据，研判态势趋势与近期风险。

## 基本信息

- Skill ID：`operational-trend-risk`
- 分类：综合评估

## 触发词

- 态势趋势
- 风险预测
- 趋势分析
- 后续风险

## 推荐问题

- 基于近期数据研判作战态势趋势和下一阶段主要风险

## 执行步骤

### 1. 查询任务趋势

统计任务数量、类型、完成率和周期变化。

- 步骤 ID：`mission-history`
- 数据集关键词：`任务`、`mission`、`历史任务`、`行动`、`执行记录`
- 操作：`dataset_query`

### 2. 查询战果趋势

统计命中、摧毁和目标达成的时间变化。

- 步骤 ID：`combat-result`
- 数据集关键词：`战果`、`命中`、`摧毁`、`打击效果`
- 操作：`dataset_query`

### 3. 查询战损趋势

统计损失数量、对象和原因的时间变化。

- 步骤 ID：`combat-loss`
- 数据集关键词：`战损`、`损失`、`伤亡`、`损毁`
- 操作：`dataset_query`

### 4. 查询资源趋势

统计关键资源消耗与剩余保障压力。

- 步骤 ID：`resource-consume`
- 数据集关键词：`消耗`、`弹药`、`燃料`、`物资`
- 操作：`dataset_query`

## 输出要求

区分已发生事实与趋势推断，给出上升或下降信号、主要风险、证据和建议观察指标。
