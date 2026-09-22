---
id: target-priority
name: 目标优先级排序
description: 打击目标的重要度、防御强度、状态与空间分布，形成可追溯的优先级清单。当用户问及
  目标优先级、重点目标、目标排序、先处置哪些目标、目标清单时使用。
category: 态势分析
order: 80
triggers:
  - 按重要度与防御强度排列目标优先级
  - 筛选当前最需关注的重点目标
  - 打击目标清单与状态分布
  - 目标的防御强度与位置分布
requiredEntityKinds: [ground_facility]
recommendedChartTypes: [bar, scatter]
mapModes: [points]
playback: false
requiredSections: [kpi, chart, map, table, text]
focusMetrics: [目标总数, 高重要度目标数, 已毁伤目标数, 平均防御等级]
interactions: [重要度筛选, 目标类型筛选, 目标详情查看]
---

## 取数剧本
- need: entityKind=ground_facility, mode=aggregate, question=按目标类别与状态统计目标数量、重要度与防御等级分布
- need: entityKind=ground_facility, mode=detail, geo=points, question=目标的位置、类别、重要度、防御等级与状态的逐行明细
- need: mode=aggregate, question=按目标统计被打击次数与最近打击时间

## 区块剧本
kpi(目标概览) → chart(目标类别与重要度分布) → chart(重要度与防御强度关系) → map(目标点位与状态) → table(优先级清单) → text(结论)
- 优先级清单用表格按重要度与防御等级排序列出，包含状态与最近打击时间
- 目标点位地图与表格共用同一份明细数据，不要重复规划取值口径不同的子问题

## 呈现偏好
- 排序结果用条形图；重要度与防御强度两个数值维度的关系用散点图，不要用饼图表达排序
- 目标点位按类别与状态符号化并自动生成图例；点位密集区域需要聚合并标注数量
- 表格分页展示，排序列必须与结论中给出的排序口径一致
- 每个图表给出中文标题与一句话结论；结论区放页面底部

## 叙事要点
- 先给目标总量与类别构成，再给重要度与防御强度的分布关系，最后落到优先级清单与空间分布
- 必须回答的问题：高重要度目标集中在哪些类别、防御强度与重要度是否匹配、已毁伤目标占比如何
- 排序必须说明所用字段与口径；样本不足时明示「数据不足以支撑排序」，不得给出无依据的次序
- 只呈现排序依据与数据事实，不输出行动指令类表述
