---
id: air-power-situation
name: 空军力量态势
description: 红蓝双方空军兵力对比、战损、出动强度与航迹动态演示。当用户问及空军/航空兵/战机力量对比、
  在役与战损数量、出动架次、飞行轨迹，或需要「动态演示」「回放」双方空中活动时使用。
category: 态势分析
order: 10
triggers:
  - 分析红蓝方空军力量态势
  - 对比双方在役与战损飞机数量
  - 我方战机飞行轨迹与动态演示
  - 空军兵力部署与作战能力范围
  - 双方空军出动强度对比
requiredEntityKinds: [air]
recommendedChartTypes: [bar, pie, radar]
mapModes: [tracks, points]
playback: true
requiredSections: [kpi, chart, map, text]
focusMetrics: [在役数量, 战损数量, 出动架次, 覆盖半径]
interactions: [阵营筛选联动, 航迹选择, 时间轴回放]
---

## 取数剧本
- need: entityKind=air, mode=aggregate, question=按机型与阵营统计在役数量与战损数量
- need: entityKind=air, mode=detail, geo=tracks, question=逐架次航迹逐点明细（含实体编号、序号与记录时间）
- need: entityKind=base, mode=detail, geo=points, question=双方基地位置与驻场机型

## 区块剧本
kpi(兵力概览) → chart(机型在役对比) → chart(战损构成) → map(航迹动态演示) → timeline → text(结论)
- 有航迹数据时地图放在对比图表之后、结论之前，并开启回放
- 基地点位可与航迹共用地图区块（地图区块可引用多个子问题数据）

## 呈现偏好
- 战场地图必须开启回放：能力圈随飞机移动、航迹渐进显示，由运行时提供播放控件，不要自行实现播放器
- 双方对比类图表固定「蓝方在前、红方在后」，保证多次生成的次序一致
- 航迹按架次区分，避免多架次连成一条线；阵营色由运行时自动映射，不要在图表里写死颜色
- 图表每个都要有中文标题与一句话结论；结论区放在页面底部

## 叙事要点
- 先给双方总量对比，再给结构性差异（机型构成、基地分布），最后给时空证据（航迹与出动时段）
- 必须回答的问题：双方兵力差距在哪、战损比反映什么、出动强度与时空分布是否集中
- 只使用数据包中的事实，样本不足时明示「数据不足以支撑该结论」，不得推断编造
