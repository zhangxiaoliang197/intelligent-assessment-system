/**
 * 态势图导出（html2canvas + jsPDF，ADR-12）。
 *
 * 截取 .situation-capture-root 节点为 canvas → 分页写入 A4 PDF。
 *
 * 地图底图说明：
 * - 瓦片走 vite/nginx 同源代理（/geowebcache → GeoServer:9090），浏览器视角是同源；
 * - 因此 html2canvas 用 useCORS:false 直接读取同源瓦片即可，canvas 不会被跨域污染；
 * - 若打开 useCORS:true，html2canvas 会给瓦片 <img> 加 crossorigin=anonymous，
 *   经代理转发到 GeoServer 后因服务端未返回 CORS 头而加载失败，导致底图空白。
 */
import { ElMessage } from 'element-plus'

export function useSituationExport() {
  /** 等待当前视口内的 Leaflet 瓦片全部加载完成（或超时），避免截图时底图空白。 */
  async function waitForTiles(root: HTMLElement, timeout = 4000): Promise<void> {
    const imgs = Array.from(root.querySelectorAll<HTMLImageElement>('img.leaflet-tile'))
    if (!imgs.length) return
    await Promise.race([
      Promise.all(
        imgs.map((img) =>
          img.complete
            ? Promise.resolve()
            : new Promise<void>((resolve) => {
                img.addEventListener('load', () => resolve(), { once: true })
                img.addEventListener('error', () => resolve(), { once: true })
              }),
        ),
      ),
      new Promise<void>((resolve) => setTimeout(resolve, timeout)),
    ])
  }

  async function exportPDF(rootSelector = '.situation-capture-root', fileName = '态势图.pdf') {
    const node = document.querySelector(rootSelector) as HTMLElement
    if (!node) {
      ElMessage.warning('未找到可导出的内容区')
      return
    }
    try {
      const [{ default: html2canvas }, jsPdfMod] = await Promise.all([
        import('html2canvas'),
        import('jspdf'),
      ])
      const jsPDF = jsPdfMod.jsPDF || jsPdfMod.default
      await waitForTiles(node)
      const canvas = await html2canvas(node, {
        scale: 2,
        useCORS: false,
        preferCSSPageSize: true,
        backgroundColor: '#fff',
        logging: false,
      } as any)

      const pdf = new jsPDF('p', 'mm', 'a4')
      const pageWidth = pdf.internal.pageSize.getWidth()
      const pageHeight = pdf.internal.pageSize.getHeight()
      const imgWidth = pageWidth
      const imgHeight = (canvas.height * imgWidth) / canvas.width

      let position = 0
      let heightLeft = imgHeight
      const imgData = canvas.toDataURL('image/jpeg', 0.92)

      pdf.addImage(imgData, 'JPEG', 0, position, imgWidth, imgHeight)
      heightLeft -= pageHeight
      while (heightLeft > 0) {
        position -= pageHeight
        pdf.addPage()
        pdf.addImage(imgData, 'JPEG', 0, position, imgWidth, imgHeight)
        heightLeft -= pageHeight
      }
      pdf.save(fileName)
      ElMessage.success('导出成功')
    } catch (e: any) {
      console.error('导出失败', e)
      ElMessage.error('导出失败：' + (e?.message || '未知错误'))
    }
  }

  async function exportImage(rootSelector = '.situation-capture-root', fileName = '态势图.png') {
    const node = document.querySelector(rootSelector) as HTMLElement
    if (!node) {
      ElMessage.warning('未找到可导出的内容区')
      return
    }
    try {
      const { default: html2canvas } = await import('html2canvas')
      await waitForTiles(node)
      const canvas = await html2canvas(node, {
        scale: 2,
        useCORS: false,
        preferCSSPageSize: true,
        backgroundColor: '#fff',
        logging: false,
      } as any)
      const link = document.createElement('a')
      link.download = fileName
      link.href = canvas.toDataURL('image/png')
      link.click()
      ElMessage.success('导出成功')
    } catch (e: any) {
      console.error('导出失败', e)
      ElMessage.error('导出失败：' + (e?.message || '未知错误'))
    }
  }

  return { exportPDF, exportImage }
}
