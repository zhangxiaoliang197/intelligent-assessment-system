/**
 * Artifact 槽位对账 + 栅格回收（前端兜底层）。
 *
 * 后端 artifact_postprocess.sanitize_artifact 已做同构收口；本工具负责兜住
 * 两类漏网情况：①历史报告（生成于收口逻辑上线前）；②网络中途的旧产物。
 * 规则与后端保持一致：
 *  - 栅格容器 div.grid（12 列），直接子卡片 style.grid-column: span N；
 *  - 图表槽 [data-sit="chart"] 引用不存在的 chartId → 移除；
 *  - 空壳卡片（无槽位/无图表元素且纯文本过短）→ 移除；
 *  - 拥挤图表列（占宽 ≤5 列的嵌套 grid 内含 ≥2 个图表槽）→ 嵌套列占满整行、
 *    剥离内联单列模板、内部卡片两列均布，同层卡片（含地图）全部全宽；
 *  - 发生删除/展开的 grid 剩余卡片均分 12 列（1→12，2→6/6，3→4，≥4→偶数 6 否则 4）；
 *    无任何修改动作时不动 LLM 原 span（与后端同构的幂等早退）；
 *  - 残缺度高（有图表数据但 0 个有效图表槽，或图文地图全空）→ degraded，调用方降级。
 */

export interface ReconcileResult {
  /** 对账与回收后的整页 HTML */
  html: string
  /** 有效图表槽数量 */
  validChartSlots: number
  /** 地图槽数量 */
  mapSlots: number
  /** 被移除的坏槽位数量（引用不存在数据的 chart/narrative_chart） */
  removedBadSlots: number
  /** 残缺度高，不建议沙箱渲染，调用方应走布局树/固定版式降级 */
  degraded: boolean
}

/**
 * 非空卡片判定元素：含任一即认为卡片有实质内容。
 * 实质槽位只认可视化槽（chart/map/kpi）与必注入的叙事槽（narrative*）；
 * map_explanation 是地图附属文本槽，无地图时不得阻止地图空卡被回收。
 */
const SHELL_CONTENT_SELECTOR = [
  'table', 'svg', 'canvas', 'ul', 'ol', 'img', 'iframe',
  '[data-sit="chart"]',
  '[data-sit="map"]',
  '[data-sit="kpi"]',
  '[data-sit="narrative"]',
  '[data-sit="narrative_chart"]',
].join(',')

/**
 * 均分 12 列（与后端 _balanced_spans 同构）。
 * @param n 卡片数量
 * @returns 每张卡的 span 数组
 */
function balancedSpans(n: number): number[] {
  if (n <= 0) return []
  if (n === 1) return [12]
  if (n === 2) return [6, 6]
  if (n === 3) return [4, 4, 4]
  const span = n % 2 === 0 ? 6 : 4
  return new Array(n).fill(span)
}

/** 判断是否空壳卡片：无任何可视化元素、无嵌套栅格、纯文本不足 20 字符 */
function isShellCard(el: HTMLElement): boolean {
  if (el.querySelector('.grid') || el.querySelector(SHELL_CONTENT_SELECTOR)) return false
  return (el.textContent || '').trim().length < 20
}

/** 拥挤图表列判定阈值（与后端 _CRAMPED_COL_SPAN_MAX/_CRAMPED_CHART_MIN 同构） */
const CRAMPED_COL_SPAN_MAX = 5
const CRAMPED_CHART_MIN = 2

/** 取元素栅格占宽 span N（未声明按占满 12 列处理） */
function getColSpan(el: HTMLElement): number {
  const m = /span\s*(\d+)/i.exec(el.style.gridColumn || '')
  return m ? Number(m[1]) : 12
}

/** 枚举栅格直接子级中的 card/grid 元素 */
function directItems(grid: HTMLElement): HTMLElement[] {
  return Array.from(grid.children).filter(
    (c): c is HTMLElement =>
      c instanceof HTMLElement && (c.classList.contains('card') || c.classList.contains('grid')),
  )
}

/**
 * 回收单个栅格容器（调用方保证子栅格已先处理，与后端自底向上一致）：
 * 删空壳直接子 → 拥挤图表列展开 → 0 图表时地图全宽 → 均分列宽；
 * 无任何修改动作时早退，保留 LLM 原始 span。
 * @returns 本层是否发生过修改
 */
