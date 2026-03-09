import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }
          if (id.includes('recharts')) {
            return 'vendor-recharts'
          }
          if (id.includes('@tanstack/react-query')) {
            return 'vendor-react-query'
          }
          if (id.includes('@tanstack/react-table')) {
            return 'vendor-react-table'
          }
          if (id.includes('react-router') || id.includes('@remix-run')) {
            return 'vendor-router'
          }
          return 'vendor'
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
