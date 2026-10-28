<script setup>
import { computed, ref, watch } from 'vue'
import { Button, ErrorMessage, toast } from '@relay/ui'
import ChoiceField from './fields/ChoiceField.vue'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import { relativeTime } from './relativeTime'
import { distinctPeople, withMention } from '../services/ticketForm'

const props = defineProps({ ticket: Object })
const emit = defineEmits(['changed'])
const comments = ref([]), body = ref(''), mentions = ref([]), error = ref(''), busy = ref(false)
const labels = new Map()
const contact = computed(() => props.ticket.messages?.[0]?.contact || '')
const readOnly = computed(() => busy.value || !props.ticket.can_edit)
const watchers = computed(() => (props.ticket.tagged || []).map(row => row.user))
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
async function colleagues(query, signal) {
  const rows = distinctPeople(await coreApi('collaboration.colleagues', { contact: contact.value, query }, false, { signal }))
  for (const row of rows) labels.set(row.value, row.label)
  return rows
}
const watcherField = computed(() => ({ label: 'Watchers', placeholder: 'Add a watcher…', readOnly: readOnly.value, search: colleagues,
  initialOptions: (props.ticket.tagged || []).map(row => ({ value: row.user, label: row.full_name || row.user })) }))
const mentionField = computed(() => ({ label: 'Notify in this comment', placeholder: 'Search colleagues…', readOnly: readOnly.value, search: colleagues }))
function send() {
  return run(async current => {
    const result = await coreApi('ticket_tags.add_comment', { name: props.ticket.name, body: body.value, mentions: mentions.value }, true)
    if (current !== generation) return
    comments.value = result; body.value = ''; mentions.value = []
    toast('Comment added'); emit('changed')
  })
}
// Watchers save on each pick or removal.
function saveWatchers(users) {
  return run(async () => {
    await coreApi('ticket_tags.set_tagged', { name: props.ticket.name, users: users.slice(0, 20) }, true)
    toast('Watchers saved'); emit('changed')
  })
}
watch(() => props.ticket.name, () => {
  ++generation; comments.value = []; body.value = ''; mentions.value = []; error.value = ''; busy.value = false
  run(load)
}, { immediate: true })
watch(() => props.ticket.tagged, value => { for (const row of value || []) labels.set(row.user, row.full_name) }, { immediate: true })
useRealtimeRefresh([], ['tickets'], () => run(load))
</script>

<template>
  <section aria-label="Watchers and comments" class="ticket-discussion space-y-3">
    <div class="ticket-watchers">
      <ChoiceField v-if="ticket.can_edit" :field="watcherField" :model-value="watchers" multiple @update:model-value="saveWatchers" />
      <template v-else><h3 class="font-semibold">Watchers</h3><p class="ticket-muted">{{ ticket.tagged?.length ? ticket.tagged.map(row => row.full_name || row.user).join(', ') : 'No one is watching this ticket.' }}</p></template>
      <small class="ticket-muted">Watchers get updates and see this ticket under Tagged me.</small>
    </div>
    <h3 class="font-semibold">Comments</h3>
    <p v-if="!comments.length" class="ticket-muted">No comments yet.</p>
    <article v-for="row in comments" :key="row.name" class="ticket-comment">
      <div class="ticket-comment-author"><strong>{{ row.author_name }}</strong><time>{{ relativeTime(row.creation) }}</time></div>
      <p>{{ row.body }}</p>
    </article>
    <form v-if="ticket.can_edit" class="ticket-comment-form" @submit.prevent="send">
      <textarea v-model="body" aria-label="Ticket comment" placeholder="Write a comment…" rows="3" maxlength="4000" />
      <ChoiceField :field="mentionField" :model-value="mentions" multiple @update:model-value="mention" />
      <small class="ticket-muted">People you add here get a notification about this comment.</small>
      <div><Button type="submit" variant="solid" label="Add comment" :disabled="busy || !body.trim()" /></div>
    </form>
    <ErrorMessage :message="error" />
  </section>
</template>

<style scoped>
.ticket-discussion { border-top:1px solid var(--outline-gray-2); padding-top:0.75rem; }
.ticket-muted { color:var(--ink-gray-6); font-size:13px; }
.ticket-watchers { display:grid; gap:4px; }
.ticket-comment { border-top:1px solid var(--outline-gray-2); padding-top:0.5rem; }
.ticket-comment-author { display:flex; gap:8px; align-items:baseline; font-size:12px; }
.ticket-comment-author time { color:var(--ink-gray-5); font-size:11px; }
.ticket-comment p { white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; margin-top:4px; }
.ticket-comment-form { display:flex; flex-direction:column; gap:8px; }
.ticket-comment-form textarea { border:1px solid var(--outline-gray-2); background:var(--surface-gray-1); color:var(--ink-gray-8); border-radius:7px; padding:9px; resize:vertical; font-size:13px; }
</style>
