import { defineConfig, devices } from '@playwright/test'

// End-to-end journeys run against the production build served by the real API on one
// origin (exactly the Cloud Run topology), with a throwaway SQLite database.
const db = `sqlite:///${process.cwd().split(String.fromCharCode(92)).join('/')}/../backend/var/e2e.db`

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8001', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, grep: /@responsive/ },
  ],
  webServer: {
    command: 'node e2e/serve.mjs',
    url: 'http://127.0.0.1:8001/readyz',
    timeout: 180_000,
    reuseExistingServer: false,
    env: { E2E_DATABASE_URL: db },
  },
})
