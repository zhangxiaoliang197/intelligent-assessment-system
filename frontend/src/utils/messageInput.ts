/**
 * 对话输入统一键盘行为：Enter 发送，Shift+Enter 换行。
 * 输入法正在组词时不发送，避免中文候选确认被误当成提交。
 */
export function sendMessageOnEnter(event: Event | KeyboardEvent, send: () => unknown) {
  if (!(event instanceof KeyboardEvent)) return
  if (event.key !== 'Enter' || event.shiftKey) return
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  send()
}
