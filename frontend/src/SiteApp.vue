<script setup>
import { computed, defineAsyncComponent, onErrorCaptured, onMounted, provide, ref } from 'vue'
import { Button, Dropdown, ErrorMessage, FeatherIcon } from '@relay/ui'
import { linkedTitle } from './services/linkedTitle'
import { coreApi, frappeRequest } from './services/coreApi'
import { realtimeStatus, startRealtime } from './services/realtime'
import LoadingRows from './components/LoadingRows.vue'
import ConnectedMessages from './components/ConnectedMessages.vue'
import AccessDenied from './components/AccessDenied.vue'
import NotificationInbox from './components/NotificationInbox.vue'
import TicketNotices from './components/TicketNotices.vue'
import { routeTab, useViewRoute } from './useViewRoute'
import { activeRailGroup, navAllowed, navListed, opensSetup, railGroups, whatsappRoute, whatsappSections } from './services/navigation'
import MobileTabBar from './components/shell/MobileTabBar.vue'
import SectionSidebar from './components/shell/SectionSidebar.vue'
import ProfileDialog from './components/shell/ProfileDialog.vue'
import UserAvatar from './components/UserAvatar.vue'
import { loadMyProfile, saveMyProfile } from './services/userProfiles'
import { useMobileLayout } from './composables/useMobileLayout'
import { useUnreadChats } from './composables/useQueueCounts'
import { defaultMedium, pageCapabilities } from './services/enabledChannels'
import { openLegacyConversation } from './services/legacyLinks'
import { THEME_LABELS, cycleTheme, theme } from './services/theme'

