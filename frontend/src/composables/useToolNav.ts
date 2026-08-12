import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, PieChart, Document, MapLocation } from '@element-plus/icons-vue'

// 工具切换栏项类型
export interface ToolItem {
  id: number
  name: string
  icon: any
  color: string
  path: string
  current: boolean
}

// 四个功能页面的统一切换栏配置（单一数据源）。
// 新增功能只需在此追加一项，各功能页面自动同步，避免重复维护导致漏配。
const TOOL_DEFS: Array<Omit<ToolItem, 'current'>> = [
  { id: 1, name: '智能问答', icon: ChatDotRound, color: '#409eff', path: '/qa' },
  { id: 2, name: '指标分析', icon: PieChart, color: '#67c23a', path: '/indicator' },
  { id: 3, name: '评估分析', icon: Document, color: '#e6a23c', path: '/evaluation' },
  { id: 4, name: '态势图', icon: MapLocation, color: '#8b5cf6', path: '/situation' }
]

/**
 * 提供四功能页面的统一切换栏数据与跳转方法。
 * current 由当前路由自动推导，无需各页面硬编码。
 */
export function useToolNav() {
  const route = useRoute()
  const router = useRouter()

  const tools = computed<ToolItem[]>(() =>
    TOOL_DEFS.map((t) => ({ ...t, current: route.path === t.path }))
  )

  // 跳转到指定功能页面
  const navigateToTool = (path: string) => {
    router.push(path)
  }

  return { tools, navigateToTool }
}
