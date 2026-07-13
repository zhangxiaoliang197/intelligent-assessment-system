/**
 * 图片上传 Composable
 * ————————————————————————————————
 * 封装图片上传逻辑：发送到 /image/upload 保存到 data/images/，
 * 返回 image_id 用于对话时引用。
 *
 * 使用方式：
 *   const { images, uploading, upload, remove, clear } = useImageUpload()
 *   选图片后自动上传，预览和 image_id 同时可用。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

export interface ImageInfo {
  image_id: string
  filename: string
  preview_url: string
}

export function useImageUpload() {
  const images = ref<ImageInfo[]>([])
  const uploading = ref(false)

  /** base64 encode the file as data URL for local preview */
  function fileToPreview(file: File): Promise<string> {
    return new Promise((resolve) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result as string)
      reader.readAsDataURL(file)
    })
  }

  async function upload(file: File): Promise<ImageInfo | null> {
    const allowed = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp']
    if (!allowed.includes(file.type)) {
      ElMessage.warning('仅支持 PNG / JPG / GIF / WebP / BMP 格式')
      return null
    }
    if (file.size > 10 * 1024 * 1024) {
      ElMessage.warning('图片大小不能超过 10MB')
      return null
    }

    uploading.value = true
    try {
      const formData = new FormData()
      formData.append('file', file)
      const resp = await fetch('/api/image/upload', { method: 'POST', body: formData })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }))
        throw new Error(err.detail || `上传失败 (${resp.status})`)
      }
      const data = await resp.json()
      if (!data.success) throw new Error('上传失败')

      const info: ImageInfo = {
        image_id: data.image_id,
        filename: data.filename,
        preview_url: await fileToPreview(file),
      }
      images.value.push(info)
      return info
    } catch (e: any) {
      ElMessage.error(e.message || '图片上传失败')
      return null
    } finally {
      uploading.value = false
    }
  }

  function remove(idx: number) {
    images.value.splice(idx, 1)
  }

  function clear() {
    images.value = []
  }

  /** 返回当前最新图片的 image_id，无图片返回 undefined */
  function getImageId(): string | undefined {
    return images.value.length > 0 ? images.value[0].image_id : undefined
  }

  return { images, uploading, upload, remove, clear, getImageId }
}
