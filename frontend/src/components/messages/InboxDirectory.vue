<script setup>
import { inject, onMounted, ref, watch } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
import BusinessDirectory from './BusinessDirectory.vue'
const props = defineProps({ selected: String, businessName: String, businessType: String, busy: Boolean })
const emit = defineEmits(['select', 'business'])
const capabilities = inject('relayCapabilities')
const mode = ref('all'), query = ref(''), rows = ref([]), next = ref(null), loading = ref(false), error = ref('')
let generation = 0
async function load(cursor = {}) {
  if (mode.value === 'business') return
  const ticket = ++generation; loading.value = true; error.value = ''
  try {
    const page = await coreApi('inbox.directory', { mode: mode.value, query: query.value, medium: 'WhatsApp', ...cursor })
    if (ticket === generation) { rows.value = cursor.after ? [...rows.value, ...page.items] : page.items; next.value = page.next }
  } catch (e) { if (ticket === generation) error.value = e.message }
  finally { if (ticket === generation) loading.value = false }
}
watch(mode, () => { rows.value = []; load() })
onMounted(() => load())
useRealtimeRefresh(['Relay Message', 'Relay Conversation Assignment'], ['messages', 'inbox', 'incoming', 'reads'], () => load())
</script>
<template>
  <nav class="v1-queues" aria-label="Inbox queues">
    <button v-for="[value, label] in [['all','All'],['mine','Mine'],['unread','Unread'],['unassigned','Unassigned']]" :key="value" :aria-pressed="mode === value" @click="mode = value">{{ label }}</button>
    <a v-if="capabilities.manage" href="#/contacts?tab=unlinked">Unlinked</a>
    <button :aria-pressed="mode === 'business'" @click="mode = 'business'">Businesses</button>
  </nav>
  <BusinessDirectory v-if="mode === 'business'" :selected="businessName" :selected-doctype="businessType" :busy="busy" @select="(doctype, record) => emit('business', doctype, record)" />
  <template v-else>
    <form class="directory-search" @submit.prevent="load()"><FormControl v-model="query" label="Search conversations" type="search" /><Button icon="search" aria-label="Search conversations" type="submit" :disabled="loading" /></form>
    <p v-if="mode === 'mine'" class="px-4 text-xs text-ink-gray-5">Conversations assigned directly to you.</p>
    <ErrorMessage class="px-4" :message="error" /><Button v-if="error" label="Retry queue" @click="load()" />
    <div class="directory-rows"><button v-for="row in rows" :key="row.name" class="directory-contact" :aria-pressed="selected === row.name" :disabled="busy" @click="emit('select', row.name)"><span class="directory-contact-copy"><strong>{{ row.display_name || row.name }}</strong><small>{{ row.latest_preview || 'No messages yet' }}</small></span><span v-if="row.unread" class="directory-unread">{{ row.unread }}</span></button>
      <p v-if="loading" class="p-4" role="status">Loading conversations…</p><p v-else-if="!rows.length && !error" class="p-4 text-sm">No conversations in this queue. Browse businesses to start a message.</p>
      <Button v-if="next" label="More conversations" :disabled="loading" @click="load(next)" />
    </div>
  </template>
</template>
