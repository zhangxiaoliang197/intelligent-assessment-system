---
id: mission-progress
name: 任务执行与架次统计
description: 任务清单、执行进度、架次统计与任务要素明细。当用户问及任务执行情况、任务完成度、
  架次安排、任务类型构成或需要逐条查看任务明细时使用。
category: 任务分析
order: 50
triggers:
  - 分析双方任务执行情况与完成度
  - 统计各类型任务的架次数量
  - 任务清单与执行进度明细
  - 按任务类型看兵力投入情况
requiredEntityKinds: [air]
recommendedChartTypes: [bar, line]
mapModes: []
playback: false
requiredSections: [kpi, chart, table, text]
focusMetrics: [任务总数, 完成任务数, 架次总数, 任务类型数]
interactions: [任务类型筛选, 阵营筛选, 明细分页查看]
---

## 取数剧本
- need: mode=aggregate, question=按任务类型与阵营统计任务数量与架次总数
- need: mode=aggregate, question=按任务状态统计完成、进行中与未开始的数量
- need: mode=detail, question=逐条任务明细（含任务类型、所属阵营、执行时段、参战兵力）

## 区块剧本
kpi(任务与架次概览) → chart(任务类型构成) → chart(任务状态分布) → table(任务明细) → text(结论)
- 本技能不要求地图；没有坐标数据时不要强行安排地图区块
- 明细表按照任务的执行时段排序，给出合理分页

## 呈现偏好
- 表格列优先保留：任务类型、所属阵营、执行时段、兵力/架次；列宽自适应，长文本截断并支持查看
- 占比类图表（任务状态分布）分类少时用饼图，分类多时改用条形图
- 时间相关维度用折线图展示变化；图表与表格通过筛选按钮联动
- 结论区放页面底部，不得在表格或图表中写死任何数量

## 叙事要点
- 先给任务总量与架次规模，再给任务类型与状态的构成，最后指出投入重点与进度短板
- 必须回答的问题：任务结构如何、执行进度是否正常、兵力投入集中在哪类任务
- 状态字段缺失时明示「部分任务缺少状态数据」，不得推断完成情况
