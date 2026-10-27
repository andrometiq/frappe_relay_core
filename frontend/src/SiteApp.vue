<script setup>
import { computed, defineAsyncComponent, onErrorCaptured, onMounted, provide, ref, watch, nextTick } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon } from '@relay/ui'
import { linkedTitle } from './services/linkedTitle'
import { coreApi, frappeRequest } from './services/coreApi'
import { realtimeStatus, startRealtime } from './services/realtime'
import LoadingRows from './components/LoadingRows.vue'
import ConnectedMessages from './components/ConnectedMessages.vue'
import NotificationInbox from './components/NotificationInbox.vue'
import { routeTab, useViewRoute } from './useViewRoute'
import { navAllowed, whatsappRoute, whatsappSections } from './services/navigation'
import MobileTabBar from './components/shell/MobileTabBar.vue'
import { useMobileLayout } from './composables/useMobileLayout'
import { useQueueCounts } from './composables/useQueueCounts'
import { countLabel } from './services/queueCounts'
import { defaultMedium, pageCapabilities } from './services/enabledChannels'

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
  { name: 'Tickets', label: 'Tickets', icon: 'bookmark' },
  { name: 'Contacts', label: 'Contacts & Links', icon: 'users' },
  { name: 'WhatsApp', label: 'WhatsApp', icon: 'message-circle', group: 'Channels', channel: 'WhatsApp' },
  { name: 'Business events', label: 'Business events', icon: 'zap', business_events: true, group: 'Manage' },
  { name: 'Skills', label: 'AI skills', icon: 'bot', skills: true, group: 'Manage' },
  { name: 'Settings', label: 'Settings & Setup', icon: 'settings', configure: true, group: 'System manager' },
  { name: 'Activity', label: 'Activity & Health', icon: 'activity', configure: true, group: 'System manager' },
  { name: 'Teams', label: 'Teams & Access', icon: 'user-check', teams: true, group: 'Manage' },
]
const view = useViewRoute(Object.keys(views), 'Messages')
const rendered = pageCapabilities(document.getElementById('app'))
const capabilities = ref(rendered || { manage: false, configure: false, teams: false, billing: false, multi_team: false, skills: false, business_events: false }), ready = ref(Boolean(rendered))
const mobile = ref(false), error = ref(''), loadError = ref('')
const current = computed(() => navigation.find(item => item.name === view.value))
const visible = computed(() => navigation.filter(item => navAllowed(item, capabilities.value)))
const menu = computed(() => ['', 'Channels', 'Manage', 'System manager'].map(group => ({ group, items: visible.value.filter(item => (item.group || '') === group) })).filter(section => section.items.length))
const isMobile = useMobileLayout(), moreOpen = ref(false)
const { counts: queueCounts } = useQueueCounts(computed(() => defaultMedium(capabilities.value)))
const inboxBadge = computed(() => countLabel(queueCounts.value.unread))
const sections = computed(() => whatsappSections(capabilities.value))
const hash = ref(location.hash)
const section = computed(() => view.value === 'WhatsApp' ? routeTab(hash.value, 'templates') : '')
const subActive = name => section.value === name
const whatsappOpen = ref(true)
const itemActive = item => view.value === item.name && !(item.name === 'WhatsApp' && whatsappOpen.value && sections.value.some(row => subActive(row.name)))
function openSection(name) { location.hash = whatsappRoute(name) }
function openNavigation() {
  if (isMobile.value) moreOpen.value = true
  else mobile.value = true
}
const user = window.frappe?.session?.user || document.getElementById('app')?.dataset.user || 'Account'
const userTitle = computed(() => linkedTitle('User', user, 'Account'))
provide('relayCapabilities', capabilities)
async function initialize() {
  if (ready.value) return
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
function focusSearch(event) {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') return
  const input = document.querySelector('#relay-titlebar-search input')
  if (!input) return
  event.preventDefault()
  input.focus()
}
onMounted(() => { startRealtime(); initialize(); window.addEventListener('hashchange', () => { hash.value = location.hash }); window.addEventListener('keydown', focusSearch) })
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
    <header class="page-header v1-header" :inert="mobile || moreOpen || undefined">
      <Button id="relay-menu" class="relay-mobile-menu" icon="menu" aria-label="Open navigation" :aria-expanded="mobile" @click="openNavigation" />
      <span class="relay-brand"><span class="relay-logo" aria-hidden="true"><FeatherIcon name="message-circle" /></span>Relay</span>
      <h1>{{ current?.label }}</h1>
      <div id="relay-titlebar-search" class="relay-titlebar-search" />
      <div class="ml-auto flex items-center gap-2"><div id="relay-header-actions" class="relay-header-actions" /><span class="v1-connection" :class="{ 'is-connected': realtimeStatus === 'Live' }" role="status"><span aria-hidden="true" />{{ realtimeStatus }}</span><NotificationInbox /></div>
    </header>
    <aside class="app-nav" :class="{ 'mobile-nav-open': mobile }" aria-label="Relay navigation" @keydown="trapNavigation">
      <nav v-for="section in menu" :key="section.group" class="relay-nav-section" :aria-label="section.group || 'Workspace'">
        <p v-if="section.group" class="relay-nav-group" aria-hidden="true">{{ section.group }}</p>
        <template v-for="item in section.items" :key="item.name">
          <div class="nav-row">
            <button class="nav-item" :class="{ active: itemActive(item) }" :data-channel="item.channel" :aria-current="itemActive(item) ? 'page' : undefined" @click="view = item.name">
              <FeatherIcon :name="item.icon" class="h-4 w-4" /><span class="relay-nav-label">{{ item.label }}</span>
              <span v-if="item.name === 'Messages' && inboxBadge" class="nav-count" :aria-label="`${inboxBadge} unread chats`">{{ inboxBadge }}</span>
            </button>
            <button v-if="item.name === 'WhatsApp' && sections.length" type="button" class="nav-chevron" :aria-expanded="whatsappOpen"
              :aria-label="whatsappOpen ? 'Hide WhatsApp pages' : 'Show WhatsApp pages'" @click="whatsappOpen = !whatsappOpen"><FeatherIcon name="chevron-down" :size="12" /></button>
          </div>
          <template v-if="item.name === 'WhatsApp' && whatsappOpen">
            <button v-for="row in sections" :key="row.name" class="nav-item nav-sub" :class="{ active: subActive(row.name) }"
              :aria-current="subActive(row.name) ? 'page' : undefined" @click="openSection(row.name)">
              <FeatherIcon :name="row.icon" class="h-4 w-4" /><span class="relay-nav-label">{{ row.label }}</span>
            </button>
          </template>
        </template>
      </nav>
      <div class="relay-nav-footer">
        <a href="/desk/relay-core" class="nav-item"><FeatherIcon name="grid" class="h-4 w-4" /><span class="relay-nav-label">Frappe Desk</span></a>
        <div class="relay-account"><Avatar :label="userTitle" size="sm" aria-hidden="true" /><span class="relay-user-name" :title="userTitle">{{ userTitle }}</span><Button icon="log-out" aria-label="Sign out" @click="logout" /></div>
      </div>
    </aside>
    <main class="workspace" :inert="mobile || moreOpen || undefined">
      <h1 v-if="view !== 'Messages'" class="workspace-title">{{ current?.label }}</h1>
      <div v-if="error || loadError" class="px-4 py-2"><ErrorMessage :message="error || loadError" /><Button v-if="!ready" label="Retry access check" @click="initialize" /><Button v-if="loadError" label="Refresh Relay" @click="location.reload()" /></div>
      <LoadingRows v-if="!ready && !error" label="Loading workspace…" :count="6" />
      <p v-else-if="current && !navAllowed(current, capabilities)" class="p-4">Your role does not include this page.</p>
      <component :is="views[view]" v-else-if="ready" v-bind="['Skills', 'Business events'].includes(view) ? { kind: view === 'Skills' ? 'skills' : 'business_events' } : {}" />
    </main>
    <MobileTabBar v-if="isMobile && ready" v-model:open="moreOpen" :items="visible" :sections="sections" :view="view" :section="section" @navigate="view = $event" @section="openSection">
      <template #footer>
        <a href="/desk/relay-core" class="mobile-sheet-item"><span class="mobile-sheet-icon"><FeatherIcon name="grid" :size="18" /></span><span>Frappe Desk</span></a>
        <div class="relay-account mobile-sheet-account"><Avatar :label="userTitle" size="sm" aria-hidden="true" /><span class="relay-user-name" :title="userTitle">{{ userTitle }}</span><Button icon="log-out" aria-label="Sign out" @click="logout" /></div>
      </template>
    </MobileTabBar>
  </div>
</template>
