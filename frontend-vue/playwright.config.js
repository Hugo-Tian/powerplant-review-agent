import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 120000,
  expect: { timeout: 10000 },
  use: { baseURL: 'http://127.0.0.1:8766', viewport: { width: 1440, height: 1080 },
    screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: { command: 'python ../scripts/serve_e2e.py', url: 'http://127.0.0.1:8766',
    reuseExistingServer: false, timeout: 60000 },
})
