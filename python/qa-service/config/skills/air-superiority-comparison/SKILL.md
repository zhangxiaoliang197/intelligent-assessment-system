---
id: air-superiority-comparison
order: 2
name: 制空权对比分析
description: 先分析分项空中能力，再核验总体制空评分，输出红蓝双方对比。
category: 空中作战
triggers:
- 制空权
- 制空能力
- 空中优势
- 红蓝空战
recommendedQuestions:
- 对比目标区域红蓝双方制空权，说明决定优势的关键因素
steps:
- id: air-capability
  name: 查询分项空中能力
  description: 对比占位、打击、侦察等分项能力。
  datasetKeywords:
  - 空中能力
  - 制空分项
  - 占位
  - 侦察能力
- id: air-overall
  name: 查询总体制空能力
  description: 核验总体评分和各分项权重表现。
  datasetKeywords:
  - 总体制空
  - 制空权
  - 空中优势
  - 总体能力
outputInstruction: 按双方分项差距、总体差距和关键制约因素输出制空权判断，并说明结论适用的区域与时间范围。
---

# 制空权对比分析

先分析分项空中能力，再核验总体制空评分，输出红蓝双方对比。

## 基本信息

- Skill ID：`air-superiority-comparison`
- 分类：空中作战

## 触发词

- 制空权
- 制空能力
- 空中优势
- 红蓝空战

## 推荐问题

- 对比目标区域红蓝双方制空权，说明决定优势的关键因素

## 执行步骤

### 1. 查询分项空中能力

对比占位、打击、侦察等分项能力。

- 步骤 ID：`air-capability`
- 数据集关键词：`空中能力`、`制空分项`、`占位`、`侦察能力`
- 操作：`dataset_query`

### 2. 查询总体制空能力

核验总体评分和各分项权重表现。

- 步骤 ID：`air-overall`
- 数据集关键词：`总体制空`、`制空权`、`空中优势`、`总体能力`
- 操作：`dataset_query`

## 输出要求

按双方分项差距、总体差距和关键制约因素输出制空权判断，并说明结论适用的区域与时间范围。
