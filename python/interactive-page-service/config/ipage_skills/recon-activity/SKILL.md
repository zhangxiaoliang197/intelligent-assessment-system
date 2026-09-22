---
id: recon-activity
name: 侦察活动与目标分布
description: 侦察行动的频次、方式、时段特征与侦察目标的空间分布。当用户问及侦察活动、
  侦察力量运用、目标发现情况、侦察区域覆盖或需要按时间看侦察强度变化时使用。
category: 态势分析
order: 40
triggers:
  - 分析侦察活动与目标发现情况
  - 侦察力量运用与侦察区域分布
  - 按时间看侦察强度变化趋势
  - 侦察目标分布与活动频次
requiredEntityKinds: [air]
recommendedChartTypes: [bar, line]
mapModes: [points, tracks]
playback: false
requiredSections: [kpi, chart, map, text]
focusMetrics: [侦察次数, 侦察目标数, 活动时段, 覆盖区域]
interactions: [侦察方式筛选, 时间段筛选, 目标详情查看]
---

## 取数剧本
- need: entityKind=air, mode=aggregate, question=按侦察机型与阵营统计侦察活动次数
- need: mode=aggregate, question=按日期与时段统计侦察活动频次，用于趋势展示
- need: mode=detail, geo=points, question=侦察目标与侦察活动的位置、时间与所属阵营

## 区块剧本
kpi(侦察活动概览) → chart(侦察力量构成) → chart(侦察频次趋势) → map(目标与活动分布) → text(结论)
- 有逐点航迹数据时地图可声明 tracks 并开启动态演示；只有点位时用 points
- 频率趋势用折线图；构成对比用条形图

## 呈现偏好
- 时间趋势图的横轴按时间升序排列，缺失时段不要跳过（保持时间间隔真实）
- 地图点位按阵营与目标类型区分，并与图表用筛选按钮联动
- 密集区域的点位需要聚合或抽稀，避免相互遮挡
- 结论区放页面底部，图表下方给一句话结论

## 叙事要点
- 先给侦察活动总量与力量构成，再给时段/日期上的强度变化，最后落到目标分布的空间特征
- 必须回答的问题：侦察重心在哪些方向、活动强度在时间上是否集中、覆盖了哪些目标类别
- 数据只覆盖部分时段时明示覆盖范围，不得把缺失时段当成「无活动」
