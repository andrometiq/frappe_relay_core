<script setup>
import { inject, onMounted, ref, watch } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon, TextInput, FormControl } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
import { relativeTime } from '../relativeTime'
import LoadingRows from '../LoadingRows.vue'
import WorkspaceState from '../WorkspaceState.vue'
import BusinessDirectory from './BusinessDirectory.vue'
const props = defineProps({ selected: String, businessName: String, businessType: String, busy: Boolean })
const emit = defineEmits(['select', 'business'])
const capabilities = inject('relayCapabilities')
const medium = ref('all');
const mode = ref('all'), query = ref(''), rows = ref([]), next = ref(null), loading = ref(false), error = ref('')
let generation = 0, searchTimer
async function load(cursor = {}) {
  clearTimeout(searchTimer)
  if (mode.value === 'business') return
  const ticket = ++generation; loading.value = true; error.value = ''
  try {
    const page = await coreApi('inbox.directory', { mode: mode.value, query: query.value, medium: medium.value === 'all' ? undefined : medium.value, ...cursor })
    if (ticket === generation) { rows.value = cursor.after ? [...rows.value, ...page.items] : page.items; next.value = page.next }
  } catch (e) { if (ticket === generation) { error.value = e.message; rows.value = []; next.value = null } }
  finally { if (ticket === generation) loading.value = false }
}
watch(query, (_value, _previous, onCleanup) => {
  ++generation; clearTimeout(searchTimer); error.value = ''; rows.value = []; next.value = null; loading.value = true
  searchTimer = setTimeout(() => load(), 300)
  onCleanup(() => { ++generation; clearTimeout(searchTimer) })
})
watch([mode, medium], () => { ++generation; rows.value = []; next.value = null; load() })
onMounted(() => load())
useRealtimeRefresh(['Relay Message', 'Relay Conversation Assignment'], ['messages', 'inbox', 'incoming', 'reads', 'permissions', 'contacts'], () => load())
</script>
<template>
  <header class="inbox-directory-heading"><div><h2>Conversations</h2><p>Stay close to every customer</p></div><FeatherIcon name="message-circle" :size="20" /></header>
  <nav class="v1-queues" aria-label="Inbox queues">
    <button v-for="[value, label] in [['all','All'],['mine','Mine'],['unread','Unread'],['unassigned','Unassigned']]" :key="value" :aria-pressed="mode === value" @click="mode = value">{{ label }}</button>
    <a v-if="capabilities.manage" href="#/contacts?tab=unlinked">Unlinked</a>
    <button :aria-pressed="mode === 'business'" @click="mode = 'business'">Businesses</button>
  </nav>
  <BusinessDirectory v-if="mode === 'business'" :selected="businessName" :selected-doctype="businessType" :busy="busy" @select="(doctype, record) => emit('business', doctype, record)" />
  <template v-else>
    <form class="directory-search inbox-filters" role="search" @submit.prevent="load()">
      <TextInput v-model="query" type="search" aria-label="Search conversations" placeholder="Search conversations" maxlength="80"><template #prefix><FeatherIcon name="search" /></template></TextInput>
      <FormControl v-model="medium" type="select" aria-label="Channel" :options="[{label:'All channels',value:'all'}, 'WhatsApp', 'Telegram', 'Email']" />
    </form>
    <p v-if="mode === 'mine'" class="px-4 pb-3 text-xs text-ink-gray-5">Conversations assigned directly to you.</p>
    <div v-if="error" class="px-4 py-3"><ErrorMessage :message="error" /><Button label="Retry queue" @click="load()" /></div>
    <div class="directory-rows" :aria-busy="loading">
      <LoadingRows v-if="loading && !rows.length" label="Loading conversations…" />
      <button v-for="row in rows" :key="row.name" class="directory-contact" :aria-pressed="selected === row.name" :disabled="busy" @click="emit('select', row.name)">
        <span class="directory-avatar"><Avatar :label="row.display_name || row.name" /><span class="directory-channel" :title="row.provider || 'Conversation'" :aria-label="row.provider || 'Conversation'"><FeatherIcon :name="row.provider === 'Email' ? 'mail' : row.provider === 'Telegram' ? 'send' : 'message-circle'" :size="11" /></span></span>
        <span class="directory-contact-copy">
          <span class="directory-contact-top"><strong>{{ row.display_name || row.name }}</strong><time :title="row.latest_at" :datetime="row.latest_at">{{ relativeTime(row.latest_at) }}</time></span>
          <span class="directory-contact-bottom"><small>{{ row.latest_preview || 'No messages yet' }}</small><span v-if="row.unread" class="directory-unread" :aria-label="`${row.unread} unread messages`">{{ row.unread > 99 ? '99+' : row.unread }}</span></span>
          <span class="directory-contact-context"><span v-if="row.business" class="directory-business" :title="row.business.doctype + ' · ' + row.business.name">{{ row.business.name }}</span><span class="directory-assignee"><FeatherIcon name="user" :size="12" />{{ row.assignment?.assigned_to || row.assignment?.team || 'Unassigned' }}</span></span>
        </span>
      </button>
      <WorkspaceState v-if="!loading && !rows.length && !error" compact :title="query ? 'No conversations found' : mode === 'unread' ? 'You’re all caught up' : 'No conversations yet'" :description="query ? 'Try a different name or clear your search.' : 'Browse your businesses to start a conversation.'"><Button v-if="query" label="Clear search" @click="query = ''" /><Button v-else label="Browse businesses" @click="mode = 'business'" /></WorkspaceState>
      <Button v-if="next" class="directory-load-more" label="More conversations" :loading="loading" @click="load(next)" />
    </div>
  </template>
</template>

<style scoped>
.inbox-filters { align-items:center; }
.inbox-filters > .relay-input-shell { flex:1; width:0; }
.inbox-filters > .relay-field { flex:0 0 132px; min-width:0; }
</style>
