---
id: regional-threat-heatmap
name: 区域威胁热力分析
description: 敌方地面威胁单元的类型构成、威胁等级与空间覆盖分布。当用户问及威胁分布、高危区域、
  威胁热点、防空与雷达阵地位置、威胁覆盖范围时使用。
category: 态势分析
order: 60
triggers:
  - 分析当前区域威胁分布
  - 敌方防空雷达与导弹阵地位置及覆盖范围
  - 哪些区域威胁等级最高
  - 威胁单元类型构成与状态
requiredEntityKinds: [ground_facility]
recommendedChartTypes: [bar, pie]
mapModes: [circles, points]
playback: false
requiredSections: [kpi, chart, map, text]
focusMetrics: [威胁单元数量, 最高威胁等级, 探测半径, 打击半径, 活跃阵地数]
interactions: [威胁类型筛选, 威胁等级筛选, 阵地详情查看]
---

## 取数剧本
- need: entityKind=ground_facility, mode=aggregate, question=按威胁类型与威胁等级统计威胁单元数量与状态构成
- need: entityKind=ground_facility, mode=detail, geo=circles, question=威胁单元的位置、探测半径与打击半径明细

## 区块剧本
kpi(威胁概览) → chart(威胁类型构成) → chart(威胁等级分布) → map(威胁阵地与覆盖范围) → text(结论)
- 覆盖范围圈与圆心处的阵地符号由运行时按半径列自动绘制，不要为同一批阵地另规划点位子问题
- 威胁类型超过可读数量时，在表格中列出明细而非塞进饼图

## 呈现偏好
- 空间强度靠地图图层表达，不要规划热力色块类图表：威胁等级在柱状图中体现，位置与覆盖半径在地图上体现
- 取数时同时保留探测半径与打击半径两列，运行时会各自成圈（探测为虚线、打击为实线）并分别配色
- 覆盖范围圈面积较大时按威胁等级排序渲染，避免高等级圈被低等级圈遮盖
- 每个图表给出中文标题与一句话结论；结论区放页面底部

## 叙事要点
- 先给威胁总量与类型构成，再给等级分布，最后落到空间覆盖与高威胁区域
- 必须回答的问题：威胁主要集中在哪些区域、哪些类型威胁等级最高、覆盖范围是否存在重叠或空白
- 已压制或已摧毁的阵地必须如实呈现并单独说明，不得只展示活跃威胁
- 只使用数据包中的事实，覆盖范围说明不足时明示「数据不足以支撑该结论」，不得推断编造
