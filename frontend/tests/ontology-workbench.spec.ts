import { test, expect, type Frame, type Page } from '@playwright/test'

test.setTimeout(180000)
async function tool(frame: Frame, name: string, args: Record<string, unknown> = {}) {
  const result = await frame.evaluate(async ({ name, args }) => (window as any).__mcpTools[name](args), { name, args })
  expect(result.success, JSON.stringify(result)).toBe(true)
  return result.data
}
async function loaded(page: Page) {
  await expect(page.locator('.loading-cover')).toHaveCount(0, { timeout: 40000 })
  const frame = page.frames().find(item => item.url().includes('/ontosphere/'))!
  await expect(frame.locator('.vg-card').first()).toBeVisible()
  expect(await frame.evaluate(() => (window as any).__workspaceCtx.editor.authoringState.elements.size)).toBe(0)
  return frame
}
async function acceptDraftChange(page: Page) {
  const confirm = page.getByRole('button', { name: '继续载入', exact: true })
  if (await confirm.isVisible({ timeout: 1000 }).catch(() => false)) await confirm.click()
}

test('真实 Ontosphere：协同推演回放、OWL 2 DL、SHACL、编辑保存与重开', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/ontology')
  await expect(page).toHaveURL(/\/ontology\/ont_demo_qinglan/)
  let frame = await loaded(page)
  expect(await frame.evaluate(() => crossOriginIsolated)).toBe(true)
  await expect(page.getByRole('heading', { name: '装备协同推演' })).toBeVisible()
  await page.getByRole('button', { name: /09:00.*初始编组/ }).click()
  await acceptDraftChange(page)
  frame = await loaded(page)
  await expect(frame.locator('.vg-card')).toHaveCount(20)
  await page.screenshot({ path: '../tmp/ontology-ui/ontosphere-wargame.png', fullPage: true })

  await frame.getByRole('button', { name: '本体图', exact: true }).click()
  await expect(frame.locator('.vg-card__label').filter({ hasText: '就绪装备〔可推导〕' })).toBeVisible()
  await page.screenshot({ path: '../tmp/ontology-ui/ontosphere-tbox.png', fullPage: true })
  await frame.getByRole('button', { name: '实例图', exact: true }).click()
  await expect(frame.locator('.vg-card')).toHaveCount(20)

  await page.getByRole('button', { name: 'OWL 推理', exact: true }).click()
  await expect(page.getByText('OWL 推理已完成，可在原生推理报告中查看推导结果')).toBeVisible({ timeout: 90000 })
  const readyQuery = 'SELECT ?s WHERE { GRAPH <urn:vg:inferred> { ?s a <https://example.org/qinglan/schema#ReadyPlatform> } }'
  expect((await tool(frame, 'queryGraph', { sparql: readyQuery })).rows).toHaveLength(8)
  const units = await tool(frame, 'queryGraph', { sparql: 'SELECT ?s WHERE { GRAPH <urn:vg:inferred> { ?s a <https://example.org/qinglan/schema#SupportedUnit> } }' })
  expect(units.rows).toHaveLength(3)
  await page.screenshot({ path: '../tmp/ontology-ui/ontosphere-reasoning.png', fullPage: true })
  await page.getByRole('button', { name: '约束验证', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'SHACL 验证通过' })).toBeVisible()
  await page.getByRole('dialog', { name: 'SHACL 验证通过' }).locator('.el-dialog__headerbtn').click()

  await page.getByRole('button', { name: /09:15.*状态变化/ }).click()
  await acceptDraftChange(page)
  frame = await loaded(page)
  expect((await tool(frame, 'queryGraph', { sparql: readyQuery })).rows).toHaveLength(0)
  const turnOne = await tool(frame, 'runReasoning', { reasonerBackend: 'konclude' })
  expect(turnOne.isConsistent).toBe(true)
  expect(turnOne.inferredTriples).toBeGreaterThan(20)
  expect((await tool(frame, 'queryGraph', { sparql: readyQuery })).rows).toHaveLength(6)
  const states = await tool(frame, 'queryGraph', { sparql: 'SELECT ?s WHERE { ?s <https://example.org/qinglan/schema#status> "链路降级" }' })
  expect(states.rows).toHaveLength(2)
  await tool(frame, 'updateNode', { iri: 'https://example.org/qinglan/equipment#R02', label: 'R-02 观测平台〔已核验〕' })
  await expect(frame.locator('.vg-card__label').filter({ hasText: 'R-02 观测平台〔已核验〕' })).toBeVisible()

  await page.getByRole('button', { name: '保存本体', exact: true }).click()
  await expect(page.getByText('本体、RDF 数据集与画布布局已保存')).toBeVisible()
  const saved = (await (await request.get('/api/ontology/ont_demo_qinglan/workbench/editor')).json()).data
  expect(saved.dataset).toContain('urn:vg:data')
  expect(saved.turtle).toContain('已核验')
  expect(saved.layouts.abox).toBeTruthy()
  expect(saved.layouts.host.turn).toBe(1)
  expect(saved.turtle).not.toMatch(/equip:R02[^.]+a[^.]*ql:ReadyPlatform/s)
  await page.getByRole('button', { name: '版本记录', exact: true }).click()
  await expect(page.locator('.history-item').last()).toBeVisible()
  await page.locator('.el-drawer__close-btn').click()
  page.on('dialog', dialog => dialog.accept())
  await page.reload()
  frame = await loaded(page)
  await expect(frame.locator('.vg-card__label').filter({ hasText: 'R-02 观测平台〔已核验〕' })).toBeVisible()
  await expect(page.locator('.turn.active')).toContainText('状态变化')
  // Restore the most recent pre-save snapshot as a draft, then save a new revision.
  await page.getByRole('button', { name: '版本记录', exact: true }).click()
  await page.locator('.history-item').first().getByRole('button', { name: '载入这个版本' }).click()
  await loaded(page)
  await expect(page.locator('.turn.active')).toContainText('初始编组')
  await expect(frame.locator('.vg-card__label').filter({ hasText: '已核验' })).toHaveCount(0)
  await expect(frame.locator('.vg-card')).toHaveCount(20)
  await expect(frame.locator('.vg-card__label').filter({ hasText: 'event:E1' })).toHaveCount(0)
  await page.getByRole('button', { name: '保存本体', exact: true }).click()
  await expect(page.getByText('本体、RDF 数据集与画布布局已保存')).toBeVisible()
  expect(errors).toEqual([])
})

