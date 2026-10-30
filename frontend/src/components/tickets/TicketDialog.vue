<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Badge, Button, Dialog, ErrorMessage, FormControl } from '@relay/ui'
import ChoiceField from '../fields/ChoiceField.vue'
import TicketDiscussion from '../TicketDiscussion.vue'
import { coreApi } from '../../services/coreApi'
import { linkedTitle } from '../../services/linkedTitle'
import { recordTitle } from '../../services/recordTitle'
import { distinctPeople } from '../../services/ticketForm'
import { isClosed, pickerOptions, statusLook } from '../../services/ticketSettings'
import { dateTime } from '../relativeTime'

const props = defineProps({ ticket: Object, settings: Object, busy: Boolean, aiEnabled: Boolean, error: String })
const emit = defineEmits(['update', 'close'])
const records = ref([])
const open = computed({ get: () => true, set: value => { if (!value) emit('close') } })
const title = computed(() => recordTitle(props.ticket, 'Ticket'))
const statusOptions = computed(() => pickerOptions(props.settings.statuses))
const look = computed(() => statusLook(props.settings, props.ticket))
const closed = computed(() => isClosed(props.settings, props.ticket))
const staffTookOver = computed(() => props.ticket.ai_disabled && props.ticket.ownership_actor && props.ticket.ownership_actor !== 'Administrator')
const ownerField = computed(() => ({ label: '', placeholder: linkedTitle('User', props.ticket.assigned_to, 'Search colleagues…'), readOnly: props.busy,
  search: async (query, signal) => distinctPeople(await coreApi('collaboration.colleagues', { contact: props.ticket.contact, query }, false, { signal })) }))
// The second press of the double-click that opened the ticket lands on the mask; it must not close it.
const keepOpenOnDoubleClick = event => { if (event.detail > 1 && event.target.classList?.contains('relay-dialog-mask')) event.stopPropagation() }
onMounted(() => document.addEventListener('mousedown', keepOpenOnDoubleClick, true))
onBeforeUnmount(() => document.removeEventListener('mousedown', keepOpenOnDoubleClick, true))
const deskRoute = (doctype, name) => '/app/' + encodeURIComponent(doctype.toLowerCase().replaceAll(' ', '-')) + '/' + encodeURIComponent(name)

// The contact's linked business records; a contact the user cannot read shows none.
watch(() => props.ticket.contact_person, async person => {
  records.value = []
  if (!person) return
  try {
    const details = await coreApi('api.contact_details', { contact: person })
    if (person === props.ticket.contact_person) records.value = details.links
  } catch { records.value = [] }
}, { immediate: true })
</script>

