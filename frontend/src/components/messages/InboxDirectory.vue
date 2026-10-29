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
import { countLabel } from '../../services/queueCounts'
import { mergeChangedRows, newestActivity, onlyChangedRows } from '../../services/inboxRows'
import { INBOX_ROWS, useQueueCounts } from '../../composables/useQueueCounts'
import { useMobileLayout } from '../../composables/useMobileLayout'
import InboxFilterPanel from './InboxFilterPanel.vue'
import InboxFolders from './InboxFolders.vue'
import InboxRowActions from './InboxRowActions.vue'
import { useChatFolders } from '../../composables/useChatFolders'
import { folderLabel } from '../../services/chatFolders'
import { hasManyNumbers, numberName } from '../../services/whatsappNumbers'
import { TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, withoutFilter, withoutFilters } from '../../services/inboxFilters'
const props = defineProps({ selected: String, businessName: String, businessType: String, busy: Boolean })
const emit = defineEmits(['select', 'business', 'start', 'navigate'])
const isMobile = useMobileLayout()
const capabilities = inject('relayCapabilities')
// Only switched-on channels get a chip, and only when there is more than one to choose.
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
const mode = ref(filters.value.tab), folder = ref(''), query = ref(''), rows = ref([]), next = ref(null), loading = ref(false), error = ref('')
const groupingView = computed(() => ['all', 'business'].includes(mode.value) && params.value.business_type !== 'none')
const filtersOpen = ref(false), filterButton = ref(null), mobileFilterButton = ref(null)
watch(mode, value => { if (value !== 'business') filters.value = { ...filters.value, tab: value } })
watch(filters, value => saveFilters(storage, user, value))
function browse() { mode.value = 'business' }
let generation = 0, searchTimer
function directoryPage(cursor) {
  return coreApi('inbox.directory', { rows: 'business', mode: mode.value, query: query.value, medium: medium.value === 'all' ? undefined : medium.value,
    ...params.value, folder: folder.value || undefined, ...cursor })
}
async function load(cursor = {}) {
  clearTimeout(searchTimer)
  if (groupingView.value) return
  const ticket = ++generation; loading.value = true; error.value = ''
  try {
    const page = await directoryPage(cursor)
    if (ticket === generation) { rows.value = cursor.after ? [...rows.value, ...page.items] : page.items; next.value = page.next }
  } catch (e) { if (ticket === generation) { error.value = e.message; rows.value = []; next.value = null } }
  finally { if (ticket === generation) loading.value = false }
}
watch(query, (_value, _previous, onCleanup) => {
  ++generation; clearTimeout(searchTimer); error.value = ''; rows.value = []; next.value = null; loading.value = true
  searchTimer = setTimeout(() => load(), 300)
  onCleanup(() => { ++generation; clearTimeout(searchTimer) })
})
watch([mode, medium, () => JSON.stringify(params.value), folder], () => { ++generation; rows.value = []; next.value = null; load() })
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
async function refreshChanged() {
  const since = newestActivity(rows.value)
  if (loading.value || error.value || !since) return load()
  const ticket = ++generation
  try {
    const page = await directoryPage({ since })
    if (ticket !== generation) return
    if (page.next) return load()
    rows.value = mergeChangedRows(rows.value, page.items)
  } catch { if (ticket === generation) return load() }
}
useRealtimeRefresh(['Relay Message'], ['messages', 'inbox', 'incoming', 'reads', 'chats', 'permissions', 'contacts'],
  ({ kinds } = {}) => !groupingView.value && kinds && onlyChangedRows(kinds) ? refreshChanged() : load())
