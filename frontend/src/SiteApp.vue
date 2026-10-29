<script setup>
import { computed, defineAsyncComponent, onErrorCaptured, onMounted, provide, ref } from 'vue'
import { Avatar, Button, Dropdown, ErrorMessage, FeatherIcon } from '@relay/ui'
import { linkedTitle } from './services/linkedTitle'
import { coreApi, frappeRequest } from './services/coreApi'
import { realtimeStatus, startRealtime } from './services/realtime'
import LoadingRows from './components/LoadingRows.vue'
import ConnectedMessages from './components/ConnectedMessages.vue'
import AccessDenied from './components/AccessDenied.vue'
import NotificationInbox from './components/NotificationInbox.vue'
import TicketNotices from './components/TicketNotices.vue'
import { routeTab, useViewRoute } from './useViewRoute'
import { navAllowed, railGroups, whatsappRoute, whatsappSections } from './services/navigation'
import MobileTabBar from './components/shell/MobileTabBar.vue'
import { useMobileLayout } from './composables/useMobileLayout'
import { useUnreadChats } from './composables/useQueueCounts'
import { defaultMedium, pageCapabilities } from './services/enabledChannels'
import { openLegacyConversation } from './services/legacyLinks'
import { THEME_LABELS, cycleTheme, theme } from './services/theme'

