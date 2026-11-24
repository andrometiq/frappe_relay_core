<script setup>
import { useLoadMore } from '../../composables/useLoadMore'
import { recordTitle } from '../../services/recordTitle'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
import { listTime } from '../relativeTime'
import LoadingRows from '../LoadingRows.vue'
import WorkspaceState from '../WorkspaceState.vue'
import BusinessDirectory from './BusinessDirectory.vue'
import { defaultMedium, mediumChips } from '../../services/enabledChannels'
import { mergeChangedRows, mergeFirstPage, newestActivity } from '../../services/inboxRows'
import { heldRefresh, listRefresh } from '../../services/realtimeRefreshQueue'
import { INBOX_ROWS, useQueueCounts } from '../../composables/useQueueCounts'
import { useMobileLayout } from '../../composables/useMobileLayout'
import InboxFilterPanel from './InboxFilterPanel.vue'
import InboxFolders from './InboxFolders.vue'
import InboxSidebar from './InboxSidebar.vue'
import InboxRowActions from './InboxRowActions.vue'
import { useChatFolders } from '../../composables/useChatFolders'
import { folderColor, folderLabel } from '../../services/chatFolders'
import { hasManyNumbers, numberName } from '../../services/whatsappNumbers'
import { rowChannels, waitingLabel } from '../../services/conversationThreads'
import { TABS, VIEWS, channelOptions, filterChips, filterParams, listParams, loadFilters, saveFilters, withoutFilter, withoutFilters } from '../../services/inboxFilters'
const props = defineProps({ selected: String, businessName: String, businessType: String, busy: Boolean })
const emit = defineEmits(['select', 'business', 'start', 'navigate'])
const isMobile = useMobileLayout()
const capabilities = inject('relayCapabilities')
// Only switched-on channels are offered in the filter, and only when there is more than one to choose.
const chips = computed(() => mediumChips(capabilities.value).filter(chip => chip.enabled))
const manyMediums = computed(() => chips.value.length > 1)
const medium = ref(defaultMedium(capabilities.value))
// A site with two or more WhatsApp numbers names the number on each row.
const manyNumbers = computed(() => hasManyNumbers(capabilities.value))
// The tab and filters are kept per user in this browser.
const user = globalThis.frappe?.session?.user, storage = globalThis.localStorage
const filters = ref(loadFilters(storage, user))
const options = computed(() => channelOptions(capabilities.value, medium.value))
const params = computed(() => filterParams(filters.value, options.value))
const activeFilters = computed(() => filterChips(filters.value, options.value))
// Each readable business record is one row; chats that no readable record covers stay contact rows.
const { counts } = useQueueCounts(medium, computed(() => ({ ...params.value, ...INBOX_ROWS })))
const mode = ref(filters.value.tab), view = ref(filters.value.view || 'all'), folder = ref(''), query = ref(''), rows = ref([]), next = ref(null), loading = ref(false), error = ref('')
const requestParams = computed(() => listParams(filters.value, options.value, view.value))
// The sidebar's Numbers pick one WhatsApp number, the same filter as ticking it in the filter panel.
const numbers = computed(() => channelOptions(capabilities.value, 'WhatsApp'))
const channelFilter = computed({ get: () => filters.value.channels, set: channels => { filters.value = { ...filters.value, channels } } })
const viewsOpen = ref(false), folderDialogs = ref(null)
// Browsing by business type is its own view; every tab lists the chat rows, newest activity first.
const groupingView = computed(() => mode.value === 'business' && params.value.business_type !== 'none')
const filtersOpen = ref(false), filterButton = ref(null), mobileFilterButton = ref(null)
watch(mode, value => { if (value !== 'business') filters.value = { ...filters.value, tab: value } })
// Picking a view or folder leaves the record browser for the chat list.
watch([view, folder], ([value]) => {
  filters.value = { ...filters.value, view: value }
  if (mode.value === 'business') mode.value = filters.value.tab
})
watch(filters, value => saveFilters(storage, user, value))
function browse() { mode.value = 'business' }
let generation = 0, searchTimer
function directoryPage(cursor) {
  return coreApi('inbox.directory', { rows: 'business', mode: mode.value, query: query.value, medium: medium.value === 'all' ? undefined : medium.value,
    ...requestParams.value, folder: folder.value || undefined, ...cursor })
}
async function load(cursor = {}) {
  clearTimeout(searchTimer)
  if (groupingView.value) return
  const ticket = ++generation; loading.value = true; error.value = ''
  try {
    const page = await directoryPage(cursor)
    if (ticket === generation) { rows.value = cursor.after ? [...rows.value, ...page.items] : page.items; next.value = page.next }
  } catch (e) { if (ticket === generation) { error.value = e.message; rows.value = []; next.value = null } }
  finally { if (ticket === generation) { loading.value = false; live.release() } }
}
watch(query, (_value, _previous, onCleanup) => {
  ++generation; clearTimeout(searchTimer); error.value = ''; rows.value = []; next.value = null; loading.value = true
  searchTimer = setTimeout(() => load(), 300)
  onCleanup(() => { ++generation; clearTimeout(searchTimer) })
})
watch([mode, medium, () => JSON.stringify(requestParams.value), folder], () => { ++generation; rows.value = []; next.value = null; load() })
onMounted(() => load())
const more = useLoadMore({ loading, hasMore: next, error, load: () => load(next.value) })
const { folders, changes, moved } = useChatFolders()
// A move changes only that row; a folder view or a deleted folder reloads the page.
watch(moved, value => {
  const row = value && rows.value.find(item => item.name === value.contact)
  if (row) row.folder = value.folder
})
watch(changes, () => { if (folder.value) load() })
watch(folders, list => { if (folder.value && !list.some(item => item.name === folder.value)) folder.value = '' })
// A chat with no saved name shows its number; the number is the Frappe Contact name for such chats.
const listTitle = computed(() => folder.value ? folderLabel(folders.value, folder.value) || 'Folder' : VIEWS.find(([value]) => value === view.value)?.[1] || 'All chats')
const channelCount = computed(() => (capabilities.value.inbox_channels || []).length)
const subtitle = computed(() => channelCount.value ? `${channelCount.value} ${channelCount.value === 1 ? 'channel' : 'channels'}` : '')
const rowTitle = row => recordTitle(row.kind === 'business' ? row : { display_name: row.display_name || row.contact }, 'Unknown number')
const rowActions = ref()
function openRowMenu(event, row) {
  event.preventDefault()
  rowActions.value.open(event, event.currentTarget, row)
}
// Touch has no hover, so a long press opens the row menu; the click that ends the press does not open the chat.
let pressTimer, pressed = false
function pressStart(event, row) {
  pressed = false
  if (event.pointerType !== 'touch') return
  const target = event.currentTarget
  pressTimer = setTimeout(() => { pressed = true; rowActions.value.open(event, target, row) }, 500)
}
function pressEnd() { clearTimeout(pressTimer) }
function openRow(row) {
  if (pressed) { pressed = false; return }
  if (row.kind === 'business') emit('business', row.doctype, { name: row.record, label: row.title })
  else emit('select', row.name)
}
function rowChanged(row, values) { Object.assign(row, values) }
// A new message updates only the conversations active since the newest loaded row; other changes reload the page.
async function refreshChanged(kinds) {
  const since = newestActivity(rows.value)
  if (error.value || !since) return load()
  const ticket = ++generation
  try {
    const page = await directoryPage({ since })
    if (ticket !== generation) return live.hold(kinds)
    if (page.next) return load()
    rows.value = mergeChangedRows(rows.value, page.items)
  } catch { if (ticket === generation) return load() }
}
// A read state change re-reads the first page in place, so the list keeps its rows and scroll.
async function refreshFirstPage(kinds) {
  if (error.value || !rows.value.length) return load()
  const ticket = ++generation
  try {
    const page = await directoryPage({})
    if (ticket === generation) rows.value = mergeFirstPage(rows.value, page)
    else live.hold(kinds)
  } catch { if (ticket === generation) return load() }
}
// Receipts change no row; new messages alone fetch only the changed rows.
function refresh({ kinds } = {}) {
  const kind = listRefresh(kinds)
  if (groupingView.value || kind === 'none') return
  if (kind === 'reload') return load()
  return kind === 'loaded' && !kinds.has('reads') && !kinds.has('chats') ? refreshChanged(kinds) : refreshFirstPage(kinds)
}
const live = heldRefresh(() => loading.value, refresh)
useRealtimeRefresh(['Relay Message'], ['messages', 'receipts', 'inbox', 'reads', 'chats', 'permissions', 'contacts'], live.refresh)
</script>
<template>
  <InboxSidebar v-model:view="view" v-model:folder="folder" v-model:channels="channelFilter" v-model:query="query" v-model:open="viewsOpen" :counts="counts" :folders="folders"
    :numbers="numbers" :can-folders="!!capabilities.folders" :subtitle="subtitle" @start="emit('start')" @edit-folder="folderDialogs?.openEditor($event)" @delete-folder="folderDialogs?.confirmRemove($event)" />
  <InboxFolders v-if="capabilities.folders" ref="folderDialogs" v-model="folder" />
  <div class="inbox-list">
    <header class="inbox-list-head">
      <h2>{{ listTitle }}</h2>
      <span ref="filterButton" class="inbox-filter-trigger"><Button icon="filter" variant="ghost" :aria-pressed="activeFilters.length > 0 || mode === 'business'" :aria-expanded="filtersOpen" aria-label="Filter chats" title="Filter chats" @click="filtersOpen = !filtersOpen" /><span v-if="activeFilters.length" class="inbox-filter-count" aria-hidden="true">{{ activeFilters.length }}</span></span>
      <Button variant="solid" icon-left="plus" label="New" aria-label="New chat" title="New chat" @click="emit('start')" />
    </header>
    <Teleport v-if="isMobile && !selected && !businessName" to="#relay-header-actions" defer>
      <span ref="mobileFilterButton" class="inbox-filter-trigger"><Button icon="filter" variant="ghost" class="relay-header-icon hit-zone" :aria-pressed="activeFilters.length > 0 || mode === 'business'" :aria-expanded="filtersOpen" aria-label="Filter chats" title="Filter chats" @click="filtersOpen = !filtersOpen" /><span v-if="activeFilters.length" class="inbox-filter-count" aria-hidden="true">{{ activeFilters.length }}</span></span>
      <Button icon="plus" variant="ghost" class="relay-header-icon relay-header-new hit-zone" aria-label="New chat" title="New chat" @click="emit('start')" />
    </Teleport>
    <form v-if="isMobile && !groupingView" class="directory-search inbox-filters" role="search" @submit.prevent="load()">
      <TextInput v-model="query" type="search" aria-label="Search chats" placeholder="Search chats, contacts" maxlength="80"><template #prefix><FeatherIcon name="search" :size="16" /></template></TextInput>
    </form>
    <nav class="inbox-tabs" aria-label="Inbox queues">
      <button v-if="isMobile" type="button" class="inbox-view-picker hit-zone" aria-haspopup="dialog" :aria-expanded="viewsOpen" @click="viewsOpen = true">
        <span>{{ listTitle }}</span><FeatherIcon name="chevron-down" :size="14" /></button>
      <button v-for="[value, label, hint] in TABS" :key="value" type="button" class="inbox-tab hit-zone" :title="hint" :aria-pressed="mode === value" @click="mode = value">{{ label }}</button>
    </nav>
    <div v-if="activeFilters.length" class="inbox-filter-chips" role="group" aria-label="Active filters">
      <span v-for="item in activeFilters" :key="item.key" class="inbox-filter-chip">{{ item.label }}<button type="button" :aria-label="'Remove filter ' + item.label" @click="filters = withoutFilter(filters, item.key)"><FeatherIcon name="x" :size="12" /></button></span>
    </div>
    <InboxFilterPanel v-model="filters" v-model:open="filtersOpen" v-model:medium="medium" :mediums="manyMediums ? chips : []" :anchor="isMobile ? mobileFilterButton : filterButton" :options="options" @browse="browse" />
    <BusinessDirectory v-if="groupingView" :filters="{ ...params, medium: medium === 'all' ? undefined : medium }" :selected="businessName" :selected-doctype="businessType" :busy="busy" @navigate="emit('navigate')" @select="(doctype, record) => emit('business', doctype, record)" @chat="name => emit('select', name)" />
    <template v-else>
      <div v-if="error" class="px-4 py-3"><ErrorMessage :message="error" /><Button label="Retry" @click="load()" /></div>
      <div class="directory-rows" :aria-busy="loading">
        <LoadingRows v-if="loading && !rows.length" label="Loading chats…" />
        <TransitionGroup name="inbox-row">
        <div v-for="row in rows" :key="row.name" class="directory-row" @contextmenu="openRowMenu($event, row)" @pointerdown="pressStart($event, row)" @pointerup="pressEnd" @pointercancel="pressEnd">
          <button type="button" :aria-label="'Open chat: ' + rowTitle(row)" class="directory-contact" :class="{ 'is-unread': row.unread }"
            :aria-pressed="row.kind === 'business' ? businessType === row.doctype && businessName === row.record : selected === row.name" :disabled="busy" @click="openRow(row)">
            <span class="directory-avatar"><Avatar :label="rowTitle(row)" /></span>
            <span class="directory-contact-copy">
              <span class="directory-contact-top"><strong>{{ rowTitle(row) }}</strong><FeatherIcon v-if="row.starred" name="star" :size="12" class="directory-star" aria-label="Starred" /><time :title="row.latest_at" :datetime="row.latest_at">{{ listTime(row.latest_at) }}</time></span>
              <span class="directory-contact-bottom"><span v-if="manyNumbers && !row.threads?.length && numberName(capabilities, row.channel)" class="number-tag">{{ numberName(capabilities, row.channel) }}</span><small>{{ row.latest_preview || 'No messages yet' }}</small></span>
              <span class="directory-row-channels">
                <span v-for="mark in rowChannels(row)" :key="mark.channel + mark.endpoint" class="row-channel" :class="{ 'is-unread': mark.unread }" :data-provider="mark.provider" :title="mark.label" role="img" :aria-label="mark.label"><FeatherIcon :name="mark.icon" :size="12" /></span>
                <span v-if="capabilities.folders && row.folder && folderLabel(folders, row.folder)" class="row-badge is-folder"><span class="row-folder-dot" :style="{ background: folderColor(row.folder) }" aria-hidden="true" />{{ folderLabel(folders, row.folder) }}</span>
                <span v-if="row.unlinked && !rowActions?.canLink(row)" class="row-badge directory-unlinked">Not linked</span>
                <span v-if="row.open_tickets" class="row-badge is-ticket">{{ row.open_tickets > 1 ? row.open_tickets + ' tickets' : 'Ticket' }}</span>
                <span v-if="waitingLabel(row)" class="row-badge is-waiting">{{ waitingLabel(row) }}</span>
                <span v-if="row.unread" class="directory-unread" :aria-label="`${row.unread} unread messages`">{{ row.unread > 99 ? '99+' : row.unread }}</span>
              </span>
            </span>
          </button>
          <button v-if="rowActions?.canLink(row)" type="button" class="directory-link" :aria-label="'Link ' + rowTitle(row) + ' to a business record'" @click="rowActions.link(row)">Link</button>
          <button type="button" class="directory-row-menu" aria-label="Chat actions" title="Chat actions" @click="rowActions.open($event, $event.currentTarget, row)"><FeatherIcon name="more-horizontal" :size="16" /></button>
        </div>
        </TransitionGroup>
        <WorkspaceState v-if="!loading && !rows.length && !error" compact :icon="mode === 'unread' ? 'check' : 'message-square'" :title="query || activeFilters.length ? 'No chats found' : folder ? 'No chats in this folder' : view === 'unlinked' ? 'Every chat is linked' : view === 'mine' ? 'No chats assigned to you' : view === 'starred' ? 'No starred chats' : mode === 'unread' ? 'You’re all caught up' : 'No chats yet'" :description="query ? 'Try a different name or number.' : activeFilters.length ? 'No chat matches these filters.' : folder ? 'Chats you move to this folder show here.' : view === 'starred' ? 'Star a chat from its menu to keep it here.' : mode === 'all' && view === 'all' ? 'Press New to message a contact.' : ''"><Button v-if="query" label="Clear search" @click="query = ''" /><Button v-else-if="activeFilters.length" label="Clear filters" @click="filters = withoutFilters(filters)" /><Button v-else-if="mode === 'all' && view === 'all' && !folder" label="New chat" variant="solid" @click="emit('start')" /></WorkspaceState>
        <div v-if="next" ref="more" class="directory-load-more" role="status">{{ loading ? 'Loading more chats…' : '' }}</div>
      </div>
      <InboxRowActions ref="rowActions" @changed="rowChanged" @error="message => error = message" />
    </template>
  </div>
