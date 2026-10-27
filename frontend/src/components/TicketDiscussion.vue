<script setup>
import { computed, ref, watch } from 'vue'
import { Button, ErrorMessage } from '@relay/ui'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import ChoiceField from './fields/ChoiceField.vue'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import { relativeTime } from './relativeTime'
import { withMention } from '../services/ticketForm'

const props = defineProps({ ticket: Object })
const emit = defineEmits(['changed'])
const comments = ref([]), body = ref(''), mentions = ref([]), tagged = ref([]), error = ref(''), busy = ref(false)
const labels = new Map()
const contact = computed(() => props.ticket.messages?.[0]?.contact || '')
const colleagues = computed(() => ({ method: 'collaboration.colleagues', params: { contact: contact.value }, readOnly: busy.value || !props.ticket.can_edit }))
const tagsChanged = computed(() => tagged.value.join() !== (props.ticket.tagged || []).map(row => row.user).join())
let generation = 0

async function run(task) {
  const current = generation
  busy.value = true; error.value = ''
  try { await task(current) } catch (e) { if (current === generation) error.value = e.message }
  finally { if (current === generation) busy.value = false }
}
async function load() {
  const current = generation, result = await coreApi('ticket_tags.comments', { name: props.ticket.name })
  if (current === generation) comments.value = result
}
function mention(values) {
  if (values.length > 10) { error.value = 'Mention at most 10 colleagues'; return }
  for (const user of values.filter(user => !mentions.value.includes(user))) body.value = withMention(body.value, labels.get(user) || user)
  mentions.value = values
}
async function rememberLabels(query, signal) {
  const rows = await coreApi('collaboration.colleagues', { contact: contact.value, query }, false, { signal })
  for (const row of rows) labels.set(row.value, row.label)
  return rows
}
const mentionField = computed(() => ({ label: 'Mention colleagues (@)', placeholder: 'Search colleagues…', readOnly: colleagues.value.readOnly, search: rememberLabels }))
function send() {
  return run(async current => {
    const result = await coreApi('ticket_tags.add_comment', { name: props.ticket.name, body: body.value, mentions: mentions.value }, true)
    if (current !== generation) return
    comments.value = result; body.value = ''; mentions.value = []
    emit('changed')
  })
}
function saveTags() {
  return run(async () => { await coreApi('ticket_tags.set_tagged', { name: props.ticket.name, users: tagged.value }, true); emit('changed') })
}
watch(() => props.ticket.name, () => {
  ++generation; comments.value = []; body.value = ''; mentions.value = []; error.value = ''; busy.value = false
  run(load)
}, { immediate: true })
watch(() => props.ticket.tagged, value => { for (const row of value || []) labels.set(row.user, row.full_name); tagged.value = (value || []).map(row => row.user) }, { immediate: true })
useRealtimeRefresh([], ['tickets'], () => run(load))
</script>

<template>
  <section aria-label="Tagged colleagues and comments" class="ticket-discussion space-y-3">
    <h3 class="font-semibold">Tagged colleagues</h3>
    <p v-if="!ticket.tagged?.length" class="ticket-muted">No one is tagged yet.</p>
    <ul v-else class="ticket-tagged"><li v-for="row in ticket.tagged" :key="row.user">@{{ row.full_name || row.user }}</li></ul>
    <div v-if="ticket.can_edit" class="ticket-tag-editor">
      <RemoteLinkField :field="{ ...colleagues, label: 'Tag colleagues', placeholder: 'Search colleagues…', initialOptions: (ticket.tagged || []).map(row => ({ value: row.user, label: row.full_name || row.user })) }" :model-value="tagged" multiple @update:model-value="tagged = $event.slice(0, 20)" />
      <Button label="Save tags" :disabled="busy || !tagsChanged" @click="saveTags" />
    </div>
    <h3 class="font-semibold">Comments</h3>
    <p v-if="!comments.length" class="ticket-muted">No comments yet.</p>
    <article v-for="row in comments" :key="row.name" class="ticket-comment">
      <div class="ticket-comment-author"><strong>{{ row.author_name }}</strong><time>{{ relativeTime(row.creation) }}</time></div>
      <p>{{ row.body }}</p>
    </article>
    <form v-if="ticket.can_edit" class="ticket-comment-form" @submit.prevent="send">
      <ChoiceField :field="mentionField" :model-value="mentions" multiple @update:model-value="mention" />
      <textarea v-model="body" aria-label="Ticket comment" placeholder="Write a comment. Mentioned colleagues get a notification." rows="3" maxlength="4000" />
      <Button type="submit" variant="solid" label="Add comment" :disabled="busy || !body.trim()" />
    </form>
    <ErrorMessage :message="error" />
  </section>
</template>

<style scoped>
.ticket-discussion { border-top:1px solid var(--outline-gray-2); padding-top:0.75rem; }
.ticket-muted { color:var(--ink-gray-6); font-size:13px; }
.ticket-tagged { display:flex; flex-wrap:wrap; gap:6px; }
.ticket-tagged li { padding:2px 8px; border-radius:999px; background:var(--surface-blue-1, var(--surface-gray-2)); color:var(--ink-gray-8); font-size:12px; }
.ticket-tag-editor { display:flex; align-items:flex-end; gap:8px; }
.ticket-tag-editor > :first-child { flex:1; min-width:0; }
.ticket-comment { border-top:1px solid var(--outline-gray-2); padding-top:0.5rem; }
.ticket-comment-author { display:flex; gap:8px; align-items:baseline; font-size:12px; }
.ticket-comment-author time { color:var(--ink-gray-5); font-size:11px; }
.ticket-comment p { white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; margin-top:4px; }
.ticket-comment-form { display:flex; flex-direction:column; gap:8px; }
.ticket-comment-form textarea { border:1px solid var(--outline-gray-2); background:var(--surface-gray-1); color:var(--ink-gray-8); border-radius:7px; padding:9px; resize:vertical; font-size:13px; }
@media (max-width: 640px) { .ticket-tag-editor { flex-direction:column; align-items:stretch; } }
</style>
