// Builds the SPA, migrates a fresh database and starts the API serving both.
import { execSync, spawn } from 'node:child_process'
import { rmSync, mkdirSync } from 'node:fs'

const backend = new URL('../../backend/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
mkdirSync(`${backend}/var`, { recursive: true })
rmSync(`${backend}/var/e2e.db`, { force: true })
const env = {
  ...process.env,
  ENVIRONMENT: 'test',
  DATABASE_URL: process.env.E2E_DATABASE_URL,
  EMAIL_TRANSPORT: 'console',
  APP_BASE_URL: 'http://127.0.0.1:8001',
  FRONTEND_DIST_DIR: '../frontend/dist',
  LOCAL_STORAGE_DIR: './var/e2e-docs',
  JOB_TRIGGER_TOKEN: 'e2e-token',
  RUN_INPROCESS_SCHEDULER: 'false',
}
execSync('npm run build', { stdio: 'inherit', cwd: new URL('..', import.meta.url) })
execSync('uv run alembic upgrade head', { stdio: 'inherit', cwd: backend, env })
const server = spawn('uv', ['run', 'uvicorn', 'app.main:app', '--port', '8001', '--host', '127.0.0.1'], { stdio: 'inherit', cwd: backend, env, shell: process.platform === 'win32' })
process.on('SIGTERM', () => server.kill())
process.on('exit', () => server.kill())