function rebuildGrid(grid: HTMLElement, forceMapFull: boolean): boolean {
  // 1. 移除空壳卡片/已被掏空的嵌套栅格
  const shells = directItems(grid).filter((child) => isShellCard(child))
  shells.forEach((child) => child.remove())

  const kept = directItems(grid)
  if (kept.length === 0) return shells.length > 0

  // 2. 拥挤图表列：占宽 ≤5 的嵌套 grid 且内含 ≥2 个图表槽
  const cramped = kept.find(
    (e) =>
      e.classList.contains('grid') &&
      getColSpan(e) <= CRAMPED_COL_SPAN_MAX &&
      e.querySelectorAll('[data-sit="chart"]').length >= CRAMPED_CHART_MIN,
  )
  if (cramped) {
    // 剥离内联单列模板（grid-template-columns:1fr），回落 .grid 类的 12 列轨道
    cramped.style.removeProperty('grid-template-columns')
    cramped.style.gridColumn = 'span 12'
    const innerCards = directItems(cramped).filter((c) => c.classList.contains('card'))
    const innerSpans = balancedSpans(innerCards.length)
    innerCards.forEach((card, i) => {
      card.style.gridColumn = `span ${innerSpans[i]}`
    })
    // 同层其他卡片（含地图卡）全部整行宽，与展开后的图列上下分排
    kept.forEach((e) => {
      if (e !== cramped) e.style.gridColumn = 'span 12'
    })
    return true
  }

  // 3. 无删除且无展开：保持原排版（幂等早退，勿把 LLM 竖排改成意外布局）
  if (shells.length === 0) return false

  // 4. 发生过删除：0 图表时地图卡全宽，其余均分；否则全部均分
  if (forceMapFull) {
    const mapCards = kept.filter((e) => e.querySelector('[data-sit="map"]'))
    const others = kept.filter((e) => !mapCards.includes(e))
    mapCards.forEach((e) => {
      e.style.gridColumn = 'span 12'
    })
    const otherSpans = balancedSpans(others.length)
    others.forEach((e, i) => {
      e.style.gridColumn = `span ${otherSpans[i]}`
    })
    return true
  }

  const spans = balancedSpans(kept.length)
  kept.forEach((item, i) => {
    item.style.gridColumn = `span ${spans[i]}`
  })
  return true
}

/**
 * 标题污染特征：LLM 偶发把规划提示词原文写入 title/h1
 * （如"请承接上一轮主题…不得臆造…以本轮数据源和证据为准"）。命中即视为污染。
 */
const PROMPT_LEAK_PATTERN = /请承接|不得臆造|数据源和证据|可独立查看的专题/

/**
 * 清洗被提示词污染的 title/h1：命中特征时清空节点文本（卡片标题不受影响）。
 */
function stripPromptLeakedTitles(doc: Document): void {
  doc.querySelectorAll('title, h1').forEach((node) => {
    const text = (node.textContent || '').trim()
    if (text.length > 40 && PROMPT_LEAK_PATTERN.test(text)) node.innerHTML = ''
  })
}

/**
 * 对账 Artifact HTML。
 * @param html 后端产物 HTML
 * @param chartIds 当前实际可用的图表 id 列表
 * @param hasMap 是否存在可用地图图层
 * @returns 回收结果；html 解析失败时原样返回并标记 degraded
 */
export function reconcileArtifactHtml(
  html: string,
  chartIds: string[],
  hasMap: boolean,
): ReconcileResult {
  const idSet = new Set(chartIds)
  let removedBadSlots = 0

  const doc = new DOMParser().parseFromString(html, 'text/html')
  if (!doc.body || !html.trim()) {
    return { html, validChartSlots: 0, mapSlots: 0, removedBadSlots: 0, degraded: true }
  }

  // 0. 清洗被规划提示词污染的 title/h1
  stripPromptLeakedTitles(doc)

  // 1. 移除引用不存在图表的 chart / narrative_chart 槽位
  doc.querySelectorAll('[data-sit="chart"][data-ref], [data-sit="narrative_chart"][data-ref]').forEach((node) => {
    const ref = node.getAttribute('data-ref')
    if (ref && !idSet.has(ref)) {
      node.remove()
      removedBadSlots += 1
    }
  })
  // 1.1 无可用地图图层时移除地图槽（避免 kit 留固定高度空白容器），
  //     其外层卡片随后按空壳回收、栅格自动重排
  if (!hasMap) {
    doc.querySelectorAll('[data-sit="map"]').forEach((node) => node.remove())
  }

  // 2. 统计有效槽位（清理之后）
  const validChartSlots = doc.querySelectorAll('[data-sit="chart"]').length
  const mapSlots = doc.querySelectorAll('[data-sit="map"]').length

  // 3. 自底向上栅格回收：DOM 序逆序保证子栅格先于父栅格处理（每个 grid 恰好一次）
  const forceMapFull = validChartSlots === 0 && mapSlots > 0
  const allGrids = Array.from(doc.querySelectorAll('div.grid')) as HTMLElement[]
  allGrids.reverse().forEach((g) => rebuildGrid(g, forceMapFull))

  // 4. 残缺度判定：
  //    - 有图表数据但一个有效图表槽都不剩 → 沙箱必然只剩地图/空白，降级；
  //    - 无图表无地图但 HTML 里也没有对应槽位 → 纯文本由叙事区兜底，降级。
  let degraded = false
  if (chartIds.length > 0 && validChartSlots === 0) degraded = true
  if (chartIds.length === 0 && !hasMap && validChartSlots === 0 && mapSlots === 0) degraded = true

  return {
    html: '<!DOCTYPE html>\n' + doc.documentElement.outerHTML,
    validChartSlots,
    mapSlots,
    removedBadSlots,
    degraded,
  }
}
