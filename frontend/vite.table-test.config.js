import config from './vite.config.js'
export default {...config,build:{...config.build,outDir:'../.runtime/frappe-table-harness',rollupOptions:{...config.build.rollupOptions,input:'tests/browser/table.html'}}}