</script>
<template>
  <header class="inbox-list-head">
    <h2>Chats</h2>
    <span ref="filterButton" class="inbox-filter-trigger"><Button icon="filter" variant="ghost" :aria-pressed="activeFilters.length > 0 || mode === 'business'" :aria-expanded="filtersOpen" aria-label="Filter chats" title="Filter chats" @click="filtersOpen = !filtersOpen" /><span v-if="activeFilters.length" class="inbox-filter-count" aria-hidden="true">{{ activeFilters.length }}</span></span>
    <Button variant="solid" icon="plus" aria-label="New chat" title="New chat" @click="emit('start')" />
  </header>
  <form v-if="!groupingView" class="directory-search inbox-filters" role="search" @submit.prevent="load()">
    <TextInput v-model="query" type="search" aria-label="Search conversations" placeholder="Search business, name or number" maxlength="80"><template #prefix><FeatherIcon name="search" /></template></TextInput>
  </form>
  <div v-if="manyMediums" class="inbox-channel-chips" role="group" aria-label="Channel">
    <button v-for="chip in chips" :key="chip.value" type="button" class="inbox-channel-chip" :aria-pressed="medium === chip.value" @click="medium = chip.value">
      <FeatherIcon v-if="chip.value === 'WhatsApp'" name="message-circle" :size="14" />{{ chip.label }}</button>
  </div>
  <nav class="v1-queues" aria-label="Inbox queues">
    <button v-for="[value, label, hint] in TABS" :key="value" :title="hint" :aria-pressed="mode === value"
      :aria-label="countLabel(counts[value]) ? `${label}, ${counts[value]} chats` : label" @click="mode = value">{{ label }}<span v-if="countLabel(counts[value])" class="queue-count" aria-hidden="true">{{ countLabel(counts[value]) }}</span></button>
    <span v-if="isMobile" ref="mobileFilterButton" class="inbox-filter-trigger"><Button icon="filter" :aria-pressed="activeFilters.length > 0 || mode === 'business'" :aria-expanded="filtersOpen" aria-label="Filter chats" title="Filter chats" @click="filtersOpen = !filtersOpen" /><span v-if="activeFilters.length" class="inbox-filter-count" aria-hidden="true">{{ activeFilters.length }}</span></span>
  </nav>
  <div v-if="activeFilters.length" class="inbox-filter-chips" role="group" aria-label="Active filters">
    <span v-for="item in activeFilters" :key="item.key" class="inbox-filter-chip">{{ item.label }}<button type="button" :aria-label="'Remove filter ' + item.label" @click="filters = withoutFilter(filters, item.key)"><FeatherIcon name="x" :size="12" /></button></span>
  </div>
  <InboxFilterPanel v-model="filters" v-model:open="filtersOpen" :anchor="isMobile ? mobileFilterButton : filterButton" :options="options" @browse="browse" />
  <InboxFolders v-if="capabilities.folders && !groupingView" v-model="folder" />
  <BusinessDirectory v-if="groupingView" :filters="{ ...params, medium: medium === 'all' ? undefined : medium }" :selected="businessName" :selected-doctype="businessType" :busy="busy" @navigate="emit('navigate')" @select="(doctype, record) => emit('business', doctype, record)" />
  <template v-else>
    <div v-if="error" class="px-4 py-3"><ErrorMessage :message="error" /><Button label="Retry" @click="load()" /></div>
    <div class="directory-rows" :aria-busy="loading">
      <LoadingRows v-if="loading && !rows.length" label="Loading chats…" />
      <div v-for="row in rows" :key="row.name" class="directory-row" @contextmenu="openRowMenu($event, row)" @pointerdown="pressStart($event, row)" @pointerup="pressEnd" @pointercancel="pressEnd">
        <button type="button" :aria-label="'Open chat: ' + rowTitle(row)" class="directory-contact" :class="{ 'is-unread': row.unread }"
          :aria-pressed="row.kind === 'business' ? businessType === row.doctype && businessName === row.record : selected === row.name" :disabled="busy" @click="openRow(row)">
          <span class="directory-avatar"><Avatar :label="rowTitle(row)" /><span v-if="manyMediums" class="directory-channel" :title="row.provider || 'Chat'" :aria-label="row.provider || 'Chat'"><FeatherIcon :name="row.provider === 'Email' ? 'mail' : row.provider === 'Telegram' ? 'send' : 'message-circle'" :size="11" /></span></span>
          <span class="directory-contact-copy">
            <span class="directory-contact-top"><strong>{{ rowTitle(row) }}</strong><FeatherIcon v-if="row.starred" name="star" :size="12" class="directory-star" aria-label="Starred" /><time :title="row.latest_at" :datetime="row.latest_at">{{ listTime(row.latest_at) }}</time></span>
            <span class="directory-contact-bottom"><span v-if="manyNumbers && numberName(capabilities, row.channel)" class="number-tag">{{ numberName(capabilities, row.channel) }}</span><small>{{ row.latest_preview || 'No messages yet' }}</small><span v-if="row.unread" class="directory-unread" :aria-label="`${row.unread} unread messages`">{{ row.unread > 99 ? '99+' : row.unread }}</span></span>
            <span v-if="(row.unlinked && !rowActions?.canLink(row)) || (capabilities.folders && row.folder && folderLabel(folders, row.folder))" class="directory-contact-context">
              <span v-if="row.unlinked && !rowActions?.canLink(row)" class="directory-unlinked">Not linked</span>
              <span v-if="capabilities.folders && row.folder && folderLabel(folders, row.folder)" class="directory-folder"><FeatherIcon name="folder" :size="12" />{{ folderLabel(folders, row.folder) }}</span>
            </span>
          </span>
        </button>
        <button v-if="rowActions?.canLink(row)" type="button" class="directory-link" :aria-label="'Link ' + rowTitle(row) + ' to a business record'" @click="rowActions.link(row)">Link</button>
        <button type="button" class="directory-row-menu" aria-label="Chat actions" title="Chat actions" @click="rowActions.open($event, $event.currentTarget, row)"><FeatherIcon name="more-horizontal" :size="16" /></button>
      </div>
      <WorkspaceState v-if="!loading && !rows.length && !error" compact :icon="mode === 'unread' ? 'check' : 'message-square'" :title="query || activeFilters.length ? 'No chats found' : folder ? 'No chats in this folder' : mode === 'unread' ? 'You’re all caught up' : mode === 'unlinked' ? 'Every chat is linked' : 'No chats yet'" :description="query ? 'Try a different name or number.' : activeFilters.length ? 'No chat matches these filters.' : folder ? 'Chats you move to this folder show here.' : mode === 'all' ? 'Press + to message a contact.' : ''"><Button v-if="query" label="Clear search" @click="query = ''" /><Button v-else-if="activeFilters.length" label="Clear filters" @click="filters = withoutFilters(filters)" /><Button v-else-if="mode === 'all' && !folder" label="New chat" variant="solid" @click="emit('start')" /></WorkspaceState>
      <div v-if="next" ref="more" class="directory-load-more" role="status">{{ loading ? 'Loading more chats…' : '' }}</div>
    </div>
    <InboxRowActions ref="rowActions" @changed="rowChanged" @error="message => error = message" />
  </template>
