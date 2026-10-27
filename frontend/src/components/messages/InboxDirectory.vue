<script setup>
import { recordTitle } from '../../services/recordTitle'
import { linkedTitle } from '../../services/linkedTitle'
import { computed, inject, onMounted, ref, watch } from 'vue'
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
import NumberFilter from './NumberFilter.vue'
import InboxFolders from './InboxFolders.vue'
import MoveToFolderDialog from './MoveToFolderDialog.vue'
import { useChatFolders } from '../../composables/useChatFolders'
import { folderLabel } from '../../services/chatFolders'
import { assignmentLabel } from '../../services/assignment'
import { hasManyNumbers, numberName, whatsappNumbers } from '../../services/whatsappNumbers'
const props = defineProps({ selected: String, businessName: String, businessType: String, busy: Boolean })
const emit = defineEmits(['select', 'business', 'start'])
const isMobile = useMobileLayout()
const capabilities = inject('relayCapabilities')
const mediums = computed(() => mediumOptions(capabilities.value))
const chips = computed(() => mediumChips(capabilities.value))
const medium = ref(defaultMedium(capabilities.value))
// A site with two or more WhatsApp numbers can show one number's chats; rows then name their number.
const manyNumbers = computed(() => hasManyNumbers(capabilities.value))
const number = ref('')
const numberFilter = computed(() => medium.value === 'WhatsApp' && manyNumbers.value ? number.value : '')
const { counts } = useQueueCounts(medium, numberFilter)
const mode = ref('all'), folder = ref(''), query = ref(''), rows = ref([]), next = ref(null), loading = ref(false), error = ref('')
const moreQueues = computed(() => [
  { label: 'Businesses', onClick: () => { mode.value = 'business' } },
  ...(capabilities.value.manage ? [{ label: 'Unlinked senders', onClick: () => { location.hash = '/contacts?tab=unlinked' } }] : []),
])
const queues = computed(() => [['mine', 'Mine', 'Chats assigned to you'],
  ['unassigned', 'Unassigned', capabilities.value.teams_enabled ? 'Chats with no agent and no team' : 'Chats with no assigned agent'],
  ['all', 'All', 'All chats you can see'], ['unread', 'Unread', 'Chats with messages you have not read']])
let generation = 0, searchTimer
function directoryPage(cursor) {
  return coreApi('inbox.directory', { mode: mode.value, query: query.value, medium: medium.value === 'all' ? undefined : medium.value,
    channel: numberFilter.value || undefined, folder: folder.value || undefined, ...cursor })
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
watch(medium, () => { number.value = '' })
watch([mode, medium, numberFilter, folder], () => { ++generation; rows.value = []; next.value = null; load() })
onMounted(() => load())
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
useRealtimeRefresh(['Relay Message', 'Relay Conversation Assignment'], ['messages', 'inbox', 'incoming', 'reads', 'permissions', 'contacts'],
  ({ kinds } = {}) => mode.value !== 'business' && kinds && onlyChangedRows(kinds) ? refreshChanged() : load())
</script>
<template>
  <header class="inbox-list-head">
    <h2>Inbox</h2>
    <Dropdown :options="moreQueues"><Button icon="filter" variant="ghost" :aria-pressed="mode === 'business'" aria-label="More inbox views" title="More inbox views" /></Dropdown>
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
  <NumberFilter v-if="mode !== 'business' && medium === 'WhatsApp' && manyNumbers" v-model="number" :numbers="whatsappNumbers(capabilities)" />
  <nav class="v1-queues" aria-label="Inbox queues">
    <button v-for="[value, label, hint] in queues" :key="value" :title="hint" :aria-pressed="mode === value"
      :aria-label="countLabel(counts[value]) ? `${label}, ${counts[value]} conversations` : label" @click="mode = value">{{ label }}<span v-if="countLabel(counts[value])" class="queue-count" aria-hidden="true">{{ countLabel(counts[value]) }}</span></button>
    <Dropdown v-if="isMobile" :options="moreQueues"><Button label="More" icon-right="chevron-down" :aria-pressed="mode === 'business'" aria-label="More inbox views" /></Dropdown>
  </nav>
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
          <span class="directory-contact-context"><span v-if="capabilities.folders && row.folder && folderLabel(folders, row.folder)" class="directory-folder"><FeatherIcon name="folder" :size="12" />{{ folderLabel(folders, row.folder) }}</span><span v-if="row.business" class="directory-business" :title="linkedTitle(row.business.doctype, row.business.name)">{{ linkedTitle(row.business.doctype, row.business.name) }}</span><span class="directory-assignee"><FeatherIcon name="user" :size="12" />{{ assignmentLabel(row.assignment, { teams: capabilities.teams_enabled, title: linkedTitle }) }}</span></span>
        </span>
      </button>
      <WorkspaceState v-if="!loading && !rows.length && !error" compact :title="query ? 'No conversations found' : folder ? 'No conversations in this folder' : mode === 'unread' ? 'You’re all caught up' : 'No conversations yet'" :description="query ? 'Try a different name or clear your search.' : folder ? 'Use Move to folder on a conversation to file it here.' : 'Browse your businesses to start a conversation.'"><Button v-if="query" label="Clear search" @click="query = ''" /><Button v-else label="Browse businesses" @click="mode = 'business'" /></WorkspaceState>
      <Button v-if="next" class="directory-load-more" label="More conversations" :loading="loading" @click="load(next)" />
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
</style>
