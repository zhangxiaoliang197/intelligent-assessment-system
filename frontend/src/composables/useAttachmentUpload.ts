/**
 * 文档附件上传 Composable
 * ————————————————————————————————
 * 封装文件上传逻辑：使用 FormData 将文件发送到 QA 服务的解析端点，
 * 返回可用于对话的 attachment_id。
 *
 * 数据流：
 *   用户选择文件 → POST /attachment/upload → 后端解析并缓存 →
 *   返回 { attachment_id, filename, text_length, preview }
 *   用户发送消息时携带 attachment_id → 后端注入文档到 LLM 上下文
 *
 * 支持格式：PDF / Word (.doc/.docx) / 纯文本 (.txt)
 * 文件上限：20MB（后端校验）
 *
 * 使用方式：
 *   const { attachments, uploading, upload, remove, clear } = useAttachmentUpload()
 *   <input type="file" @change="upload($event)" />
 *   发送消息前读取 attachments.value[0].attachment_id
 */
import { ref } from 'vue'

export interface AttachmentInfo {
  /** 后端返回的唯一 ID，用于对话时引用 */
  attachment_id: string
  /** 原始文件名 */
  filename: string
  /** 解析后文本长度（字符数） */
  text_length: number
  /** 前 200 字符预览 */
  preview: string
  /** 上传状态 */
  status: 'uploading' | 'success' | 'error'
  /** 错误消息 */
  error?: string
}

export function useAttachmentUpload() {
  const attachments = ref<AttachmentInfo[]>([])
  const uploading = ref(false)

  /**
   * 上传单个文件，返回 AttachmentInfo。
   * 用户选择文件后调用（通常在 @change 事件中）。
   *
   * @param file 来自 <input type="file"> 或 el-upload 的文件对象
   * @returns 上传结果，失败时为 null
   */
  async function upload(file: File): Promise<AttachmentInfo | null> {
    uploading.value = true

    // 1. 先用临时 ID 占位，push 到 reactive 数组
    const tempId = `_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
    attachments.value.push({
      attachment_id: tempId,
      filename: file.name,
      text_length: 0,
      preview: '',
      status: 'uploading',
    })

    // 2. 从 reactive 数组中取回 proxy 引用（关键：必须操作 proxy 才能触发视图更新）
    const idx = attachments.value.length - 1

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch('/api/attachment/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const errText = await response.text()
        let errMsg = errText
        try {
          const errJson = JSON.parse(errText)
          errMsg = errJson.detail || errText
        } catch (_) { /* noop */ }
        throw new Error(errMsg)
      }

      const data = await response.json()
      // 更新 reactive proxy → 视图自动刷新
      attachments.value[idx].attachment_id = data.attachment_id
      attachments.value[idx].text_length = data.text_length
      attachments.value[idx].preview = data.preview
      attachments.value[idx].status = 'success'
      uploading.value = false
      return attachments.value[idx]
    } catch (e: any) {
      attachments.value[idx].status = 'error'
      attachments.value[idx].error = e.message || '上传失败'
      uploading.value = false
      return attachments.value[idx]
    }
  }

  /**
   * 移除指定附件（按 attachment_id）。
   * 若 attachment_id 为空（上传失败），按数组索引移除。
   */
  function remove(attachmentIdOrIndex: string | number) {
    if (typeof attachmentIdOrIndex === 'number') {
      attachments.value.splice(attachmentIdOrIndex, 1)
    } else {
      attachments.value = attachments.value.filter(
        (a) => a.attachment_id !== attachmentIdOrIndex
      )
    }
  }

  /** 清空所有附件 */
  function clear() {
    attachments.value = []
  }

  /** 获取第一个上传成功的 attachment_id（便于直接在请求体中使用） */
  function getAttachmentId(): string {
    const success = attachments.value.find((a) => a.status === 'success')
    return success?.attachment_id || ''
  }

  return { attachments, uploading, upload, remove, clear, getAttachmentId }
}
