<script setup>
import { computed, defineAsyncComponent, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { whatsappRoute, whatsappSections } from '../../services/navigation'
import { routeTab } from '../../useViewRoute'
import WhatsAppWorkspace from '../WhatsAppWorkspace.vue'
import WhatsAppIdentity from '../WhatsAppIdentity.vue'

const capabilities = inject('relayCapabilities')
const views = {
  templates: WhatsAppWorkspace,
  campaigns: defineAsyncComponent(() => import('../CampaignsWorkspace.vue')),
  forms: defineAsyncComponent(() => import('./WhatsAppForms.vue')),
  billing: defineAsyncComponent(() => import('./WhatsAppBilling.vue')),
}
const tabs = computed(() => [...whatsappSections(capabilities.value), { name: 'account', label: 'Account' }])
const requested = ref(routeTab(location.hash, 'templates'))
const tab = computed(() => (tabs.value.find(item => item.name === requested.value) || tabs.value[0]).name)
const account = ref(''), configured = ref(null), error = ref('')

function open(name) { location.hash = whatsappRoute(name) }
function readRoute() { requested.value = routeTab(location.hash, 'templates') }
async function load() {
  error.value = ''
  try {
    const [settings, channel] = await Promise.all([coreApi('settings.connection'), coreApi('whatsapp.connection')])
    account.value = settings.account; configured.value = channel.configured
  } catch (e) { error.value = e.message }
}
onMounted(() => { load(); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => window.removeEventListener('hashchange', readRoute))
</script>
<template>
  <section class="v1-screen channel-section">
    <header class="channel-section-header">
      <FeatherIcon name="message-circle" class="h-4 w-4" />
      <h2>WhatsApp<template v-if="account"> · {{ account }}</template></h2>
      <Badge v-if="configured !== null" :label="configured ? 'Connected' : 'Needs setup'" :theme="configured ? 'green' : 'orange'" />
    </header>
    <nav class="v1-tabs" aria-label="WhatsApp sections">
      <Button v-for="item in tabs" :key="item.name" :label="item.label" :variant="tab === item.name ? 'solid' : 'ghost'" :aria-current="tab === item.name ? 'page' : undefined" @click="open(item.name)" />
    </nav>
    <div v-if="tab === 'account'" class="v1-content space-y-5">
      <ErrorMessage :message="error" />
      <div class="workflow-card">
        <h2 class="font-semibold">Account and sending number</h2><p>Account: {{ account || 'Not configured' }}</p>
        <WhatsAppIdentity v-if="configured" /><p v-else>Enable this account’s WhatsApp channel to read its identity.</p>
      </div>
      <div class="flex flex-wrap gap-3"><a class="v1-link" href="#/settings">Hub connection and setup</a><a class="v1-link" href="/desk/relay-channel">Configure channel</a></div>
    </div>
    <component :is="views[tab]" v-else v-bind="tab === 'billing' ? { account } : {}" />
  </section>
</template>
<style scoped>
.channel-section-header { display:flex; align-items:center; gap:8px; padding:12px 16px 4px; color:var(--ink-gray-8); }
.channel-section-header h2 { font-size:15px; font-weight:600; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.channel-section-header svg { color:var(--ink-gray-5); flex-shrink:0; }
.channel-section > :last-child { display:flex; flex:1; flex-direction:column; min-height:0; }
</style>
