import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const proxy = {
  '/docs': { target: process.env.DEMO_API_TARGET || 'http://127.0.0.1:8000' },
  '/openapi.json': { target: process.env.DEMO_API_TARGET || 'http://127.0.0.1:8000' },
  '/api': {
    target: process.env.DEMO_API_TARGET || 'http://127.0.0.1:8000',
    changeOrigin: true,
    rewrite: path => path.replace(/^\/api/, ''),
  },
}
export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, strictPort: true, proxy },
})
