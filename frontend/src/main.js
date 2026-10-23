import './services/theme'
import { createApp } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import PrimeVue from 'primevue/config'
import App from './App.vue'
import './style.css'
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
createApp(App).use(PrimeVue, { unstyled: true }).use(router).mount('#app')