</template>

<style scoped>
.inbox-filters { align-items:center; }
.inbox-filters > .relay-input-shell { flex:1; width:0; }
.queue-count { margin-left:5px; color:var(--ink-gray-5); font-size:12px; font-weight:400; font-variant-numeric:tabular-nums; }
[aria-pressed=true] > .queue-count { color:inherit; font-weight:600; }
.directory-folder { display:inline-flex; align-items:center; gap:3px; margin-right:8px; color:var(--ink-gray-5); }
.inbox-filter-trigger { position:relative; display:inline-flex; }
.inbox-filter-count { position:absolute; top:-3px; right:-3px; min-width:16px; height:16px; padding:0 4px; border-radius:8px; background:var(--relay-accent); color:var(--relay-accent-ink); font-size:10.5px; font-weight:600; line-height:16px; text-align:center; pointer-events:none; }
.v1-queues > .inbox-filter-trigger { margin-left:auto; }
.directory-row { position:relative; }
/* Rows breathe: clear padding, a 4px gap between name and message, a bold name over a muted message. */
.directory-rows .directory-row > .directory-contact { min-height:70px; gap:12px; padding:12px 16px; border-bottom:1px solid var(--relay-stroke); }
.directory-rows .directory-row > .directory-contact .directory-contact-copy { display:flex; flex-direction:column; gap:4px; }
.directory-rows .directory-row > .directory-contact .directory-contact-top strong { font-size:14px; font-weight:600; color:var(--relay-ink); }
.directory-rows .directory-row > .directory-contact .directory-contact-bottom small { margin-top:0; font-size:13px; color:var(--relay-ink-3); }
.directory-unlinked { color:var(--ink-gray-6); }
.directory-star { flex:none; color:var(--ink-gray-6); fill:currentColor; }
.directory-link { position:absolute; bottom:14px; right:14px; height:20px; min-height:0; padding:0 8px; border:1px solid var(--relay-accent); border-radius:10px; color:var(--relay-accent-text); font-size:11.5px; font-weight:600; }
.directory-link:hover { background:var(--relay-accent-soft); }
.directory-row-menu { position:absolute; top:6px; right:6px; display:grid; place-items:center; width:28px; height:28px; border-radius:6px; background:var(--relay-layer-strong); color:var(--relay-ink-2); box-shadow:var(--relay-shadow-1); opacity:0; pointer-events:none; }
.directory-row:hover > .directory-row-menu, .directory-row-menu:focus-visible { opacity:1; pointer-events:auto; }
@media (hover:none) { .directory-row-menu { display:none; } }
@media (max-width:768px) { .directory-link { right:12px; height:44px; min-width:44px; bottom:4px; } .inbox-list-head :deep(button), .v1-queues button { min-height:44px; min-width:44px; } }
/* The Link button sits on the context line and the row menu takes the time's place, so neither covers text. */
.directory-row:has(.directory-link) :is(.directory-contact-bottom, .directory-contact-context) { padding-right:56px; }
@media (hover:hover) { .directory-row:hover .directory-contact-top time { visibility:hidden; } }
.inbox-filter-chips { display:flex; flex-wrap:wrap; gap:6px; padding:8px 16px 0; }
.inbox-filter-chip { display:inline-flex; align-items:center; gap:4px; max-width:100%; min-height:24px; padding:0 4px 0 10px; border-radius:12px; background:var(--relay-accent-soft); color:var(--relay-accent-text); font-size:12px; overflow-wrap:anywhere; }
.inbox-filter-chip button { display:grid; place-items:center; width:20px; height:20px; border-radius:10px; }
.inbox-filter-chip button:hover { background:var(--relay-select); }
</style>
