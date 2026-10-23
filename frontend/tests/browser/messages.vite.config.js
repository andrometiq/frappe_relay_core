import base from '../../vite.config.js'
export default {
  ...base, base: '/',
  build: { ...base.build, outDir: '../.runtime/messages-simulation-ui', emptyOutDir: true,
    rollupOptions: { ...base.build.rollupOptions, input: 'tests/browser/messages.html' } },
}
