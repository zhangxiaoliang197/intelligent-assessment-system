import { test, expect } from '@playwright/test'

test('真实服务：现有本体、文献来源和全库分页搜索', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const list = await (await request.get('/api/ontology/list')).json()
  expect(list.items.length).toBeGreaterThan(0)
  const ontology = list.items[0]
  await page.goto(`/ontology/${ontology.id}`)
  await expect(page.getByRole('heading', { name: ontology.name, exact: true })).toBeVisible()
  await expect(page.locator('.loading-cover')).toHaveCount(0, { timeout: 40000 })
  const frame = page.frames().find(item => item.url().includes('/ontosphere/'))!
  await expect(frame.locator('.vg-card').first()).toBeVisible()
  const result = await frame.evaluate(async () => (window as any).__mcpTools.queryGraph({ sparql: 'SELECT ?s WHERE { ?s ?p ?o } LIMIT 10' }))
  expect(result.success).toBe(true)
  expect(result.data.rows.length).toBeGreaterThan(0)
  await page.screenshot({ path: '../tmp/ontology-ui/workbench-live.png', fullPage: true })

  // This record is beyond the original first 200 records in the library.
  const laterPage = await (await request.get('/api/knowledge/list?page_size=200&page=5')).json()
  const target = laterPage.items[0]
  expect(target.literature.source_url).toBeTruthy()
  await page.goto('/knowledge')
  const stats = await (await request.get('/api/knowledge/stats')).json()
  await expect(page.locator('.el-pagination__total')).toContainText(String(stats.data.total_documents))
  await expect(page.locator('.el-table .el-loading-mask:visible')).toHaveCount(0)
  await expect(page.locator('.el-table__body-wrapper tr')).toHaveCount(20)
  await page.getByPlaceholder('搜索文档名称...').fill(target.title)
  await expect(page.locator('.el-table__body-wrapper tr')).toHaveCount(1)
  await expect(page.locator('.el-table__body-wrapper').getByText(target.title, { exact: true })).toBeVisible()
  await expect(page.locator('.el-table__body-wrapper a').first()).toHaveAttribute('href', target.literature.source_url)
  await page.screenshot({ path: '../tmp/ontology-ui/knowledge-live.png', fullPage: true })
  await page.getByPlaceholder('搜索文档名称...').clear()
  await page.locator('.toolbar .el-select').filter({ hasText: '文献内容' }).click()
  await page.getByRole('option', { name: '全文论文', exact: true }).click()
  await expect(page.locator('.el-pagination__total')).toContainText('100')
  const originalLink = page.getByRole('link', { name: '全文 PDF ↗' }).first()
  const pdfUrl = await originalLink.getAttribute('href')
  expect(pdfUrl).toBeTruthy()
  const pdf = await request.get(pdfUrl!)
  expect(pdf.status()).toBe(200)
  expect(pdf.headers()['content-type']).toContain('application/pdf')
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-')
  await page.screenshot({ path: '../tmp/ontology-ui/knowledge-fulltext.png', fullPage: true })
  expect(errors).toEqual([])
})
