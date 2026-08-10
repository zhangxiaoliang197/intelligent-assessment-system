/**
 * 态势图导出（html2canvas + jsPDF，ADR-12）。
 *
 * 截取 .situation-capture-root 节点为 canvas → 分页写入 A4 PDF。
 * 注意：Leaflet 地图瓦片需 crossOrigin，否则截图跨域瓦片空白（docs/situation-map/05 §9）。
 */
import { ElMessage } from 'element-plus'

export function useSituationExport() {
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
      const canvas = await html2canvas(node, {
        scale: 2,
        useCORS: true,
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
      const canvas = await html2canvas(node, {
        scale: 2,
        useCORS: true,
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
