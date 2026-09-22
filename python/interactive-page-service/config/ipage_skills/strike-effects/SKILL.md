---
id: strike-effects
name: 打击效果与战损评估
description: 打击行动的目标分布、命中结果与双方战损评估。当用户问及打击效果、命中率、战损统计、
  毁伤程度或需要按目标类型对比打击结果时使用。
category: 效果评估
order: 30
triggers:
  - 分析打击效果与战损情况
  - 统计命中目标数量与毁伤程度
  - 双方战损对比评估
  - 打击目标分布与命中结果
requiredEntityKinds: [ground_facility]
recommendedChartTypes: [bar, pie]
mapModes: [points]
playback: false
requiredSections: [kpi, chart, map, text]
focusMetrics: [打击次数, 命中数量, 摧毁数量, 战损数量]
interactions: [目标类型筛选, 毁伤程度筛选, 事件详情查看]
---

## 取数剧本
- need: entityKind=ground_facility, mode=aggregate, question=按目标类型统计被打击次数与摧毁、受损数量
- need: mode=aggregate, question=按毁伤程度与阵营统计打击结果分布
- need: mode=detail, geo=points, question=打击与战损事件的位置、发生时间与结果

## 区块剧本
kpi(打击与战损概览) → chart(目标类型打击分布) → chart(毁伤程度构成) → map(打击与战损事件点位) → text(结论)
- 事件点位地图按事件类型符号化并自动生成图例，不需额外说明符号形状
- 有战损明细数据时可追加 table 区块

## 呈现偏好
- 占比类图表（毁伤程度构成）分类数较少时用饼图，否则改用条形图
- 事件地图的点位密集区域需要聚合并标注数量，避免相互遮挡
- 图表给出中文标题与一句话结论；结论区放页面底部
- 不得在图表或结论中写死任何数量，全部由运行时数据计算

## 叙事要点
- 先给打击总量与命中结果，再给目标类型的结构性差异，最后落到毁伤程度与战损对比
- 必须回答的问题：打击是否命中预期目标、毁伤程度构成如何、双方战损差距在哪
- 「未命中」「无战损」也是结论的一部分，必须如实呈现，不得只展示成功项
