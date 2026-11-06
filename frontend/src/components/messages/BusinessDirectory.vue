<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { appendTiles, browseCrumbs, chatTile, browseRoute, enterBrowse, levelLabel, mergeTiles, moveSentTile, readBrowse, searchLabel, sentTile, tileCount, tileKey, tileUnread } from '../../services/businessBrowse'
import { useDebouncedSearch } from '../../composables/useDebouncedSearch'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
import { chatListRefresh, heldRefresh } from '../../services/realtimeRefreshQueue'
import { lastOwnSend, ownSendOf } from '../../services/ownSends'
import { useLoadMore } from '../../composables/useLoadMore'
import { listTime } from '../relativeTime'
import LoadingRows from '../LoadingRows.vue'

const props = defineProps({ selected: String, selectedDoctype: String, busy: Boolean, contacts: Boolean, filters: Object })
const emit = defineEmits(['select', 'contact', 'chat', 'navigate'])
const base = props.contacts ? '#/contacts' : '#/messages'
const state = ref(readBrowse(location.hash)), query = ref(state.value.query), items = ref([]), fields = ref([])
const loading = ref(false), error = ref(''), next = ref(null), heading = ref(null)
// Search filters the shown level; contacts are searched only inside a record and in Not linked.
const people = computed(() => props.contacts && !!(state.value.record || state.value.unlinked))
const crumbs = computed(() => browseCrumbs(state.value, fields.value))
// Chats All counts the chats that no business record covers, so its root lists them below the type tiles.
const rootChats = computed(() => !props.contacts && !state.value.doctype && !props.filters?.business_type && !props.filters?.business_name)
let sequence = 0
// Live events of one send arrive over a few hundred milliseconds; they are answered together.
const LIVE_DELAY = 300
async function chatPage(after) {
  const page = await coreApi('inbox.directory', { rows: 'business', mode: 'unlinked', query: query.value, ...props.filters, ...(after ? { after } : {}) })
  return { items: page.items.map(chatTile), next: page.next?.after ?? null }
}
function levelPage(append) {
  return people.value
    ? coreApi('api.contact_directory', { query: query.value, after: append ? next.value : null,
      business_type: state.value.doctype || null, business_name: state.value.record || null, unlinked: state.value.unlinked ? 1 : 0 })
    : coreApi('business_groups.browse', { doctype: state.value.doctype || null,
      path: JSON.stringify(state.value.path), path_fields: JSON.stringify(state.value.pathFields), query: query.value,
      start: append ? next.value : 0, contacts: props.contacts ? 1 : 0, ...props.filters })
}
async function load(append = false) {
  const request = ++sequence
  loading.value = true; error.value = ''
  if (!append) { items.value = []; next.value = null }
  try {
    if (rootChats.value && append) {
      const chats = await chatPage(next.value)
      if (request !== sequence) return
      items.value = appendTiles(items.value, chats.items); next.value = chats.next
      return
    }
    const page = await levelPage(append)
    if (request !== sequence) return
    if (page.path && JSON.stringify(page.path) !== JSON.stringify(state.value.path)) {
      // The grouping changed since this URL was saved: show the type level the server answered.
      state.value = { ...state.value, path: page.path, pathFields: page.path_fields, record: '', recordLabel: '' }
      return window.history.replaceState(window.history.state, '', browseRoute(base, { ...state.value, query: query.value }))
    }
    const chats = rootChats.value ? await chatPage(null) : null
    if (request !== sequence) return
    const rows = people.value ? page.items.map(row => ({ ...row, kind: 'contact', label: row.full_name || row.name })) : page.items
    items.value = append ? appendTiles(items.value, rows) : chats ? [...rows, ...chats.items] : rows
    if (!people.value) fields.value = page.fields || []
    next.value = chats ? chats.next : page.next
  } catch (e) { if (request === sequence) error.value = e.message }
  finally { if (request === sequence) { loading.value = false; live.release() } }
}
const moreSentinel = useLoadMore({ loading, hasMore: () => next.value != null, error, load: () => load(true) })
const search = useDebouncedSearch(query, () => load(), () => { ++sequence; items.value = []; next.value = null; loading.value = true })
let changingLevel = false
function saveSearch() {
  if (changingLevel) return
  const params = new URLSearchParams(location.hash.split('?')[1] || '')
  if (params.has('business_name') || params.has('contact') || params.has('message')) return
  window.history.replaceState(window.history.state, '', browseRoute(base, { ...state.value, query: query.value }))
}
watch(query, saveSearch, { flush: 'sync' })
function navigate(value) {
  saveSearch()
  changingLevel = true
  query.value = ''; state.value = { ...value, query: '' }
  changingLevel = false
  const route = browseRoute(base, state.value)
  if (location.hash !== route) window.history.pushState({ relayList: true }, '', route)
  emit('navigate')
  nextTick(() => heading.value?.focus())
}
function choose(tile) {
  saveSearch()
  if (tile.kind === 'contact') return emit('contact', tile.name)
  if (tile.kind === 'chat') return emit('chat', tile.name)
  if (tile.kind === 'record' && !props.contacts) return emit('select', state.value.doctype, tile)
  navigate(enterBrowse(state.value, tile))
}
function readRoute() {
  if (location.hash.split('?')[0] !== base) return
  const params = new URLSearchParams(location.hash.split('?')[1] || '')
  // Opening a thread keeps this browser at its parent until Back returns here.
  if (params.has('business_name') || params.has('contact') || params.has('message')) return
  state.value = readBrowse(location.hash); query.value = state.value.query; emit('navigate')
}
watch(state, () => load())
watch(() => JSON.stringify(props.filters), () => navigate({ ...readBrowse(base), query: '' }))
onMounted(() => { load(); window.addEventListener('popstate', readRoute); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => { ++sequence; window.removeEventListener('popstate', readRoute); window.removeEventListener('hashchange', readRoute) })
// A message elsewhere re-reads the first page and updates the shown tiles in place: no reload, and scroll and loaded pages stay.
async function refreshLoaded(batch) {
  if (error.value || !items.value.length) return load()
  const request = sequence
  try {
    const page = await levelPage(false)
    const chats = rootChats.value ? await chatPage(null) : null
    if (request !== sequence) return live.hold(batch?.kinds)
    if (page.path && JSON.stringify(page.path) !== JSON.stringify(state.value.path)) return load()
    items.value = mergeTiles(items.value, [...page.items, ...(chats?.items || [])])
  } catch { if (request === sequence) return load() }
}
// Reading the open record sends `reads` and, when its shared unread count drops, `chats`; only that tile is fetched again.
async function refreshSelected(batch) {
  const request = sequence
  const tile = items.value.find(row => row.kind === 'record' && row.doctype === props.selectedDoctype && row.name === props.selected)
  if (!tile) return refreshLoaded(batch)
  const page = await coreApi('business_groups.browse', { doctype: state.value.doctype, path: JSON.stringify(state.value.path),
    path_fields: JSON.stringify(state.value.pathFields), query: query.value, start: 0, contacts: 0, ...props.filters, business_type: tile.doctype, business_name: tile.name })
  const row = page.items.find(item => tileKey(item) === tileKey(tile))
  if (request === sequence && row) Object.assign(tile, row)
}
// A send from this browser moves its tile here at once and reads nothing; its live events then read nothing either.
watch(lastOwnSend, sent => {
  const tile = !props.contacts && sentTile(items.value, sent)
  if (tile) items.value = moveSentTile(items.value, tile, sent)
})
// Live events of the open conversation change one tile; a change elsewhere reads the first page once per burst.
function liveRefresh(batch) {
  let kind = chatListRefresh(batch, name => !!ownSendOf(name))
  if (kind === 'own' && ![...batch.messages].every(name => sentTile(items.value, ownSendOf(name)))) kind = 'loaded'
  if (props.contacts && !['none', 'own'].includes(kind)) kind = 'reload'
  return refreshes[kind](batch)
}
const refreshes = { none: () => {}, own: () => {}, selected: refreshSelected, loaded: refreshLoaded, reload: () => load() }
// Hub event changes ('incoming') are not chat changes: a status callback of a send would read the page again.
const live = heldRefresh(() => loading.value, liveRefresh)
useRealtimeRefresh(['Relay Message', 'Contact', 'Relay Contact Type'], ['messages', 'receipts', 'contacts', 'reads', 'chats', 'permissions'],
  live.refresh, LIVE_DELAY)
</script>

<template>
  <section class="business-browser" :aria-busy="loading">
    <nav v-if="state.doctype || state.unlinked" class="business-crumbs" aria-label="Business navigation">
      <button v-for="(crumb, index) in crumbs" :key="index" type="button" :aria-current="index === crumbs.length - 1 ? 'page' : undefined" :title="crumb.title" @click="navigate(crumb.state)">
        <FeatherIcon v-if="index" name="chevron-right" :size="14" aria-hidden="true" />{{ crumb.label }}
      </button>
    </nav>
    <h3 ref="heading" tabindex="-1" class="business-level">{{ levelLabel(state, fields) }}</h3>
    <form class="business-search" role="search" @submit.prevent="search">
      <TextInput v-model="query" type="search" maxlength="80" :aria-label="searchLabel(state, fields)" :placeholder="searchLabel(state, fields)">
        <template #prefix><FeatherIcon name="search" /></template>
      </TextInput>
    </form>
    <ErrorMessage :message="error" />
    <div class="business-tiles">
      <LoadingRows v-if="loading && !items.length" label="Loading records…" />
      <button v-for="tile in items" :key="tileKey(tile)" type="button" class="business-tile"
        :disabled="busy" :aria-pressed="tile.kind === 'record' && selectedDoctype === tile.doctype && selected === tile.name" @click="choose(tile)">
        <Avatar v-if="['contact', 'record', 'chat'].includes(tile.kind)" :label="tile.label" />
        <span v-else class="business-tile-icon" aria-hidden="true"><FeatherIcon :name="tile.kind === 'unlinked' ? 'users' : 'folder'" :size="20" /></span>
        <span class="business-tile-copy"><strong>{{ tile.label }}</strong>
          <small v-if="contacts && tile.kind !== 'contact'">{{ tileCount(tile.contact_count, 'contact') }}</small>
          <small v-else-if="tile.kind === 'type' || tile.kind === 'group'">{{ tileCount(tile.record_count, 'record') }}</small>
          <small v-else-if="tile.kind === 'record'">{{ tile.last_activity ? 'Last activity ' + listTime(tile.last_activity) : 'No activity yet' }}</small>
          <small v-else-if="tile.kind === 'contact'">{{ tile.mobile_no || tile.name }}</small>
          <small v-else-if="tile.kind === 'chat'">{{ tile.latest_preview || 'No messages yet' }}</small>
        </span>
        <span v-if="!contacts && tileUnread(tile)" class="directory-unread" :aria-label="tileCount(tileUnread(tile), ['record', 'chat'].includes(tile.kind) ? 'unread message' : 'unread record')">{{ tileUnread(tile) }}</span>
        <FeatherIcon name="chevron-right" :size="16" aria-hidden="true" />
      </button>
      <p v-if="!loading && !error && !items.length" class="business-empty">No matching {{ people ? 'contacts' : 'records' }}.</p>
      <Button v-if="error" label="Retry" @click="load()" />
      <LoadingRows v-if="loading && items.length" label="Loading more…" />
      <span v-if="next != null" ref="moreSentinel" class="business-more" aria-hidden="true" />
    </div>
  </section>
</template>

<style scoped>
.business-browser { flex:1 1 auto; display:flex; flex-direction:column; min-height:0; min-width:0; overflow:auto; color:var(--relay-ink); }
.business-crumbs { display:flex; flex-wrap:wrap; gap:0 4px; padding:4px 12px; }
.business-crumbs button { display:inline-flex; align-items:center; gap:4px; min-height:44px; min-width:44px; padding:4px; font-size:12px; color:var(--relay-ink-3); overflow-wrap:anywhere; text-align:left; }
.business-crumbs [aria-current=page] { color:var(--relay-ink); font-weight:600; }
.business-level { padding:0 16px; font-size:14px; font-weight:600; }
.business-search { padding:12px 16px; }
.business-search :deep(input) { min-height:44px; }
.business-tiles { display:flex; flex-direction:column; gap:8px; padding:0 12px 16px; }
.business-tile { display:flex; align-items:center; gap:12px; min-height:76px; width:100%; padding:12px; text-align:left; border:1px solid var(--relay-stroke); border-radius:12px; background:var(--relay-layer); }
.business-tile:hover, .business-tile[aria-pressed=true] { background:var(--relay-accent-soft); border-color:var(--relay-accent); }
.business-tile-icon { display:grid; place-items:center; flex:none; width:40px; height:40px; border-radius:10px; background:var(--relay-accent-soft); color:var(--relay-accent-text); }
.business-tile-copy { display:flex; flex:1; flex-direction:column; min-width:0; gap:4px; overflow-wrap:anywhere; }
.business-tile-copy strong { font-size:14px; font-weight:600; }
.business-more { grid-column:1 / -1; height:1px; }
.business-tile-copy small, .business-empty { font-size:12px; color:var(--relay-ink-3); }
.business-tile:focus-visible, .business-crumbs button:focus-visible { outline:2px solid var(--relay-accent); outline-offset:2px; }
@media (max-width:768px) {
  .business-browser :deep(input), .business-browser :deep(button:not(.business-tile)) { min-height:44px !important; min-width:44px; }
}
</style>
