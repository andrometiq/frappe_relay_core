<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, ErrorMessage, FormControl } from '@relay/ui'
import RemoteLinkField from '../fields/RemoteLinkField.vue'
import { coreApi } from '../../services/coreApi'
import { TICKET_PRIORITIES, ticketPayload, ticketRoute, ticketSubject } from '../../services/ticketForm'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ contact: String, message: Object, quoted: Boolean, contactName: String })
const emit = defineEmits(['created'])
const form = ref({ subject: '', brief: '', priority: 'Medium', assignedTo: '', tagged: [] })
const busy = ref(false), error = ref('')
const colleagues = computed(() => ({ method: 'collaboration.colleagues', params: { contact: props.contact }, readOnly: busy.value }))
const ready = computed(() => form.value.subject.trim() && props.message?.name)

function prepare() {
  form.value = { subject: ticketSubject(props.message, props.contactName ? 'Follow up with ' + props.contactName : 'Follow up'), brief: '', priority: 'Medium', assignedTo: '', tagged: [] }
  error.value = ''
}
function tag(values) {
  if (values.length > 20) { error.value = 'Tag at most 20 colleagues'; return }
  form.value.tagged = values
}
async function create() {
  busy.value = true; error.value = ''
  try {
    const result = await coreApi('tickets.create', ticketPayload(form.value, [props.message.name]), true)
    open.value = false
    emit('created', { ...result, href: ticketRoute(result.name) })
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
watch(open, value => { if (value) prepare() }, { immediate: true })
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Create ticket', size: 'md' }" :disable-outside-click-to-close="busy">
    <form id="relay-create-ticket" class="create-ticket-form" @submit.prevent="ready && create()">
      <blockquote v-if="quoted && message" class="create-ticket-quote">{{ ticketSubject(message, 'Attachment or message without text') }}</blockquote>
      <FormControl v-model="form.subject" label="Subject" required maxlength="140" :disabled="busy" />
      <FormControl v-model="form.brief" type="textarea" label="Description" maxlength="4000" rows="3" placeholder="What needs to happen?" :disabled="busy" />
      <div class="create-ticket-row">
        <FormControl v-model="form.priority" type="select" label="Priority" :options="TICKET_PRIORITIES" :disabled="busy" />
        <RemoteLinkField v-model="form.assignedTo" :field="{ ...colleagues, label: 'Assign to', placeholder: 'Search colleagues…' }" />
      </div>
      <RemoteLinkField :field="{ ...colleagues, label: 'Tag colleagues (@)', placeholder: 'Search colleagues…' }" :model-value="form.tagged" multiple @update:model-value="tag" />
      <p class="create-ticket-hint">The ticket links to this conversation. Assigned and tagged colleagues get a notification.</p>
      <ErrorMessage :message="error" />
    </form>
    <template #actions="{ close }">
      <Button label="Cancel" variant="ghost" :disabled="busy" @click="close" />
      <Button type="submit" form="relay-create-ticket" label="Create ticket" variant="solid" :loading="busy" :disabled="!ready" />
    </template>
  </Dialog>
</template>

<style scoped>
.create-ticket-form { display:flex; flex-direction:column; gap:12px; }
.create-ticket-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.4fr); gap:12px; }
.create-ticket-quote { margin:0; padding:8px 10px; border-left:3px solid var(--outline-gray-3); background:var(--surface-gray-1); border-radius:4px; color:var(--ink-gray-7); font-size:13px; overflow-wrap:anywhere; }
.create-ticket-hint { color:var(--ink-gray-6); font-size:12px; line-height:1.4; }
@media (max-width: 640px) { .create-ticket-row { grid-template-columns:1fr; } }
</style>
