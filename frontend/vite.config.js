import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `npm run build` writes the app to ../src/obd_dashboard/static, which the FastAPI app serves.
// `npm run dev` runs a hot-reloading dev server and proxies /api to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: '../src/obd_dashboard/static', emptyOutDir: true },
  server: { port: 5173, proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } } },
})
