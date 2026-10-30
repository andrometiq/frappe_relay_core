<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { browseCrumbs, browseRoute, enterBrowse, readBrowse, tileCount, tileUnread } from '../../services/businessBrowse'
import { useDebouncedSearch } from '../../composables/useDebouncedSearch'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
import { useLoadMore } from '../../composables/useLoadMore'
import { listTime } from '../relativeTime'
import LoadingRows from '../LoadingRows.vue'

const props = defineProps({ selected: String, selectedDoctype: String, busy: Boolean, contacts: Boolean, filters: Object })
const emit = defineEmits(['select', 'contact', 'navigate'])
const base = props.contacts ? '#/contacts' : '#/messages'
const state = ref(readBrowse(location.hash)), query = ref(state.value.query), items = ref([]), fields = ref([])
const loading = ref(false), error = ref(''), next = ref(null), heading = ref(null)
const people = computed(() => props.contacts && (query.value.trim() || state.value.record || state.value.unlinked))
const crumbs = computed(() => browseCrumbs(state.value, fields.value))
let sequence = 0
async function load(append = false) {
  const request = ++sequence
  loading.value = true; error.value = ''
  if (!append) { items.value = []; next.value = null }
  try {
    const page = people.value
      ? await coreApi('api.contact_directory', { query: query.value, after: append ? next.value : null,
        // Searching at any depth finds contacts directly, without restricting the business path.
        business_type: query.value.trim() ? null : state.value.doctype || null,
        business_name: query.value.trim() ? null : state.value.record || null,
        unlinked: !query.value.trim() && state.value.unlinked ? 1 : 0 })
      : await coreApi('business_groups.browse', { doctype: state.value.doctype || null,
        path: JSON.stringify(state.value.path), query: query.value, start: append ? next.value : 0,
        contacts: props.contacts ? 1 : 0, ...props.filters })
    if (request !== sequence) return
    const rows = people.value ? page.items.map(row => ({ ...row, kind: 'contact', label: row.full_name || row.name })) : page.items
    items.value = append ? [...items.value, ...rows] : rows
    fields.value = page.fields || fields.value; next.value = page.next
  } catch (e) { if (request === sequence) error.value = e.message }
  finally { if (request === sequence) loading.value = false }
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
useRealtimeRefresh(['Relay Message', 'Contact', 'Relay Contact Type'], ['messages', 'incoming', 'contacts', 'reads', 'chats', 'permissions'], () => load())
</script>

<template>
  <section class="business-browser" :aria-busy="loading">
    <nav v-if="state.doctype || state.unlinked" class="business-crumbs" aria-label="Business navigation">
      <button v-for="(crumb, index) in crumbs" :key="index" type="button" :aria-current="index === crumbs.length - 1 ? 'page' : undefined" :title="crumb.title" @click="navigate(crumb.state)">
        <FeatherIcon v-if="index" name="chevron-right" :size="14" aria-hidden="true" />{{ crumb.label }}
      </button>
    </nav>
    <h3 ref="heading" tabindex="-1" class="business-level">{{ people ? (query.trim() ? 'Contact search' : 'Contacts') : fields[state.path.length]?.label || (state.doctype ? 'Business records' : 'Business types') }}</h3>
    <form class="business-search" role="search" @submit.prevent="search">
      <TextInput v-model="query" type="search" maxlength="80" :aria-label="contacts ? 'Search contacts' : 'Search business records'" :placeholder="contacts ? 'Search name, number or email' : 'Search record title or name'">
        <template #prefix><FeatherIcon name="search" /></template>
      </TextInput>
    </form>
    <ErrorMessage :message="error" />
    <div class="business-tiles">
      <LoadingRows v-if="loading && !items.length" label="Loading records…" />
      <button v-for="tile in items" :key="JSON.stringify([tile.kind, tile.doctype, tile.name, tile.value])" type="button" class="business-tile"
        :disabled="busy" :aria-pressed="tile.kind === 'record' && selectedDoctype === tile.doctype && selected === tile.name" @click="choose(tile)">
        <Avatar v-if="tile.kind === 'contact'" :label="tile.label" />
        <span v-else class="business-tile-icon" aria-hidden="true"><FeatherIcon :name="tile.kind === 'record' ? 'file-text' : tile.kind === 'unlinked' ? 'users' : 'folder'" :size="20" /></span>
        <span class="business-tile-copy"><strong>{{ tile.label }}</strong>
          <small v-if="contacts && tile.kind !== 'contact'">{{ tileCount(tile.contact_count, 'contact') }}</small>
          <small v-else-if="tile.kind === 'type' || tile.kind === 'group'">{{ tileCount(tile.record_count, 'record') }}</small>
          <small v-else-if="tile.kind === 'record'">{{ tile.last_activity ? 'Last activity ' + listTime(tile.last_activity) : 'No activity yet' }}</small>
          <small v-else-if="tile.kind === 'contact'">{{ tile.mobile_no || tile.name }}</small>
        </span>
        <span v-if="!contacts && tileUnread(tile)" class="directory-unread" :aria-label="tileCount(tileUnread(tile), tile.kind === 'record' ? 'unread message' : 'unread record')">{{ tileUnread(tile) }}</span>
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
