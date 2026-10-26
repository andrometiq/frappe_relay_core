import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Icons from 'unplugin-icons/vite'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
// Libraries change less often than Relay code; their own hashed chunk stays cached across Relay deploys.
// Lottie stays in its lazy sticker chunk.
// Fonts stay separate files: the browser fetches each unicode-range face only when the page needs it.
const vendorChunk = id => id.includes('/node_modules/') && !id.includes('/node_modules/lottie-web/') ? 'vendor' : undefined
export default defineConfig({
  base: './', plugins: [vue(), Icons({ compiler: 'vue3', customCollections: { lucide: Object.fromEntries(Object.entries(JSON.parse(readFileSync(new URL('./vendor/lucide.json', import.meta.url), 'utf8')).icons).map(([name, icon]) => [name, '<svg viewBox="0 0 24 24">' + icon.body + '</svg>'])) } })], cacheDir: '.vite',
  resolve: {
    alias: { '@relay/ui': fileURLToPath(new URL('./src/ui/index.js', import.meta.url)) },
    dedupe: ['vue', 'vue-router'],
  },
  build: { assetsInlineLimit: (file, content) => !file.endsWith('.woff2') && content.length < 200000, cssCodeSplit: false, rollupOptions: { output: { inlineDynamicImports: false, manualChunks: vendorChunk } } },
  server: { host: '127.0.0.1' },
})
