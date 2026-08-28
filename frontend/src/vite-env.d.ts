/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface ImportMetaEnv {
  readonly VITE_APP_TITLE: string
  /** 动态本体（Palantir 项目）前端地址，默认 http://localhost:3000 */
  readonly VITE_AEGIS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