test('原生画布保留 SPARQL、布局与聚类入口，窄屏可操作', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 850 })
  await page.goto('/ontology/ont_demo_qinglan')
  const frame = await loaded(page)
  await expect(frame.getByRole('button', { name: '布局', exact: true }).first()).toBeVisible()
  await expect(frame.getByRole('combobox')).toBeVisible()
  await frame.getByRole('button', { name: '图谱查询', exact: true }).click()
  await expect(frame.getByText('图谱查询', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '保存本体', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../tmp/ontology-ui/ontosphere-compact.png', fullPage: true })
})

test('统一蓝白主题、中文设置与中文使用文档', async ({ page }) => {
  await page.goto('/ontology/ont_demo_qinglan')
  const frame = await loaded(page)
  await expect(page.getByRole('heading', { name: '装备协同推演' })).toBeVisible()
  await expect(page.getByRole('region', { name: '推演回合' })).toContainText('回合回放')
  await expect(frame.getByText('R-01 观测平台', { exact: true })).toBeVisible()
  await expect(frame.locator('.vg-card__label').filter({ hasText: '青岚' })).toHaveCount(0)
  expect(await page.locator('.project-bar').evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(255, 255, 255)')
  expect(await frame.evaluate(() => document.documentElement.lang)).toBe('zh-CN')
  expect(await frame.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--primary').trim())).toBe('#3b82f6')
  await expect(frame.getByText('保存', { exact: true })).toBeVisible()
  await expect(frame.getByRole('button', { name: '本体图', exact: true })).toBeVisible()
  await frame.getByRole('button', { name: '设置', exact: true }).click()
  for (const name of ['界面', '性能', '本体推理', '约束验证', '工作流', '高级设置']) {
    await frame.getByRole('tab', { name, exact: true }).click()
    const remaining = await frame.evaluate(() => {
      const result: string[] = [], walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
      while (walker.nextNode()) {
        const node = walker.currentNode, parent = node.parentElement, text = node.textContent?.trim() || ''
        if (!parent?.checkVisibility() || parent.closest('script,style,pre,code,textarea,.font-mono,.vg-card,.reactodia-link') || /[\u4e00-\u9fff]/.test(text)) continue
        if (/^[A-Za-z][A-Za-z -]+\s[A-Za-z]/.test(text) && !/^https?:/.test(text)) result.push(text)
      }
      return result
    })
    expect(remaining, `${name}面板不应残留英文说明`).toEqual([])
  }
  await frame.getByRole('button', { name: '关闭', exact: true }).click()
  await frame.getByRole('button', { name: '使用文档', exact: true }).click()
  await frame.getByRole('button', { name: /装备协同推演$/ }).click()
  const help = frame.getByRole('dialog', { name: '使用文档：装备协同推演' })
  await expect(help).toContainText('8 台装备')
  await expect(help).not.toContainText(/青岚行动|虚构装备/)
  await page.screenshot({ path: '../tmp/ontology-ui/ontosphere-manual-zh.png', fullPage: true })
  await frame.getByRole('button', { name: '关闭使用文档' }).click()
})