</template>

<style scoped>
.inbox-list { display:flex; flex:1; flex-direction:column; min-width:0; min-height:0; }
.inbox-list-head { display:flex; flex:none; align-items:center; gap:8px; height:52px; padding:0 14px; border-bottom:1px solid var(--relay-stroke); }
.inbox-list-head h2 { flex:1; min-width:0; overflow:hidden; color:var(--relay-ink); font-size:15px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }
.inbox-list-head .relay-button--ghost { width:30px; min-width:30px; min-height:30px; height:30px; padding:0; color:var(--relay-ink-3); }
.inbox-list-head .relay-button--solid { min-height:30px; height:30px; padding:0 10px; }
.inbox-tabs { display:flex; flex:none; align-items:center; gap:4px; padding:8px 12px; border-bottom:1px solid var(--relay-stroke); }
.inbox-tab { height:24px; padding:0 10px; border-radius:999px; color:var(--relay-ink-3); font-size:12.5px; font-weight:500; white-space:nowrap; }
.inbox-tab:hover { color:var(--relay-ink); background:var(--relay-hover); }
.inbox-tab[aria-pressed=true] { background:var(--relay-ink); color:var(--relay-layer); }
.inbox-tab:focus-visible, .inbox-view-picker:focus-visible { outline:2px solid var(--relay-accent); outline-offset:1px; }
.inbox-view-picker { display:inline-flex; align-items:center; gap:4px; min-width:0; max-width:46%; height:24px; margin-right:auto; padding:0 2px; color:var(--relay-ink); font-size:14px; font-weight:600; }
.inbox-view-picker > span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.inbox-filter-trigger { position:relative; display:inline-flex; }
.inbox-filter-count { position:absolute; top:-3px; right:-3px; min-width:16px; height:16px; padding:0 4px; border-radius:8px; background:var(--relay-accent); color:var(--relay-accent-ink); font-size:10.5px; font-weight:600; line-height:16px; text-align:center; pointer-events:none; }
.directory-rows { flex:1; min-height:0; overflow:auto; }
.directory-row { position:relative; }
/* Rows follow the approved mockup: 36px avatar, 13.5px name, 13px preview, one line of 18px channel marks and badges. */
.directory-rows .directory-row > .directory-contact { position:relative; display:flex; align-items:flex-start; gap:10px; width:100%; min-height:0; margin:0; padding:11px 14px; border:0; border-bottom:1px solid var(--relay-stroke); border-radius:0; background:transparent; box-shadow:none; text-align:left; }
.directory-rows .directory-row > .directory-contact:hover { background:var(--relay-hover); }
.directory-rows .directory-row > .directory-contact[aria-pressed=true] { background:var(--relay-accent-soft); box-shadow:none; }
.directory-rows .directory-row > .directory-contact[aria-pressed=true]::before { content:none; }
.directory-avatar { flex:none; }
.directory-avatar :deep(.relay-avatar) { width:36px; height:36px; border:0; font-size:13px; }
.directory-contact-copy { display:flex; flex:1; flex-direction:column; min-width:0; }
.directory-contact-top { display:flex; align-items:center; gap:6px; min-width:0; }
.directory-contact-top strong { min-width:0; overflow:hidden; color:var(--relay-ink); font-size:13.5px; font-weight:600; line-height:20px; text-overflow:ellipsis; white-space:nowrap; }
.directory-contact-top time { flex:none; margin-left:auto; color:var(--relay-ink-soft); font-size:11.5px; }
.directory-contact-bottom { display:flex; align-items:center; gap:6px; min-width:0; margin-top:2px; }
.directory-contact-bottom small { flex:1; min-width:0; margin:0; overflow:hidden; color:var(--relay-ink-3); font-size:13px; line-height:18px; text-overflow:ellipsis; white-space:nowrap; }
.directory-contact.is-unread .directory-contact-bottom small { color:var(--relay-ink); font-weight:500; }
.directory-star { flex:none; color:var(--relay-ink-3); fill:currentColor; }
.directory-row-channels { display:flex; align-items:center; gap:5px; min-width:0; min-height:18px; margin-top:6px; }
.row-channel { position:relative; display:grid; flex:none; place-items:center; width:18px; height:18px; border-radius:4px; background:var(--relay-hover); color:var(--relay-ink-3); }
.row-channel :deep(svg) { width:11px; height:11px; }
.row-channel[data-provider="WhatsApp"] { color:var(--relay-whatsapp); }
.row-channel[data-provider="Telegram"] { color:var(--relay-telegram); }
.row-channel[data-provider="Email"] { color:var(--relay-email); }
/* The channel holding the unread message carries a blue ring and dot. */
.row-channel.is-unread { background:var(--relay-accent-soft); box-shadow:inset 0 0 0 1px var(--relay-accent); }
.row-channel.is-unread::after { content:""; position:absolute; top:-3px; right:-3px; width:7px; height:7px; border:1.5px solid var(--relay-layer); border-radius:50%; background:var(--relay-accent); }
.row-badge { display:inline-flex; flex:none; align-items:center; gap:4px; max-width:120px; height:18px; padding:0 7px; overflow:hidden; border-radius:4px; background:var(--relay-hover); color:var(--relay-ink-3); font-size:11px; font-weight:500; text-overflow:ellipsis; white-space:nowrap; }
.directory-row-channels > .row-badge:not(.is-folder,.directory-unlinked), .directory-row-channels > .directory-unread { margin-left:auto; }
.directory-row-channels > .row-badge:not(.is-folder,.directory-unlinked) ~ :is(.row-badge,.directory-unread) { margin-left:0; }
.row-badge.is-ticket { background:var(--relay-warning-bg); color:var(--relay-warning-ink); }
.row-badge.is-waiting { background:var(--relay-note-bg); color:var(--relay-note-ink); }
.row-folder-dot { flex:none; width:6px; height:6px; border-radius:2px; }
.directory-unread { display:grid; flex:none; place-items:center; min-width:18px; height:18px; padding:0 5px; border-radius:9px; background:var(--relay-accent); color:var(--relay-accent-ink); font-size:11px; font-weight:600; }
/* Link is a small pill on the last line, like the row badges; an invisible frame keeps a 44px tap target on phones. */
.directory-link { position:absolute; right:14px; bottom:11px; display:inline-flex; align-items:center; height:18px; min-height:0; padding:0 8px; border-radius:4px; background:var(--relay-accent-soft); color:var(--relay-accent-text); font-size:11px; font-weight:600; }
.directory-link:hover { box-shadow:inset 0 0 0 1px var(--relay-accent); }
.directory-link:focus-visible { outline:2px solid var(--relay-accent); outline-offset:1px; }
.directory-row:has(.directory-link) .directory-row-channels { padding-right:48px; }
.directory-row-menu { position:absolute; top:8px; right:8px; display:grid; place-items:center; width:26px; height:26px; border-radius:6px; background:var(--relay-layer); color:var(--relay-ink-2); box-shadow:var(--relay-shadow-1); opacity:0; pointer-events:none; }
.directory-row:hover > .directory-row-menu, .directory-row-menu:focus-visible { opacity:1; pointer-events:auto; }
@media (hover:hover) { .directory-row:hover .directory-contact-top time { visibility:hidden; } }
@media (hover:none) { .directory-row-menu { display:none; } }
/* Phones: the same rows a little tighter, with a 40px avatar. */
@media (max-width:768px) {
  .inbox-list-head { display:none; }
  .inbox-tabs { gap:2px; padding:6px 12px 8px; border-bottom:0; }
  .inbox-tab { height:26px; }
  /* About 72px a row: 8px padding, name, preview and a 16px line of marks. */
  .directory-rows .directory-row > .directory-contact { gap:12px; padding:8px 16px; }
  .directory-avatar { margin-top:2px; }
  .directory-avatar :deep(.relay-avatar) { width:40px; height:40px; font-size:14px; }
  .directory-contact-top strong { font-size:14.5px; }
  .directory-contact-bottom { margin-top:1px; }
  .directory-contact-bottom small { font-size:13.5px; }
  .directory-row-channels { gap:4px; min-height:16px; margin-top:3px; }
  .row-channel { width:16px; height:16px; }
  .row-channel :deep(svg) { width:10px; height:10px; }
  .row-badge { height:16px; padding:0 6px; font-size:10.5px; }
  .directory-unread { min-width:16px; height:16px; font-size:10.5px; }
  .directory-link { right:16px; bottom:8px; height:16px; font-size:10.5px; }
  .directory-link::before { content:""; position:absolute; inset:-14px -6px; }
}
/* A row with a new message moves to the top; the others slide to make room. */
.inbox-row-move { transition:transform var(--relay-normal) var(--relay-ease); }
.inbox-row-enter-active { transition:opacity var(--relay-normal) var(--relay-ease), transform var(--relay-normal) var(--relay-ease); }
.inbox-row-enter-from { opacity:0; transform:translateY(-8px); }
.inbox-row-leave-active { display:none; }
@media (prefers-reduced-motion:reduce) { .inbox-row-move, .inbox-row-enter-active { transition:none; } }
.inbox-filter-chips { display:flex; flex-wrap:wrap; gap:6px; padding:8px 12px 0; }
.inbox-filter-chip { display:inline-flex; align-items:center; gap:4px; max-width:100%; min-height:22px; padding:0 4px 0 9px; border-radius:11px; background:var(--relay-accent-soft); color:var(--relay-accent-text); font-size:12px; overflow-wrap:anywhere; }
.inbox-filter-chip button { display:grid; place-items:center; width:20px; height:20px; border-radius:10px; }
.inbox-filter-chip button:hover { background:var(--relay-select); }
</style>
