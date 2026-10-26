<script setup>
import { computed, defineAsyncComponent, onErrorCaptured, onMounted, provide, ref, watch, nextTick } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon } from '@relay/ui'
import { linkedTitle } from './services/linkedTitle'
import { coreApi, frappeRequest } from './services/coreApi'
import { realtimeStatus, startRealtime } from './services/realtime'
import LoadingRows from './components/LoadingRows.vue'
import ConnectedMessages from './components/ConnectedMessages.vue'
import NotificationInbox from './components/NotificationInbox.vue'
import { useViewRoute } from './useViewRoute'
import { channelEnabled } from './services/enabledChannels'

const location = window.location
const views = {
  Messages: ConnectedMessages,
  Tickets: defineAsyncComponent(() => import('./components/TicketsWorkspace.vue')),
  Skills: defineAsyncComponent(() => import('./components/AutomationWorkspace.vue')),
  'Business events': defineAsyncComponent(() => import('./components/AutomationWorkspace.vue')),
  Contacts: defineAsyncComponent(() => import('./components/ContactsWorkspace.vue')),
  WhatsApp: defineAsyncComponent(() => import('./components/whatsapp/WhatsAppSection.vue')),
  Teams: defineAsyncComponent(() => import('./components/AccessWorkspace.vue')),
  Settings: defineAsyncComponent(() => import('./components/SiteSettings.vue')),
  Activity: defineAsyncComponent(() => import('./components/ActivityWorkspace.vue')),
}
const navigation = [
  { name: 'Messages', label: 'Inbox', icon: 'inbox' },
  { name: 'Contacts', label: 'Contacts & links', icon: 'users' },
  { name: 'Tickets', label: 'Tickets', icon: 'bookmark' },
  { name: 'Skills', label: 'AI & skills', icon: 'bot', configure: true },
  { name: 'Business events', label: 'Business events', icon: 'zap', configure: true },
  { name: 'WhatsApp', label: 'WhatsApp', icon: 'message-circle', group: 'Channels', channel: 'WhatsApp' },
  { name: 'Teams', label: 'Teams & access', icon: 'user-check', group: 'Admin' },
  { name: 'Settings', label: 'Settings & setup', icon: 'settings', group: 'Admin' },
  { name: 'Activity', label: 'Activity & health', icon: 'activity', manage: true, group: 'Admin' },
]
const view = useViewRoute(Object.keys(views), 'Messages')
const capabilities = ref({ manage: false, configure: false }), ready = ref(false)
const mobile = ref(false), error = ref(''), loadError = ref('')
const current = computed(() => navigation.find(item => item.name === view.value))
const menu = computed(() => {
  const caps = capabilities.value
  const visible = navigation.filter(item => (!item.manage || caps.manage) && (!item.configure || caps.configure) && channelEnabled(caps, item.channel))
  return ['', 'Channels', 'Admin'].map(group => ({ group, items: visible.filter(item => (item.group || '') === group) })).filter(section => section.items.length)
})
const user = window.frappe?.session?.user || document.getElementById('app')?.dataset.user || 'Account'
const userTitle = computed(() => linkedTitle('User', user, 'Account'))
provide('relayCapabilities', capabilities)
async function initialize() {
  error.value = ''
  try { capabilities.value = await coreApi('api.capabilities'); ready.value = true }
  catch (e) { error.value = e.message }
}
async function logout() {
  error.value = ''
  try { await frappeRequest('logout', {}, true); location.assign('/login?redirect-to=/relay') }
  catch (e) { error.value = e.message }
}
function closeNavigation() {
  mobile.value = false
  document.getElementById('relay-menu')?.focus()
}
function trapNavigation(event) {
  if (!mobile.value || event.key !== 'Tab') return
  const nodes = [...event.currentTarget.querySelectorAll('button, a[href]')].filter(node => node.offsetParent)
  const first = nodes[0], last = nodes.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
watch(mobile, async value => { if (value) { await nextTick(); document.querySelector('.mobile-nav-open button')?.focus() } })
watch(view, () => { if (mobile.value) closeNavigation() })
onMounted(() => { startRealtime(); initialize() })
onErrorCaptured(e => {
  if (/dynamically imported module|Loading chunk|Importing a module script/.test(String(e))) {
    loadError.value = 'This screen could not load. Refresh Relay to try again.'
    return false
  }
})
</script>
<template>
  <div class="app-shell relay-shell v1-shell" @keydown.esc="closeNavigation">
    <button v-if="mobile" class="relay-nav-backdrop" aria-label="Close navigation" @click="closeNavigation" />
    <aside class="app-nav" :class="{ 'mobile-nav-open': mobile }" aria-label="Relay navigation" @keydown="trapNavigation">
      <div class="relay-brand"><FeatherIcon name="message-circle" class="h-5 w-5" /><strong>Relay</strong><Button class="mobile-only ml-auto" icon="x" aria-label="Close navigation" @click="closeNavigation" /></div>
      <p class="relay-nav-caption">Communication workspace</p>
      <nav v-for="section in menu" :key="section.group" class="relay-nav-section" :aria-label="section.group || 'Workspace'">
        <p v-if="section.group" class="relay-nav-group" aria-hidden="true">{{ section.group }}</p>
        <button v-for="item in section.items" :key="item.name"
          class="nav-item" :class="{ active: view === item.name }" :aria-current="view === item.name ? 'page' : undefined" @click="view = item.name">
          <FeatherIcon :name="item.icon" class="h-4 w-4" /><span>{{ item.label }}</span>
        </button>
      </nav>
      <div class="relay-nav-footer">
        <a href="/desk/relay-core" class="nav-item"><FeatherIcon name="grid" class="h-4 w-4" />Frappe Desk</a>
        <div class="relay-account"><Avatar :label="userTitle" size="sm" aria-hidden="true" /><span class="relay-user-name" :title="userTitle">{{ userTitle }}</span><Button icon="log-out" aria-label="Sign out" @click="logout" /></div>
      </div>
    </aside>
    <main class="workspace" :inert="mobile || undefined">
      <header class="page-header v1-header">
        <Button id="relay-menu" class="relay-mobile-menu" icon="menu" aria-label="Open navigation" :aria-expanded="mobile" @click="mobile = true" />
        <h1>{{ current?.label }}</h1>
        <div class="ml-auto flex items-center gap-2"><span class="v1-connection" :class="{ 'is-connected': realtimeStatus === 'Live' }" role="status"><span aria-hidden="true" />{{ realtimeStatus }}</span><NotificationInbox /></div>
      </header>
      <div v-if="error || loadError" class="px-4 py-2"><ErrorMessage :message="error || loadError" /><Button v-if="!ready" label="Retry access check" @click="initialize" /><Button v-if="loadError" label="Refresh Relay" @click="location.reload()" /></div>
      <LoadingRows v-if="!ready && !error" label="Loading workspace…" :count="6" />
      <p v-else-if="current?.manage && !capabilities.manage" class="p-4">A Relay Communication Manager role is required. <a href="#/teams" class="underline">Review access</a></p>
      <component :is="views[view]" v-else-if="ready" v-bind="['Skills', 'Business events'].includes(view) ? { kind: view === 'Skills' ? 'skills' : 'business_events' } : {}" />
    </main>
  </div>
</template>
