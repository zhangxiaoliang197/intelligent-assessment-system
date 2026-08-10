/**
 * 态势图 SSE 接收器（docs/situation-map/05 §4）。
 *
 * 封装 EventSource 订阅/断开逻辑。事件分发到 situationStore.applyEvent。
 * 与 store 内的 subscribeSSE 互补：store 自带基础订阅，本 composable 提供生命周期绑定
 * （组件卸载时自动断开，避免内存泄漏与重复订阅）。
 */
import { onUnmounted } from 'vue'
import { useSituationStore } from '@/stores/situation'

export function useSituationStream() {
  const store = useSituationStore()

  function start(reportId: string) {
    store.subscribeSSE(reportId)
  }

  function stop() {
    store.closeStream()
  }

  onUnmounted(() => {
    stop()
  })

  return {
    start,
    stop,
  }
}