<template>
  <Dialog v-model="open" :options="{ title, size: 'lg' }">
    <div class="ticket-dialog" :aria-busy="busy">
      <ErrorMessage v-if="error" :message="error" />
      <p class="ticket-dialog__id">{{ ticket.name }}</p>
      <dl class="ticket-dialog__fields ticket-dialog__editable" aria-label="Ticket status and assignment">
        <dt>Status</dt>
        <dd>
          <FormControl v-if="ticket.can_edit" type="select" :model-value="ticket.ticket_status" aria-label="Status" :options="statusOptions" :disabled="busy" @update:model-value="status => status !== ticket.ticket_status && emit('update', 'update_status', { status })" />
          <Badge v-else :label="look.label" :theme="look.theme" />
        </dd>
        <dt>Assigned to</dt>
        <dd>
          <ChoiceField v-if="ticket.can_assign && ticket.contact" :model-value="''" :field="ownerField" @update:model-value="user => user && emit('update', 'assign', { user })" />
          <span v-else :class="{ 'ticket-unassigned': !ticket.assigned_to }">{{ linkedTitle('User', ticket.assigned_to, 'Unassigned') }}</span>
        </dd>
      </dl>
      <dl class="ticket-dialog__fields" aria-label="Ticket details">
        <dt>Type</dt>
        <dd>{{ ticket.ticket_type || 'No type' }}</dd>
        <dt>Contact</dt>
        <dd>
          <template v-if="ticket.contact">{{ ticket.contact_title || linkedTitle('Relay Contact', ticket.contact, 'Contact') }} · <a v-for="message in ticket.messages?.slice(0, 1)" :key="message.message" class="v1-link" :href="'#/messages?message=' + encodeURIComponent(message.message)">Open chat</a></template>
          <template v-else>No contact</template>
        </dd>
        <dt>Linked records</dt>
        <dd>
          <span v-if="!records.length">None</span>
          <a v-for="record in records" :key="record.doctype + ':' + record.name" class="v1-link ticket-dialog__record" :href="deskRoute(record.doctype, record.name)">{{ record.doctype }} · {{ linkedTitle(record.doctype, record.name) }}</a>
        </dd>
        <dt>Created</dt>
        <dd>{{ linkedTitle('User', ticket.owner, ticket.owner || 'Unknown') }} · {{ dateTime(ticket.creation) }}</dd>
      </dl>
      <p v-if="ticket.brief" class="ticket-dialog__brief">{{ ticket.brief }}</p>
      <section v-if="aiEnabled && ticket.conversation_key && ticket.company" class="ticket-dialog__ai" aria-label="AI">
        <div class="flex flex-wrap items-center gap-3">
          <Badge :label="ticket.ai_disabled ? (staffTookOver ? 'Staff took over' : 'AI stopped') : 'AI active'" :theme="ticket.ai_disabled ? 'gray' : 'green'" />
          <Button v-if="ticket.can_take_over && !staffTookOver" variant="outline" label="Take over" :disabled="busy" @click="emit('update', 'claim')" />
          <Button v-if="ticket.can_resume" variant="outline" label="Resume AI" :disabled="busy" @click="emit('update', 'resume_ai')" />
        </div>
        <p v-if="staffTookOver">{{ linkedTitle('User', ticket.ownership_actor, 'Staff') }} took over · {{ dateTime(ticket.ownership_at) }}</p>
        <a v-for="draft in ticket.linked_drafts" :key="draft.doctype + ':' + draft.name" class="v1-link block" :href="deskRoute(draft.doctype, draft.name)">
          Review {{ draft.doctype }} · {{ linkedTitle(draft.doctype, draft.name) }} · {{ ['Draft', 'Submitted', 'Cancelled'][draft.docstatus] }}
        </a>
      </section>
      <section v-if="ticket.messages?.length" class="ticket-evidence" aria-label="Linked messages">
        <h3>Linked messages · {{ ticket.messages.length }}</h3>
        <a v-for="message in ticket.messages" :key="message.message" class="v1-link" :href="'#/messages?message=' + encodeURIComponent(message.message)">
          {{ message.content || 'Attachment or message without text' }}
        </a>
      </section>
      <TicketDiscussion v-if="ticket.messages" :ticket="ticket" />
    </div>
    <template #actions>
      <Button label="Done" variant="ghost" @click="emit('close')" />
      <Button v-if="ticket.can_edit && !closed" label="Close ticket" variant="solid" icon-left="check" :disabled="busy" @click="emit('update', 'close_and_release')" />
    </template>
  </Dialog>
</template>

<style scoped>
.ticket-evidence { display:flex; flex-direction:column; gap:8px; max-height:280px; overflow:auto; }
.ticket-evidence a { display:block; min-height:44px; padding:12px; background:var(--surface-gray-1); border-radius:8px; white-space:pre-wrap; }
.ticket-dialog { display: flex; flex-direction: column; gap: 24px; overflow-wrap: anywhere; }
.ticket-dialog__id { font-size: 12px; color: var(--ink-gray-6); }
.ticket-dialog__editable { padding: 16px; border-radius: 8px; background: var(--surface-gray-1); }
.ticket-dialog__fields { display: grid; grid-template-columns: 120px minmax(0, 1fr); align-items: center; gap: 16px; font-size: 13px; }
.ticket-dialog__fields dt { color: var(--ink-gray-5); font-size: 12px; }
.ticket-dialog__fields dd { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; min-width: 0; color: var(--ink-gray-8); }
.ticket-dialog__fields dd > :deep(*) { max-width: 100%; }
.ticket-dialog__record { display: block; flex-basis: 100%; }
.ticket-dialog__brief { white-space: pre-wrap; font-size: 13px; padding: 16px; border-radius: 8px; background: var(--surface-gray-1); color: var(--ink-gray-8); }
.ticket-dialog__ai { display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
.ticket-unassigned { color: var(--ink-gray-6); }
@media (max-width: 640px) {
  .ticket-dialog__fields { grid-template-columns: 1fr; gap: 4px; }
  .ticket-dialog__fields dd { margin-bottom: 8px; }
}
</style>