const location = window.location
const views = {
  Messages: ConnectedMessages,
  Tickets: defineAsyncComponent(() => import('./components/TicketsWorkspace.vue')),
  Skills: defineAsyncComponent(() => import('./components/AutomationWorkspace.vue')),
  'Business events': defineAsyncComponent(() => import('./components/AutomationWorkspace.vue')),
  'Channel automation': defineAsyncComponent(() => import('./components/ChannelAutomation.vue')),
  Flows: defineAsyncComponent(() => import('./components/FlowsWorkspace.vue')),
  Contacts: defineAsyncComponent(() => import('./components/ContactsWorkspace.vue')),
  WhatsApp: defineAsyncComponent(() => import('./components/whatsapp/WhatsAppSection.vue')),
  Teams: defineAsyncComponent(() => import('./components/AccessWorkspace.vue')),
  Settings: defineAsyncComponent(() => import('./components/SiteSettings.vue')),
  Activity: defineAsyncComponent(() => import('./components/ActivityWorkspace.vue')),
}
const navigation = [
  { name: 'Messages', label: 'Chats', icon: 'message-square' },
  { name: 'Tickets', label: 'Tickets', icon: 'ticket' },
  { name: 'Contacts', label: 'Contacts', icon: 'users' },
  { name: 'WhatsApp', label: 'WhatsApp', icon: 'message-circle', channel: 'WhatsApp' },
  { name: 'Business events', label: 'Business events', icon: 'zap', business_events: true },
  { name: 'Channel automation', label: 'Channel automation', icon: 'list-ordered', manage: true },
  { name: 'Flows', label: 'Flows', icon: 'git-branch', flows: true },
  { name: 'Skills', label: 'AI skills', icon: 'bot', ai: true, skills: true },
  { name: 'Settings', label: 'Settings', icon: 'settings', manage: true },
  { name: 'Teams', label: 'Roles & access', icon: 'user-check' },
  { name: 'Activity', label: 'Activity & health', icon: 'activity', configure: true },
]
const view = useViewRoute(Object.keys(views), 'Messages')
const rendered = pageCapabilities(document.getElementById('app'))
const capabilities = ref(rendered || { manage: false, configure: false, teams: false, billing: false, multi_team: false, teams_enabled: false, folders: false, ai: false, skills: false, business_events: false, flows: false }), ready = ref(Boolean(rendered))
const error = ref(''), loadError = ref('')
const current = computed(() => navigation.find(item => item.name === view.value))
const visible = computed(() => navigation.filter(item => navAllowed(item, capabilities.value)))
const rail = computed(() => railGroups(visible.value))
const currentGroup = computed(() => rail.value.find(group => group.pages.some(page => page.name === view.value)))
const isMobile = useMobileLayout(), moreOpen = ref(false)
const inboxBadge = useUnreadChats(computed(() => defaultMedium(capabilities.value)))
const sections = computed(() => whatsappSections(capabilities.value))
const hash = ref(location.hash)
const section = computed(() => view.value === 'WhatsApp' ? routeTab(hash.value, 'templates') : '')
function openSection(name) { location.hash = whatsappRoute(name) }
const user = window.frappe?.session?.user || document.getElementById('app')?.dataset.user || 'Account'
const userTitle = computed(() => linkedTitle('User', user, 'Account'))
const accountActions = computed(() => [
  { label: `Theme: ${THEME_LABELS[theme.value][1]}`, icon: THEME_LABELS[theme.value][0], onClick: cycleTheme },
  { label: 'Open Frappe Desk', icon: 'grid', onClick: () => location.assign('/desk/relay-core') },
  { label: 'Sign out', icon: 'log-out', onClick: logout },
])
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
function focusSearch(event) {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') return
  const input = document.querySelector('.inbox-filters input')
  if (!input) return
  event.preventDefault()
  input.focus()
}
onMounted(() => { startRealtime(); initialize(); openLegacyConversation(location, coreApi); window.addEventListener('hashchange', () => { hash.value = location.hash }); window.addEventListener('keydown', focusSearch) })
onErrorCaptured(e => {
  if (/dynamically imported module|Loading chunk|Importing a module script/.test(String(e))) {
    loadError.value = 'This screen could not load. Refresh Relay to try again.'
    return false
  }
})
</script>
<template>
  <div class="app-shell relay-shell v1-shell">
    <header class="page-header v1-header" :inert="moreOpen || undefined">
      <span class="relay-brand"><span class="relay-logo" aria-hidden="true"><FeatherIcon name="message-circle" /></span>Relay</span>
      <h1>{{ current?.label }}</h1>
      <div class="ml-auto flex items-center gap-2"><div id="relay-header-actions" class="relay-header-actions" /><span class="v1-connection" :class="{ 'is-connected': realtimeStatus === 'Live' }" role="status"><span aria-hidden="true" />{{ realtimeStatus }}</span><NotificationInbox /><TicketNotices /></div>
    </header>
    <aside class="app-nav relay-rail" aria-label="Relay navigation">
      <nav class="relay-rail-items" aria-label="Relay sections">
        <template v-for="group in rail" :key="group.name">
          <button v-if="!group.bottom" type="button" class="rail-item" :class="{ active: currentGroup === group }" :title="group.name"
            :aria-current="currentGroup === group ? 'page' : undefined" @click="view = group.pages[0].name">
            <span class="rail-icon"><FeatherIcon :name="group.icon" :size="20" /><span v-if="group.name === 'Chats' && inboxBadge" class="rail-badge" :aria-label="`${inboxBadge} unread chats`">{{ inboxBadge }}</span></span>
            <span class="rail-label">{{ group.name }}</span>
          </button>
        </template>
      </nav>
      <div class="relay-rail-footer">
        <template v-for="group in rail" :key="group.name">
          <button v-if="group.bottom" type="button" class="rail-item" :class="{ active: currentGroup === group }" :title="group.name"
            :aria-current="currentGroup === group ? 'page' : undefined" @click="view = group.pages[0].name">
            <span class="rail-icon"><FeatherIcon :name="group.icon" :size="20" /></span><span class="rail-label">{{ group.name }}</span>
          </button>
        </template>
        <Dropdown :options="accountActions" placement="right">
          <button type="button" class="rail-account" :title="userTitle" :aria-label="`Account: ${userTitle}`"><Avatar :label="userTitle" size="sm" /></button>
        </Dropdown>
      </div>
    </aside>
    <main class="workspace" :inert="moreOpen || undefined">
      <h1 v-if="view !== 'Messages'" class="workspace-title">{{ current?.label }}</h1>
      <nav v-if="currentGroup?.pages.length > 1" class="v1-tabs workspace-subtabs" :aria-label="currentGroup.name + ' pages'">
        <Button v-for="page in currentGroup.pages" :key="page.name" :label="page.label" :variant="view === page.name ? 'solid' : 'ghost'"
          :aria-current="view === page.name ? 'page' : undefined" @click="view = page.name" />
      </nav>
      <div v-if="error || loadError" class="px-4 py-2"><ErrorMessage :message="error || loadError" /><Button v-if="!ready" label="Retry access check" @click="initialize" /><Button v-if="loadError" label="Refresh Relay" @click="location.reload()" /></div>
      <LoadingRows v-if="!ready && !error" label="Loading workspace…" :count="6" />
      <AccessDenied v-else-if="current && !navAllowed(current, capabilities)" :page="current" :capabilities="capabilities" />
      <component :is="views[view]" v-else-if="ready" v-bind="['Skills', 'Business events'].includes(view) ? { kind: view === 'Skills' ? 'skills' : 'business_events' } : {}" />
    </main>
    <MobileTabBar v-if="isMobile && ready" v-model:open="moreOpen" :items="visible" :sections="sections" :view="view" :section="section" :badge="inboxBadge" @navigate="view = $event" @section="openSection">
      <template #footer>
        <a href="/desk/relay-core" class="mobile-sheet-item"><span class="mobile-sheet-icon"><FeatherIcon name="grid" :size="18" /></span><span>Frappe Desk</span></a>
        <div class="relay-account mobile-sheet-account"><Avatar :label="userTitle" size="sm" aria-hidden="true" /><span class="relay-user-name" :title="userTitle">{{ userTitle }}</span><Button :icon="THEME_LABELS[theme][0]" :aria-label="`Theme: ${THEME_LABELS[theme][1]}`" :title="`Theme: ${THEME_LABELS[theme][1]}`" @click="cycleTheme" /><Button icon="log-out" aria-label="Sign out" @click="logout" /></div>
      </template>
    </MobileTabBar>
  </div>
</template>
