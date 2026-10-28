<script setup>
import { useLoadMore } from '../../composables/useLoadMore'
import { recordTitle } from '../../services/recordTitle'
import { linkedTitle } from '../../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Avatar, Button, Dropdown, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
import { listTime } from '../relativeTime'
import LoadingRows from '../LoadingRows.vue'
import WorkspaceState from '../WorkspaceState.vue'
import BusinessDirectory from './BusinessDirectory.vue'
import { defaultMedium, mediumChips, mediumOptions } from '../../services/enabledChannels'
import { countLabel } from '../../services/queueCounts'
import { mergeChangedRows, newestActivity, onlyChangedRows } from '../../services/inboxRows'
import { useQueueCounts } from '../../composables/useQueueCounts'
import { useMobileLayout } from '../../composables/useMobileLayout'
import InboxFilterPanel from './InboxFilterPanel.vue'
import InboxFolders from './InboxFolders.vue'
import MoveToFolderDialog from './MoveToFolderDialog.vue'
import { useChatFolders } from '../../composables/useChatFolders'
import { folderLabel } from '../../services/chatFolders'
import { hasManyNumbers, numberName } from '../../services/whatsappNumbers'
import { TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, withoutFilter, withoutFilters } from '../../services/inboxFilters'
const props = defineProps({ selected: String, businessName: String, businessType: String, busy: Boolean })
const emit = defineEmits(['select', 'business', 'start'])
const isMobile = useMobileLayout()
const capabilities = inject('relayCapabilities')
const mediums = computed(() => mediumOptions(capabilities.value))
const chips = computed(() => mediumChips(capabilities.value))
const medium = ref(defaultMedium(capabilities.value))
// A site with two or more WhatsApp numbers names the number on each row.
const manyNumbers = computed(() => hasManyNumbers(capabilities.value))
// The tab and filters are kept per user in this browser.
const user = globalThis.frappe?.session?.user, storage = globalThis.localStorage
const filters = ref(loadFilters(storage, user))
const options = computed(() => channelOptions(capabilities.value, medium.value))
const params = computed(() => filterParams(filters.value, options.value))
const activeFilters = computed(() => filterChips(filters.value, options.value))
const { counts } = useQueueCounts(medium, params)
const mode = ref(filters.value.tab), folder = ref(''), query = ref(''), rows = ref([]), next = ref(null), loading = ref(false), error = ref('')
const filtersOpen = ref(false), filterButton = ref(null), mobileFilterButton = ref(null)
watch(mode, value => { if (value !== 'business') filters.value = { ...filters.value, tab: value } })
watch(filters, value => saveFilters(storage, user, value))
function browse(target) {
  if (target === 'business') mode.value = 'business'
  else location.hash = '/contacts?tab=unlinked'
}
let generation = 0, searchTimer
function directoryPage(cursor) {
  return coreApi('inbox.directory', { mode: mode.value, query: query.value, medium: medium.value === 'all' ? undefined : medium.value,
    ...params.value, folder: folder.value || undefined, ...cursor })
}
async function load(cursor = {}) {
  clearTimeout(searchTimer)
  if (mode.value === 'business') return
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
const { folders, changes, moved, move } = useChatFolders()
// A move changes only that row; a folder view or a deleted folder reloads the page.
watch(moved, value => {
  const row = value && rows.value.find(item => item.name === value.contact)
  if (row) row.folder = value.folder
})
watch(changes, () => { if (folder.value) load() })
watch(folders, list => { if (folder.value && !list.some(item => item.name === folder.value)) folder.value = '' })
const rowMenu = ref(), menuRow = ref(null), moving = ref(false)
const rowActions = computed(() => [
  { label: 'Move to folder', icon: 'folder-input', onClick: () => { moving.value = true } },
  ...(menuRow.value?.folder ? [{ label: 'Remove from folder', icon: 'folder-minus', onClick: () => move(menuRow.value.name, '').catch(e => { error.value = e.message }) }] : []),
])
// The row menu holds only folder actions, so it opens only while folders are on.
function openRowMenu(event, row) {
  if (!capabilities.value.folders) return
  event.preventDefault()
  menuRow.value = row
  rowMenu.value.toggle(event)
}
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
useRealtimeRefresh(['Relay Message'], ['messages', 'inbox', 'incoming', 'reads', 'permissions', 'contacts'],
  ({ kinds } = {}) => mode.value !== 'business' && kinds && onlyChangedRows(kinds) ? refreshChanged() : load())
</script>
<template>
  <header class="inbox-list-head">
    <h2>Inbox</h2>
    <span ref="filterButton" class="inbox-filter-trigger"><Button icon="filter" variant="ghost" :aria-pressed="activeFilters.length > 0 || mode === 'business'" :aria-expanded="filtersOpen" aria-label="Filter chats" title="Filter chats" @click="filtersOpen = !filtersOpen" /><span v-if="activeFilters.length" class="inbox-filter-count" aria-hidden="true">{{ activeFilters.length }}</span></span>
    <Button variant="solid" icon="plus" aria-label="New conversation" title="New conversation" @click="emit('start')" />
  </header>
  <form v-if="mode !== 'business'" class="directory-search inbox-filters" role="search" @submit.prevent="load()">
    <Teleport to="#relay-titlebar-search" :disabled="isMobile" defer>
      <TextInput v-model="query" type="search" aria-label="Search conversations" placeholder="Search conversations" maxlength="80"><template #prefix><FeatherIcon name="search" /></template><template v-if="!isMobile" #suffix><kbd>Ctrl K</kbd></template></TextInput>
    </Teleport>
  </form>
  <div v-if="mode !== 'business'" class="inbox-channel-chips" role="group" aria-label="Channel">
    <button v-for="chip in chips" :key="chip.value" type="button" class="inbox-channel-chip" :aria-pressed="medium === chip.value" :disabled="!chip.enabled" @click="medium = chip.value">
      <FeatherIcon v-if="chip.value === 'WhatsApp'" name="message-circle" :size="14" />{{ chip.label }}<span v-if="!chip.enabled" class="inbox-chip-soon">soon</span></button>
  </div>
  <nav class="v1-queues" aria-label="Inbox queues">
    <button v-for="[value, label, hint] in TABS" :key="value" :title="hint" :aria-pressed="mode === value"
      :aria-label="countLabel(counts[value]) ? `${label}, ${counts[value]} conversations` : label" @click="mode = value">{{ label }}<span v-if="countLabel(counts[value])" class="queue-count" aria-hidden="true">{{ countLabel(counts[value]) }}</span></button>
    <span v-if="isMobile" ref="mobileFilterButton" class="inbox-filter-trigger"><Button icon="filter" :aria-pressed="activeFilters.length > 0 || mode === 'business'" :aria-expanded="filtersOpen" aria-label="Filter chats" title="Filter chats" @click="filtersOpen = !filtersOpen" /><span v-if="activeFilters.length" class="inbox-filter-count" aria-hidden="true">{{ activeFilters.length }}</span></span>
  </nav>
  <div v-if="activeFilters.length && mode !== 'business'" class="inbox-filter-chips" role="group" aria-label="Active filters">
    <span v-for="item in activeFilters" :key="item.key" class="inbox-filter-chip">{{ item.label }}<button type="button" :aria-label="'Remove filter ' + item.label" @click="filters = withoutFilter(filters, item.key)"><FeatherIcon name="x" :size="12" /></button></span>
  </div>
  <InboxFilterPanel v-model="filters" v-model:open="filtersOpen" :anchor="isMobile ? mobileFilterButton : filterButton" :options="options" :manage="!!capabilities.manage" @browse="browse" />
  <InboxFolders v-if="capabilities.folders && mode !== 'business'" v-model="folder" />
  <BusinessDirectory v-if="mode === 'business'" :selected="businessName" :selected-doctype="businessType" :busy="busy" @select="(doctype, record) => emit('business', doctype, record)" />
  <template v-else>
    <div v-if="error" class="px-4 py-3"><ErrorMessage :message="error" /><Button label="Retry queue" @click="load()" /></div>
    <div class="directory-rows" :aria-busy="loading">
      <LoadingRows v-if="loading && !rows.length" label="Loading conversations…" />
      <button v-for="row in rows" :key="row.name" type="button" :aria-label="'Open conversation: ' + recordTitle(row, 'Contact')" class="directory-contact" :class="{ 'is-unread': row.unread }" :aria-pressed="selected === row.name" :disabled="busy" @click="emit('select', row.name)" @contextmenu="openRowMenu($event, row)">
        <span class="directory-avatar"><Avatar :label="recordTitle(row, 'Contact')" /><span class="directory-channel" :title="row.provider || 'Conversation'" :aria-label="row.provider || 'Conversation'"><FeatherIcon :name="row.provider === 'Email' ? 'mail' : row.provider === 'Telegram' ? 'send' : 'message-circle'" :size="11" /></span></span>
        <span class="directory-contact-copy">
          <span class="directory-contact-top"><strong>{{ recordTitle(row, 'Contact') }}</strong><time :title="row.latest_at" :datetime="row.latest_at">{{ listTime(row.latest_at) }}</time></span>
          <span class="directory-contact-bottom"><span v-if="manyNumbers && numberName(capabilities, row.channel)" class="number-tag">{{ numberName(capabilities, row.channel) }}</span><small>{{ row.latest_preview || 'No messages yet' }}</small><span v-if="row.unread" class="directory-unread" :aria-label="`${row.unread} unread messages`">{{ row.unread > 99 ? '99+' : row.unread }}</span></span>
          <span class="directory-contact-context"><span v-if="row.unlinked" class="number-tag">Unlinked</span><span v-if="capabilities.folders && row.folder && folderLabel(folders, row.folder)" class="directory-folder"><FeatherIcon name="folder" :size="12" />{{ folderLabel(folders, row.folder) }}</span><span v-if="row.business" class="directory-business" :title="linkedTitle(row.business.doctype, row.business.name)">{{ linkedTitle(row.business.doctype, row.business.name) }}</span></span>
        </span>
      </button>
      <WorkspaceState v-if="!loading && !rows.length && !error" compact :title="query || activeFilters.length ? 'No conversations found' : folder ? 'No conversations in this folder' : mode === 'unread' ? 'You’re all caught up' : 'No conversations yet'" :description="query ? 'Try a different name or clear your search.' : activeFilters.length ? 'No chat matches these filters.' : folder ? 'Use Move to folder on a conversation to file it here.' : 'Browse your businesses to start a conversation.'"><Button v-if="query" label="Clear search" @click="query = ''" /><Button v-else-if="activeFilters.length" label="Clear filters" @click="filters = withoutFilters(filters)" /><Button v-else label="Browse businesses" @click="mode = 'business'" /></WorkspaceState>
      <div v-if="next" ref="more" class="directory-load-more" role="status">{{ loading ? 'Loading more conversations…' : '' }}</div>
    </div>
    <template v-if="capabilities.folders">
      <Dropdown ref="rowMenu" :options="rowActions" />
      <MoveToFolderDialog v-model="moving" :contact="menuRow?.name" :current="menuRow?.folder" />
    </template>
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
.inbox-filter-chips { display:flex; flex-wrap:wrap; gap:6px; padding:8px 16px 0; }
.inbox-filter-chip { display:inline-flex; align-items:center; gap:4px; max-width:100%; min-height:24px; padding:0 4px 0 10px; border-radius:12px; background:var(--relay-accent-soft); color:var(--relay-accent-text); font-size:12px; overflow-wrap:anywhere; }
.inbox-filter-chip button { display:grid; place-items:center; width:20px; height:20px; border-radius:10px; }
.inbox-filter-chip button:hover { background:var(--relay-select); }
</style>
