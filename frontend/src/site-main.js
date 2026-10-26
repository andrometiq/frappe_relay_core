import './services/theme'
import { createApp } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import PrimeVue from 'primevue/config'
import SiteApp from './SiteApp.vue'
import './style.css'
import './mobile.css'
const root = document.getElementById('app')
window.frappe = window.frappe || {}
window.frappe.csrf_token = root.dataset.csrf || ''
window.frappe.session = { user: root.dataset.user || '' }
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
createApp(SiteApp).use(PrimeVue,{unstyled:true}).use(router).mount(root)
