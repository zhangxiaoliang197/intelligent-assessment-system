/**
 * 态势图 SSE 接收器（docs/situation-map/05 §4）。
 *
 * 封装 EventSource 订阅/断开逻辑。事件分发到 situationStore.applyEvent。
 * store 是唯一订阅所有者；重复 start 同一 reportId 会被 store 幂等忽略。
 * 本 composable 只补充组件卸载时的生命周期清理。
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
