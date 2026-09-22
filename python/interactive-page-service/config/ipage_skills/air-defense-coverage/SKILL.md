---
id: air-defense-coverage
name: 防空与威胁覆盖
description: 地面防空阵地、雷达与威胁目标的位置、覆盖范围与能力对比。当用户问及防空体系、
  威胁分布、探测/打击范围、阵地覆盖或需要「范围圈」展示时使用。
category: 态势分析
order: 20
triggers:
  - 分析防空阵地与威胁覆盖范围
  - 双方雷达与导弹阵地分布及探测范围
  - 威胁目标分布与打击覆盖能力
  - 防空体系的覆盖范围对比
requiredEntityKinds: [ground_facility]
recommendedChartTypes: [bar, radar]
mapModes: [circles, points]
playback: false
requiredSections: [kpi, chart, map, text]
focusMetrics: [阵地数量, 探测半径, 打击半径, 覆盖面积]
interactions: [阵地类型筛选, 范围圈开关, 阵地详情查看]
---

## 取数剧本
- need: entityKind=ground_facility, mode=aggregate, question=按设施类型与阵营统计阵地数量与平均覆盖半径
- need: entityKind=ground_facility, mode=detail, geo=circles, question=各阵地的位置与探测半径、打击半径
- need: entityKind=ground_facility, mode=detail, geo=points, question=缺少半径字段的设施的位置与类型

## 区块剧本
kpi(阵地与覆盖概览) → chart(设施类型分布) → chart(覆盖能力对比) → map(范围圈与阵地) → text(结论)
- 范围圈与阵地符号共用地图区块；同一阵地既有探测圈又有打击圈时按不同线型区分（运行时自动处理）
- 若数据无半径字段，则降级为阵地点位地图，不得编造半径

## 呈现偏好
- 地图图层顺序固定为「底图 → 范围圈 → 阵地点位」，避免范围圈盖住阵地符号
- 范围圈不要使用高饱和填充，保持半透明，保证底图与文字可读
- 覆盖能力对比优先用雷达图（多维能力）或条形图（排名），按数据实际维度选择
- 结论区放页面底部，逐条回答覆盖重心与空隙在哪

## 叙事要点
- 先给阵地总量与类型结构，再给覆盖半径差异，最后指出覆盖重叠区与空隙区
- 必须回答的问题：哪一方的覆盖范围更大、覆盖重心在哪、是否存在明显空隙
- 半径缺失或数据不完整时明示「部分阵地缺少范围数据」，不得用推断值补齐
