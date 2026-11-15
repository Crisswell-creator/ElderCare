/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs on :8000 in development; the proxy keeps cookies first-party, exactly like
// the production single-origin deployment.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      output: {
        // Libraries change far less often than app code: a separate, content-hashed vendor
        // chunk stays cached in browsers across app deploys.
        advancedChunks: {
          groups: [{ name: 'vendor', test: /node_modules[\\/](react|react-dom|react-router|react-router-dom|@tanstack|scheduler)[\\/]/ }],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
