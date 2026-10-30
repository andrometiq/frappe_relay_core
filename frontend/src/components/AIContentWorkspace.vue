<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import EventPicker from './fields/EventPicker.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'

const props = defineProps({ kind: String })
const capabilities = inject('relayCapabilities')
const allowed = computed(() => capabilities.value.ai && capabilities.value.skills)
const knowledge = computed(() => props.kind === 'knowledge')
const api = computed(() => knowledge.value ? 'ai.knowledge' : 'ai.events')
const rows = ref([]), next = ref(null), draft = ref(null), busy = ref(false), error = ref(''), notice = ref('')
let generation = 0
function edit(row = {}) {
  draft.value = knowledge.value
    ? { title: '', enabled: 0, company: '', business_doctype: '', instructions: '', ...row }
    : { title: '', enabled: 0, company: '', description: '', audience: [], event_starts_on: '', event_ends_on: '', available_from: '', available_to: '', ...row }
  error.value = ''; notice.value = ''
}
async function load(append = false) {
  const current = ++generation
  if (!allowed.value) { rows.value = []; draft.value = null; return }
  busy.value = true; error.value = ''
  try {
    const page = await coreApi(api.value + '.directory', { after: append ? next.value : null })
    if (current === generation) { rows.value = append ? [...rows.value, ...page.items] : page.items; next.value = page.next }
  } catch (e) { if (current === generation) error.value = e.message }
  finally { if (current === generation) busy.value = false }
}
async function save() {
  if (!allowed.value || busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  const { name, memory_status, ...values } = draft.value
  try {
    const result = await coreApi(api.value + '.save', { name, values }, true)
    draft.value.name = result.name
    await load()
    notice.value = knowledge.value ? 'Instructions saved.' : 'Event saved. Its memory build is queued.'
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
watch([() => props.kind, allowed], () => { draft.value = null; rows.value = []; next.value = null; notice.value = ''; load() })
onMounted(load)
</script>
<template>
  <section class="v1-screen"><div class="v1-content space-y-4">
    <p v-if="!allowed">Enable AI features and use a communication manager account to access this page.</p>
    <template v-else>
      <WorkspaceHeading :description="knowledge ? 'Standing instructions: how the assistant should work.' : 'Facts about something that happened or is planned. Events are reference information, not instructions.'">
        <Button :label="knowledge ? 'New instruction' : 'New event'" :disabled="busy" @click="edit()" />
      </WorkspaceHeading>
      <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
      <div class="v1-detail-grid">
        <div class="space-y-3">
          <button v-for="row in rows" :key="row.name" class="v1-list-card" :disabled="busy" :aria-pressed="draft?.name === row.name" @click="edit(row)">
            <strong>{{ row.title }}</strong><span>{{ row.enabled ? 'Enabled' : 'Disabled' }}{{ row.memory_status ? ' · ' + row.memory_status : '' }}</span>
          </button>
          <p v-if="busy" role="status">Loading…</p><p v-else-if="!rows.length">No records yet.</p>
          <Button v-if="next" label="Load more" :disabled="busy" @click="load(true)" />
        </div>
        <form v-if="draft" class="workflow-card space-y-3" @submit.prevent="save">
          <FormControl v-model="draft.title" label="Title" required :disabled="busy" />
          <FormControl v-model="draft.enabled" label="Enabled" type="checkbox" :disabled="busy" />
          <EventPicker v-model="draft.company" label="Company (blank for all)" kind="company_record" :disabled="busy" />
          <template v-if="knowledge">
            <EventPicker v-model="draft.business_doctype" label="Business type (blank for all)" kind="business_doctype" :disabled="busy" />
            <FormControl v-model="draft.instructions" label="Standing instructions" type="textarea" rows="8" maxlength="8000" required :disabled="busy" />
          </template>
          <template v-else>
            <EventPicker v-model="draft.audience" label="Audience business types" kind="business_doctype" multiple :disabled="busy" />
            <FormControl v-model="draft.description" label="Event facts" type="textarea" rows="8" maxlength="10000" required :disabled="busy" />
            <div class="grid gap-3 sm:grid-cols-2">
              <FormControl v-for="field in ['event_starts_on', 'event_ends_on', 'available_from', 'available_to']" :key="field" v-model="draft[field]" :label="{event_starts_on:'Event starts',event_ends_on:'Event ends',available_from:'AI may use from',available_to:'AI may use until'}[field]" type="date" :disabled="busy" />
            </div>
            <a v-if="draft.name" class="underline" :href="'/desk/relay-ai-event/' + encodeURIComponent(draft.name)">Attachments and memory details</a>
          </template>
          <Button type="submit" label="Save" variant="solid" :loading="busy" />
        </form>
      </div>
    </template>
  </div></section>
</template>
