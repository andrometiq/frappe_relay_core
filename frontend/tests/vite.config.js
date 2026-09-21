import base from '../vite.config.js'
export default {...base,build:{...base.build,outDir:'.scroll-test-dist',rollupOptions:{...base.build.rollupOptions,input:'tests/scroll.html'}}}
