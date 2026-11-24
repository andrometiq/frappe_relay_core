<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, ErrorMessage, FormControl } from '@relay/ui'
import RemoteLinkField from '../fields/RemoteLinkField.vue'
import BusinessRecordPicker from './BusinessRecordPicker.vue'
import MentionText from './MentionText.vue'
import { coreApi } from '../../services/coreApi'
import { stableSubmission } from '../../services/submission'
import { useTicketSettings } from '../../composables/useTicketSettings'
import { pickerOptions } from '../../services/ticketSettings'
import { mentionedUsers } from '../../services/ticketForm'

// A ticket without a chat: one business record, details with @mentions, an owner and a type.
const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ businessTypes: { type: Array, default: () => [] } })
const emit = defineEmits(['created'])
const { settings, load: loadSettings } = useTicketSettings()
const form = ref({}), picked = ref(new Map()), busy = ref(false), error = ref('')
const types = computed(() => pickerOptions(settings.value.types, 'No type'))
const ready = computed(() => form.value.subject?.trim() && form.value.businessType && form.value.businessRecord)

function prepare() {
  form.value = { subject: '', businessType: props.businessTypes[0]?.value || '', businessRecord: '', details: '', assignedTo: '', ticketType: '' }
  picked.value = new Map(); error.value = ''
  loadSettings().catch(e => { error.value = e.message })
}
async function create() {
  if (busy.value || !ready.value) return
  busy.value = true; error.value = ''
  const { subject, businessType, businessRecord, details, assignedTo, ticketType } = form.value
  const payload = { subject: subject.trim(), brief: details.trim(), business_type: businessType, business_record: businessRecord,
    assigned_to: assignedTo || '', mentions: JSON.stringify(mentionedUsers(details, picked.value)), ...(ticketType ? { ticket_type: ticketType } : {}) }
  try {
    const result = await stableSubmission('relay-ticket', payload, key => coreApi('tickets.create', { ...payload, request_key: key }, true))
    open.value = false
    emit('created', result)
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
watch(open, value => { if (value) prepare() }, { immediate: true })
</script>

<template>
  <Dialog v-model="open" class="new-ticket-dialog" :options="{ title: 'New ticket', size: 'lg' }" :disable-outside-click-to-close="busy">
    <form id="relay-new-ticket" class="new-ticket-form" @submit.prevent="create">
      <FormControl v-model="form.subject" label="Subject" required maxlength="140" :disabled="busy" />
      <div class="new-ticket-field">
        <span class="new-ticket-label">Business record <span class="new-ticket-required" aria-hidden="true">*</span></span>
        <BusinessRecordPicker v-model:type="form.businessType" v-model:record="form.businessRecord" :types="businessTypes" :disabled="busy" />
        <small>Required. Only teams that can see this record will see the ticket.</small>
      </div>
      <div class="new-ticket-field">
        <label for="new-ticket-details">Details</label>
        <MentionText id="new-ticket-details" v-model="form.details" v-model:picked="picked" :disabled="busy" placeholder="What needs to happen? Type @ to mention a colleague." />
        <small>Mentioned colleagues get a notification and can open this ticket.</small>
      </div>
      <div class="new-ticket-row">
        <RemoteLinkField v-model="form.assignedTo" :field="{ label: 'Assign to', method: 'tickets.colleagues', placeholder: 'Search colleagues…', readOnly: busy }" />
        <FormControl v-if="settings.types.length" v-model="form.ticketType" type="select" label="Type" :options="types" :disabled="busy" />
      </div>
      <ErrorMessage :message="error" />
    </form>
    <template #actions="{ close }">
      <Button label="Cancel" variant="outline" :disabled="busy" @click="close" />
      <Button type="submit" form="relay-new-ticket" label="Create ticket" variant="solid" :loading="busy" :disabled="!ready" />
    </template>
  </Dialog>
</template>

<style scoped>
.new-ticket-form { display:flex; flex-direction:column; gap:14px; }
.new-ticket-field { display:flex; flex-direction:column; gap:6px; }
.new-ticket-field > :is(label,.new-ticket-label) { color:var(--ink-gray-6); font-size:12px; }
.new-ticket-field > small { color:var(--ink-gray-6); font-size:12px; }
.new-ticket-required { color:var(--relay-red); }
.new-ticket-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; align-items:end; }
@media (max-width: 640px) {
  .new-ticket-row { grid-template-columns:1fr; }
  .new-ticket-form :deep(:is(input,select,textarea,button)) { min-height:44px; }
}
</style>

<style>
.relay-dialog.new-ticket-dialog :is(.relay-button,.relay-control) { min-height:44px; }
</style>
