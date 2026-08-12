/**
 * 图表注册表（docs/situation-map/05 §5）。
 *
 * 框架不定死图表类型：新增类型只需 registerChart，不改渲染框架。
 * 起步集覆盖 ECharts 常见图表，统一用 VueECharts 包装组件。
 * LLM 产出的 option 直接喂给 ECharts；buildOption 可做后处理（如统一配色）。
 */
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import {
  BarChart, LineChart, PieChart, RadarChart, GaugeChart,
  ScatterChart, HeatmapChart, GraphChart, SankeyChart, MapChart,
} from 'echarts/charts'
import {
  TitleComponent, TooltipComponent, LegendComponent, GridComponent,
  RadarComponent as RadarComp, VisualMapComponent, GeoComponent,
  DataZoomComponent, ToolboxComponent,
} from 'echarts/components'

// 一次性注册 ECharts 组件（多次调用安全）
use([
  CanvasRenderer,
  BarChart, LineChart, PieChart, RadarChart, GaugeChart,
  ScatterChart, HeatmapChart, GraphChart, SankeyChart, MapChart,
  TitleComponent, TooltipComponent, LegendComponent, GridComponent,
  RadarComp, VisualMapComponent, GeoComponent, DataZoomComponent, ToolboxComponent,
])

export interface ChartDefinition {
  type: string
  name: string                 // 中文名
  component: any               // ECharts 包装组件（组件对象本身，无需 ref 包裹）
  buildOption?: (spec: { option: any; title?: string }) => any
}

const REGISTRY = new Map<string, ChartDefinition>()

export function registerChart(def: ChartDefinition) {
  REGISTRY.set(def.type, def)
}

export function getChart(type: string): ChartDefinition | undefined {
  return REGISTRY.get(type)
}

export function listCharts(): ChartDefinition[] {
  return Array.from(REGISTRY.values())
}

// ── 默认后处理：注入统一标题样式（不覆盖 LLM 已给定的）──
function defaultBuild(spec: { option: any; title?: string }): any {
  const opt = spec.option || {}
  if (spec.title && !opt.title) {
    opt.title = { text: spec.title, left: 'center', textStyle: { fontSize: 14 } }
  }
  if (!opt.tooltip) opt.tooltip = { trigger: 'item' }
  return opt
}

// 起步集（v1）
const STARTER: Array<[string, string]> = [
  ['bar', '柱状图'],
  ['line', '折线图'],
  ['pie', '饼图'],
  ['radar', '雷达图'],
  ['gauge', '仪表盘'],
  ['scatter', '散点图'],
  ['heatmap', '热力图'],
  ['relation', '关系图'],
  ['sankey', '桑基图'],
  ['map', '地图染色'],
]
STARTER.forEach(([type, name]) => {
  // 直接存 VChart 组件对象本身；勿用 ref/shallowRef 包裹，
  // 否则 <component :is="chartDef.component"> 拿到的是 ref 对象而非组件，渲染为空。
  registerChart({ type, name, component: VChart, buildOption: defaultBuild })
})

