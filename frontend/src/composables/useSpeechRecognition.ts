/**
 * 浏览器语音识别 Composable
 * ————————————————————————————————
 * 基于 Web Speech API (SpeechRecognition) 封装，将用户语音实时转为文本。
 *
 * 兼容性：
 *   - Chrome / Edge 完整支持
 *   - Firefox / Safari 不支持 SpeechRecognition（仅 Webkit 前缀）
 *   - 内网环境无需网络（浏览器内置引擎）
 *
 * 使用方式：
 *   const { isListening, transcript, start, stop, toggle } = useSpeechRecognition()
 *   调用 start() 开始监听，stop() 停止，transcript 实时更新识别结果
 *
 * 注意：
 *   - 需要用户手动授权麦克风（HTTPS 或 localhost）
 *   - 部分浏览器在长时间无语音输入后会自动停止
 *   - Edge 的 SpeechRecognition 能力最强（支持离线识别）
 */
import { ref, onUnmounted } from 'vue'

// 浏览器兼容性检测：Chrome/Edge 使用 webkitSpeechRecognition
const SpeechRecognitionAPI =
  (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition

export function useSpeechRecognition() {
  // 是否正在监听中
  const isListening = ref(false)
  // 当前此轮识别到的完整文本
  const transcript = ref('')
  // 是否被浏览器支持
  const isSupported = ref(!!SpeechRecognitionAPI)
  // 错误信息（如麦克风被拒绝）
  const error = ref('')

  let recognition: any = null

  /**
   * 启动语音识别
   * ————————————————————
   * 复用已有 recognition 实例以提升连续识别的性能。
   * 每次 start() 会重置 transcript 开始新一轮识别。
   */
  function start() {
    if (!SpeechRecognitionAPI) {
      error.value = '当前浏览器不支持语音识别，请使用 Chrome 或 Edge 浏览器'
      return
    }

    error.value = ''

    try {
      if (recognition) {
        // 销毁旧的实例，避免状态污染
        try { recognition.stop() } catch (_) { /* noop */ }
      }

      recognition = new SpeechRecognitionAPI()
      recognition.lang = 'zh-CN'               // 中文普通话
      recognition.interimResults = true         // 实时显示中间结果
      recognition.continuous = true             // 连续识别（不自动停止）
      recognition.maxAlternatives = 1           // 只取最可能的识别结果

      recognition.onresult = (event: any) => {
        let final = ''
        let interim = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i]
          if (result.isFinal) {
            final += result[0].transcript
          } else {
            interim += result[0].transcript
          }
        }
        // 实时更新：已确认的 + 中间结果
        transcript.value = final + interim
      }

      recognition.onerror = (event: any) => {
        console.warn('[Speech] Error:', event.error, event.message)
        if (event.error === 'not-allowed') {
          error.value = '麦克风权限被拒绝，请在浏览器设置中允许麦克风访问'
        } else if (event.error === 'no-speech') {
          // 无语音输入，静默忽略（不报错）
        } else if (event.error === 'aborted') {
          // 主动调用 stop() 时触发，正常行为
        } else {
          error.value = `语音识别出错: ${event.error}`
        }
        if (event.error !== 'aborted' && event.error !== 'no-speech') {
          isListening.value = false
        }
      }

      recognition.onend = () => {
        // 自动结束时（非用户主动停止），标记为停止
        if (isListening.value) {
          isListening.value = false
        }
      }

      recognition.start()
      isListening.value = true
    } catch (e: any) {
      error.value = `启动语音识别失败: ${e.message || e}`
      isListening.value = false
    }
  }

  /**
   * 停止语音识别并返回当前识别到的完整文本。
   * 注意：interimResults 会在 stop() 时 finalize 所有未完成的结果。
   */
  function stop(): string {
    if (recognition) {
      try { recognition.stop() } catch (_) { /* noop */ }
    }
    isListening.value = false
    return transcript.value
  }

  /** 切换监听状态（开始 ↔ 停止） */
  function toggle() {
    if (isListening.value) {
      stop()
    } else {
      start()
    }
  }

  /** 组件卸载时确保释放资源 */
  onUnmounted(() => {
    if (recognition) {
      try { recognition.stop() } catch (_) { /* noop */ }
    }
  })

  return { isListening, transcript, isSupported, error, start, stop, toggle }
}
