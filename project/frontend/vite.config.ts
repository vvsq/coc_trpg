import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueJsx(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
  proxy: {
    '/api': 'http://localhost:8000',
    // WS 代理必须带 ws: true，否则浏览器握手请求到不了 FastAPI
    '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
