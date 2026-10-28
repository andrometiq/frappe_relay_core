<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Avatar, Button, ErrorMessage, TextInput } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { recordTitle } from '../services/recordTitle'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import ContactDetails from './ContactDetails.vue'
import IncomingWorkspace from './IncomingWorkspace.vue'
import LoadingRows from './LoadingRows.vue'
import WorkspaceState from './WorkspaceState.vue'

const rows = ref([]), query = ref(''), next = ref(null), busy = ref(false), error = ref('')
const selected = ref(''), more = ref(null)
let generation = 0, searchTimer, observer
async function load(cursor = {}) {
  const ticket = ++generation
  busy.value = true; error.value = ''
  try {
    const page = await coreApi('contacts.unlinked', { query: query.value, ...cursor })
    if (ticket === generation) {
      rows.value = cursor.after ? [...rows.value, ...page.items] : page.items
      next.value = page.next
    }
  } catch (e) { if (ticket === generation) error.value = e.message }
  finally { if (ticket === generation) busy.value = false }
}
watch(query, () => {
  ++generation; clearTimeout(searchTimer)
  rows.value = []; next.value = null; busy.value = true
  searchTimer = setTimeout(() => load(), 300)
})
watch([more, busy], () => {
  observer?.disconnect()
  if (!more.value || busy.value || error.value) return
  observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting) && next.value && !busy.value) load(next.value)
  }, { rootMargin: '200px 0px' })
  observer.observe(more.value)
}, { flush: 'post' })
onMounted(() => load())
onBeforeUnmount(() => { ++generation; clearTimeout(searchTimer); observer?.disconnect() })
useRealtimeRefresh(['Contact', 'Relay Message'], ['contacts', 'incoming'], () => load())
function linked() { selected.value = ''; load() }
</script>
<template>
  <div class="unlinked-contacts">
    <section class="v1-content" aria-label="Unlinked contacts">
      <p>These contacts have no linked business record. Their messages are visible in the inbox.</p>
      <form class="workspace-search" role="search" @submit.prevent="load()">
        <TextInput v-model="query" type="search" maxlength="80" aria-label="Search unlinked contacts" placeholder="Search by name or number" />
      </form>
      <ErrorMessage :message="error" /><Button v-if="error" label="Retry contacts" @click="load(next || {})" />
      <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !selected }">
        <div class="workspace-records" :aria-busy="busy">
          <LoadingRows v-if="busy && !rows.length" label="Loading unlinked contacts…" />
          <button v-for="row in rows" :key="row.name" class="workspace-person-row" :aria-pressed="selected === row.contact" @click="selected = row.contact">
            <Avatar :label="recordTitle(row, 'Contact')" />
            <span><strong>{{ recordTitle(row, 'Contact') }}</strong><small>{{ row.phone || 'No phone number' }}</small><small>{{ row.latest_preview || 'No messages yet' }}</small></span>
          </button>
          <WorkspaceState v-if="!busy && !rows.length && !error" compact title="No unlinked contacts" :description="query ? 'Try another name or number.' : 'Contacts with no business link will appear here.'" />
          <div v-if="next" ref="more" role="status">{{ busy ? 'Loading more contacts…' : '' }}</div>
        </div>
        <ContactDetails v-if="selected" :key="selected" :contact="selected" dismissible @changed="linked" @close="selected = ''" />
      </div>
    </section>
    <IncomingWorkspace />
  </div>
</template>
<style scoped>
.unlinked-contacts { overflow:auto; min-height:0; }
</style>