const location = window.location
const initialPath = location.hash.slice(1).split('?')[0]
const views = {
  Messages: ConnectedMessages,
  Setup: defineAsyncComponent(() => import('./components/onboarding/OnboardingWorkspace.vue')),
  Tickets: defineAsyncComponent(() => import('./components/TicketsWorkspace.vue')),
  Knowledge: defineAsyncComponent(() => import('./components/AIContentWorkspace.vue')),
  Persona: defineAsyncComponent(() => import('./components/AIContentWorkspace.vue')),
  Events: defineAsyncComponent(() => import('./components/AIContentWorkspace.vue')),
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
  { name: 'Setup', label: 'Get started', icon: 'play', configure: true, setup: true },
  { name: 'Messages', label: 'Inbox', icon: 'inbox' },
  { name: 'Tickets', label: 'Tickets', icon: 'ticket' },
  { name: 'Contacts', label: 'Contacts', icon: 'users' },
  { name: 'WhatsApp', label: 'WhatsApp', icon: 'message-circle', channel: 'WhatsApp' },
  { name: 'Business events', label: 'Business events', icon: 'zap', business_events: true },
  { name: 'Channel automation', label: 'Channel automation', icon: 'list-ordered', manage: true },
  { name: 'Flows', label: 'Flows', icon: 'git-branch', flows: true },
  { name: 'Knowledge', label: 'Knowledge base', icon: 'book-open', knowledge: true },
  { name: 'Persona', label: 'Persona', icon: 'smile', persona: true },
  { name: 'Events', label: 'AI events', icon: 'calendar', events: true },
  { name: 'Skills', label: 'AI skills', icon: 'bot', ai: true, skills: true },
  { name: 'Settings', label: 'Settings', icon: 'settings', manage: true },
  { name: 'Teams', label: 'Roles & access', icon: 'user-check' },
  { name: 'Activity', label: 'Activity & health', icon: 'activity', configure: true },
]
const view = useViewRoute(Object.keys(views), 'Messages')
const rendered = pageCapabilities(document.getElementById('app'))
const capabilities = ref(rendered || { manage: false, configure: false, teams: false, billing: false, multi_team: false, teams_enabled: false, folders: false, ai: false, skills: false, knowledge: false, persona: false, events: false, business_events: false, flows: false }), ready = ref(Boolean(rendered))
const error = ref(''), loadError = ref('')
const current = computed(() => navigation.find(item => item.name === view.value))
const visible = computed(() => navigation.filter(item => navListed(item, capabilities.value)))
const setupPending = computed(() => capabilities.value.onboarding?.required && !capabilities.value.configure && !capabilities.value.whatsapp_numbers?.length)
const isMobile = useMobileLayout(), moreOpen = ref(false), pagesOpen = ref(false), profileOpen = ref(false)
const inboxBadge = useUnreadChats(computed(() => defaultMedium(capabilities.value)))
const sections = computed(() => whatsappSections(capabilities.value))
const rail = computed(() => railGroups(visible.value, sections.value))
const hash = ref(location.hash)
// The WhatsApp tab on screen: a tab the user may not open falls back to the first allowed one, as WhatsAppSection does.
const section = computed(() => {
  if (view.value !== 'WhatsApp') return ''
  const tab = routeTab(hash.value, 'templates')
  return tab === 'account' || sections.value.some(item => item.name === tab) ? tab : sections.value[0]?.name || tab
})
const currentGroup = computed(() => activeRailGroup(rail.value, view.value, section.value))
const sidebarGroup = computed(() => currentGroup.value?.pages.length > 1 ? currentGroup.value : null)
function openSection(name) { location.hash = whatsappRoute(name) }
function openGroup(group) {
  if (group.section) openSection(group.section)
  else view.value = group.pages[0].name
}
const user = window.frappe?.session?.user || document.getElementById('app')?.dataset.user || 'Account'
const userTitle = computed(() => linkedTitle('User', user, 'Account'))
const accountActions = computed(() => [
  { label: 'Your profile', icon: 'user', onClick: () => { profileOpen.value = true } },
  { label: `Theme: ${THEME_LABELS[theme.value][1]}`, icon: THEME_LABELS[theme.value][0], onClick: nextTheme },
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
// The account menu cycles the theme and keeps the profile in step.
function nextTheme() {
  cycleTheme()
  saveMyProfile({ theme: { system: 'System', light: 'Light', dark: 'Dark' }[theme.value] }).catch(() => {})
}
function openSetupFirst() { if (opensSetup(capabilities.value, initialPath)) view.value = 'Setup' }
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
onMounted(() => { startRealtime(); initialize().then(openSetupFirst); loadMyProfile(true).catch(() => {}); openLegacyConversation(location, coreApi); window.addEventListener('hashchange', () => { hash.value = location.hash }); window.addEventListener('keydown', focusSearch) })
onErrorCaptured(e => {
  if (/dynamically imported module|Loading chunk|Importing a module script/.test(String(e))) {
    loadError.value = 'This screen could not load. Refresh Relay to try again.'
    return false
  }
})
</script>
<template>
  <div class="app-shell relay-shell v1-shell" :class="{ 'has-section-sidebar': sidebarGroup && !isMobile }">
    <aside class="app-nav relay-rail" aria-label="Relay navigation">
      <span class="relay-rail-logo" aria-hidden="true">R</span>
      <nav class="relay-rail-items" aria-label="Relay sections">
        <template v-for="group in rail" :key="group.name">
          <button v-if="!group.bottom" type="button" class="rail-item" :class="{ active: currentGroup === group }" :title="group.name"
            :aria-label="group.name" :aria-current="currentGroup === group ? 'page' : undefined" @click="openGroup(group)">
            <FeatherIcon :name="group.icon" :size="18" /><span v-if="group.name === 'Inbox' && inboxBadge" class="rail-badge" :aria-label="`${inboxBadge} unread chats`">{{ inboxBadge }}</span>
          </button>
        </template>
      </nav>
      <div class="relay-rail-footer">
        <template v-for="group in rail" :key="group.name">
          <button v-if="group.bottom" type="button" class="rail-item" :class="{ active: currentGroup === group }" :title="group.name"
            :aria-label="group.name" :aria-current="currentGroup === group ? 'page' : undefined" @click="openGroup(group)">
            <FeatherIcon :name="group.icon" :size="18" />
          </button>
        </template>
        <Dropdown :options="accountActions" placement="right">
          <button type="button" class="rail-account" :title="userTitle" :aria-label="`Account: ${userTitle}`"><UserAvatar :user="user" :label="userTitle" size="sm" /></button>
        </Dropdown>
      </div>
    </aside>
    <SectionSidebar v-if="sidebarGroup" v-model:open="pagesOpen" :group="sidebarGroup" :view="view" :overlay="isMobile" @navigate="view = $event" />
    <header class="page-header v1-header" :inert="moreOpen || pagesOpen || undefined">
      <button v-if="sidebarGroup" type="button" class="section-toggle" :aria-label="`${sidebarGroup.name} pages`" :aria-expanded="pagesOpen" @click="pagesOpen = true"><FeatherIcon name="list" :size="18" /></button>
      <h1 :class="{ 'inbox-title': view === 'Messages' }">{{ current?.label }}</h1>
      <div class="ml-auto flex items-center gap-2"><div id="relay-header-actions" class="relay-header-actions" /><span class="v1-connection" :class="{ 'is-connected': realtimeStatus === 'Live' }" role="status"><span aria-hidden="true" />{{ realtimeStatus }}</span><NotificationInbox /><TicketNotices /></div>
    </header>
    <main class="workspace" :inert="moreOpen || pagesOpen || undefined">
      <p v-if="setupPending && ready" class="setup-pending" role="status">Relay is being set up. Ask your administrator to finish setup.</p>
      <div v-if="error || loadError" class="px-4 py-2"><ErrorMessage :message="error || loadError" /><Button v-if="!ready" label="Retry access check" @click="initialize" /><Button v-if="loadError" label="Refresh Relay" @click="location.reload()" /></div>
      <LoadingRows v-if="!ready && !error" label="Loading workspace…" :count="6" />
      <AccessDenied v-else-if="current && !navAllowed(current, capabilities)" :page="current" :capabilities="capabilities" />
      <component :is="views[view]" v-else-if="ready" v-bind="['Skills', 'Business events', 'Knowledge', 'Persona', 'Events'].includes(view) ? { kind: {Skills:'skills', 'Business events':'business_events', Knowledge:'knowledge', Persona:'persona', Events:'events'}[view] } : {}" />
    </main>
    <MobileTabBar v-if="isMobile && ready" v-model:open="moreOpen" :items="visible" :sections="sections" :view="view" :section="section" :badge="inboxBadge" @navigate="view = $event" @section="openSection">
      <template #footer>
        <a href="/desk/relay-core" class="mobile-sheet-item"><span class="mobile-sheet-icon"><FeatherIcon name="grid" :size="18" /></span><span>Frappe Desk</span></a>
        <div class="relay-account mobile-sheet-account">
          <button type="button" class="mobile-sheet-profile" data-profile-open @click="moreOpen = false; profileOpen = true"><UserAvatar :user="user" :label="userTitle" size="sm" /><span class="relay-user-name" :title="userTitle">{{ userTitle }}</span></button>
          <Button :icon="THEME_LABELS[theme][0]" :aria-label="`Theme: ${THEME_LABELS[theme][1]}`" :title="`Theme: ${THEME_LABELS[theme][1]}`" @click="nextTheme" /><Button icon="log-out" aria-label="Sign out" @click="logout" />
        </div>
      </template>
    </MobileTabBar>
    <ProfileDialog v-model="profileOpen" />
  </div>
</template>
