import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: process.env.WORKBENCH_TEST_URL || 'http://127.0.0.1:10086',
    headless: true,
    actionTimeout: 12000,
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    viewport: { width: 1440, height: 980 },
    screenshot: 'only-on-failure',
  },
  outputDir: '../tmp/ontology-ui/test-results',
})
