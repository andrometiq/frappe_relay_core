<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, ErrorMessage, FormControl } from '@relay/ui'
import RemoteLinkField from '../fields/RemoteLinkField.vue'
import BusinessRecordPicker from '../tickets/BusinessRecordPicker.vue'
import { coreApi } from '../../services/coreApi'
import { stableSubmission } from '../../services/submission'
import { useTicketSettings } from '../../composables/useTicketSettings'
import { pickerOptions } from '../../services/ticketSettings'
import { businessTypeOptions, ticketPayload, ticketRoute, ticketSubject } from '../../services/ticketForm'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ contact: String, message: Object, messages: Array, contactName: String })
const emit = defineEmits(['created'])
const { settings, load: loadSettings } = useTicketSettings()
const form = ref({ subject: '', brief: '', ticketType: '', assignedTo: '' })
const types = computed(() => pickerOptions(settings.value.types, 'No type'))
// Every ticket has one business record: the chat's, or one picked for a contact that has none.
const businessType = ref(''), businessRecord = ref(''), recordState = ref('known'), businessTypes = ref([])
const busy = ref(false), error = ref('')
const selectedMessages = computed(() => props.messages?.length ? props.messages : [props.message].filter(Boolean))
const colleagues = computed(() => ({ method: 'collaboration.colleagues', params: { contact: props.contact }, readOnly: busy.value }))
const ready = computed(() => form.value.subject.trim() && props.message?.name && businessType.value && businessRecord.value)

function prepare() {
  form.value = { subject: ticketSubject(props.message, props.contactName ? 'Follow up with ' + props.contactName : 'Follow up'), brief: '', ticketType: '', assignedTo: '' }
  error.value = ''; businessType.value = props.message?.business_doctype || ''; businessRecord.value = props.message?.business_name || ''
  recordState.value = businessType.value ? 'known' : 'loading'
  loadSettings().then(reconcile, e => { error.value = e.message })
  if (!businessType.value) loadContactRecord()
}
// A chat without a stored record belongs to its contact's primary record; a contact without records gets one picked.
async function loadContactRecord() {
  try {
    const profile = await coreApi('api.contact_profile', { contact: props.contact })
    if (profile.primary) {
      businessType.value = profile.primary.doctype; businessRecord.value = profile.primary.name; recordState.value = 'known'
    } else if (profile.link_count) {
      recordState.value = 'several'
    } else {
      businessTypes.value = businessTypeOptions(await coreApi('business_types.list_types'))
      businessType.value = businessTypes.value[0]?.value || ''; recordState.value = 'pick'
    }
  } catch (e) { error.value = e.message; recordState.value = 'several' }
}
function reconcile() {
  if (!types.value.some(option => option.value === form.value.ticketType)) form.value.ticketType = ''
}
async function create() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const payload = { ...ticketPayload(form.value, selectedMessages.value.map(row => row.name)), business_type: businessType.value, business_record: businessRecord.value }
    const result = await stableSubmission('relay-ticket', payload, key => coreApi('tickets.create', { ...payload, request_key: key }, true))
    open.value = false
    emit('created', { ...result, href: ticketRoute(result.name) })
  } catch (e) { error.value = e.message || 'Could not create the ticket. Select up to 50 messages from one business record and check your permissions.' }
  finally { busy.value = false }
}
watch(open, value => { if (value) prepare() }, { immediate: true })
watch(settings, () => { if (open.value) reconcile() })
</script>

<template>
  <Dialog v-model="open" class="message-ticket-dialog" :options="{ title: 'Create ticket', size: 'md' }" :disable-outside-click-to-close="busy">
    <form id="relay-create-ticket" class="create-ticket-form" @submit.prevent="ready && create()">
      <p class="create-ticket-hint">{{ selectedMessages.length }} selected {{ selectedMessages.length === 1 ? 'message' : 'messages' }}</p>
      <div class="create-ticket-evidence" aria-label="Selected messages">
        <blockquote v-for="row in selectedMessages" :key="row.name" class="create-ticket-quote">{{ ticketSubject(row, 'Attachment or message without text') }}</blockquote>
      </div>
      <div v-if="recordState === 'pick'" class="create-ticket-record">
        <span class="create-ticket-label">Business record <span class="create-ticket-required" aria-hidden="true">*</span></span>
        <BusinessRecordPicker v-model:type="businessType" v-model:record="businessRecord" :types="businessTypes" :disabled="busy" />
        <small class="create-ticket-hint">This contact has no business record. Pick one: the contact is linked to it and the ticket belongs to it.</small>
      </div>
      <p v-else-if="recordState === 'several'" class="create-ticket-hint create-ticket-blocked" role="alert">This contact has several business records and none is primary. Mark its primary record in the contact panel, then create the ticket.</p>
      <p v-else-if="recordState === 'known'" class="create-ticket-hint">{{ businessType }} · {{ businessRecord }}</p>
      <FormControl v-model="form.subject" label="Subject" required maxlength="140" :disabled="busy" />
      <FormControl v-model="form.brief" type="textarea" label="Description" maxlength="4000" rows="3" placeholder="What needs to happen?" :disabled="busy" />
      <div class="create-ticket-row">
        <FormControl v-if="settings.types.length" v-model="form.ticketType" type="select" label="Type" :options="types" :disabled="busy" />
        <RemoteLinkField v-model="form.assignedTo" :field="{ ...colleagues, label: 'Assign to', placeholder: 'Search colleagues…' }" />
      </div>
      <p class="create-ticket-hint">The ticket links to this conversation. The assigned colleague gets a notification.</p>
      <ErrorMessage :message="error" />
    </form>
    <template #actions="{ close }">
      <Button label="Cancel" variant="ghost" :disabled="busy" @click="close" />
      <Button type="submit" form="relay-create-ticket" label="Create ticket" variant="solid" :loading="busy" :disabled="!ready" />
    </template>
  </Dialog>
</template>

<style scoped>
.create-ticket-evidence { max-height:240px; overflow:auto; display:flex; flex-direction:column; gap:8px; }
.create-ticket-form { display:flex; flex-direction:column; gap:12px; }
.create-ticket-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.4fr); gap:12px; }
.create-ticket-quote { margin:0; padding:8px 10px; border-left:3px solid var(--outline-gray-3); background:var(--surface-gray-1); border-radius:4px; color:var(--ink-gray-7); font-size:13px; overflow-wrap:anywhere; }
.create-ticket-hint { color:var(--ink-gray-6); font-size:12px; line-height:1.4; }
.create-ticket-record { display:flex; flex-direction:column; gap:6px; }
.create-ticket-label { color:var(--ink-gray-6); font-size:12px; }
.create-ticket-required, .create-ticket-blocked { color:var(--relay-red); }
@media (max-width: 640px) { .create-ticket-row { grid-template-columns:1fr; } .create-ticket-form :deep(:is(input,select,button)) { min-height:44px !important; } }
</style>

<style>
.relay-dialog.message-ticket-dialog :is(.relay-button,.relay-control) { min-height:44px; }
</style>
