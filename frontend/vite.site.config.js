import base from './vite.config.js'
export default {
 ...base, base:'/assets/relay_core/relay/',
 build:{...base.build,manifest:true,outDir:'../relay_core/public/relay',emptyOutDir:true,
  rollupOptions:{...base.build.rollupOptions,input:'site.html'}},
}
