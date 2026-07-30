/**
 * Markdown 渲染工具函数。
 *
 * 封装 marked（解析）与 DOMPurify（XSS 防护），
 * 将 LLM 流式输出的 Markdown 文本转换为安全 HTML 字符串，
 * 供 Vue 模板中的 v-html 绑定使用。
 *
 * 依赖：marked（GFM 表格 / breaks 已开启）、dompurify（默认允许规则）
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// ── marked 全局配置（仅设置一次）────────────────────────────────
marked.setOptions({
  gfm: true,      // GitHub Flavoured Markdown：开启表格、删除线、TaskList 等
  breaks: true,   // 单换行符也转换为 <br>，适配 LLM 流式输出的自然换行
})

/**
 * 将 Markdown 文本渲染为安全的 HTML 字符串。
 *
 * 先由 marked 解析，再经 DOMPurify 清洗，防止 XSS 攻击。
 *
 * @param text - 原始 Markdown 文本（可为空字符串）
 * @returns 安全的 HTML 字符串；输入为空时返回空字符串
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''

  const rawHtml: string = marked.parse(text) as string

  // DOMPurify 默认允许所有安全的 HTML 标签和属性
  // （如 h1-h6 / p / table / th / td / thead / tbody / tr / blockquote /
  //   strong / em / code / pre / ul / ol / li / a / img 等）
  return DOMPurify.sanitize(rawHtml)
}
