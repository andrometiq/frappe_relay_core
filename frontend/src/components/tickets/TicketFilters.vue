<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Button, FeatherIcon, FormControl, TextInput } from '@relay/ui'
import ChoiceField from '../fields/ChoiceField.vue'
import RemoteLinkField from '../fields/RemoteLinkField.vue'
import { frappeRequest } from '../../services/coreApi'
import { linkedTitle } from '../../services/linkedTitle'
import { recordTitle } from '../../services/recordTitle'
import { activeTicketFilters, emptyTicketFilters, TICKET_PANEL_FILTERS } from '../../services/ticketSettings'

const filters = defineModel({ type: Object, required: true })
const props = defineProps({ statusOptions: Array, categoryOptions: Array, typeOptions: Array, businessTypes: Array, busy: Boolean })
const open = ref(false), panel = ref(null), trigger = ref(null)
const mineOptions = [{ value: 'assigned', label: 'Mine' }, { value: 'tagged', label: 'Tagged me' }]

async function searchAssignees(query, signal) {
  const rows = await frappeRequest('frappe.desk.search.search_link', { doctype: 'User', txt: query, filters: JSON.stringify({ enabled: 1 }), page_length: 30 }, false, { signal })
  return rows.map(row => ({ value: row.value, label: recordTitle(row, 'User'), description: row.value }))
}
const assigneeField = computed(() => ({ label: 'Assigned to', placeholder: 'Anyone', search: searchAssignees,
  initialOptions: filters.value.assigned_to ? [{ value: filters.value.assigned_to, label: linkedTitle('User', filters.value.assigned_to) }] : [] }))
const optionLabel = (options, value) => options?.find(option => option.value === value)?.label || value
const chips = computed(() => activeTicketFilters(filters.value).map(key => ({ key, label: {
  category: 'Category: ' + optionLabel(props.categoryOptions, filters.value.category),
  ticket_type: 'Type: ' + optionLabel(props.typeOptions, filters.value.ticket_type),
  business_doctype: 'Business type: ' + filters.value.business_doctype,
  business_name: 'Business: ' + linkedTitle(filters.value.business_doctype, filters.value.business_name),
  assigned_to: 'Assigned to: ' + linkedTitle('User', filters.value.assigned_to),
}[key] })))

const set = values => { filters.value = { ...filters.value, ...values } }
const toggleMine = value => set({ mine: filters.value.mine === value ? '' : value })
function remove(key) { set(key === 'business_doctype' ? { business_doctype: '', business_name: '' } : { [key]: '' }) }
function clearPanel() { set(Object.fromEntries(TICKET_PANEL_FILTERS.map(key => [key, '']))) }
function clearAll() { filters.value = emptyTicketFilters(); open.value = false }

// Pickers inside the panel open their option lists on <body>; a click there still belongs to the panel.
function outside(event) {
  const target = event.target
  if (panel.value?.contains(target) || trigger.value?.$el?.contains(target) || target.closest?.('.choice-results, .relay-select-overlay')) return
  open.value = false
}
const escape = event => { if (event.key === 'Escape') open.value = false }
watch(open, value => {
  const method = value ? 'addEventListener' : 'removeEventListener'
  document[method]('pointerdown', outside, true); document[method]('keydown', escape)
})
onBeforeUnmount(() => { open.value = false })
defineExpose({ clearAll })
</script>

<template>
  <div class="ticket-toolbar">
    <div class="ticket-toolbar__row">
      <TextInput v-model="filters.query" class="ticket-toolbar__search" type="search" placeholder="Search tickets" aria-label="Search tickets" maxlength="80"><template #prefix><FeatherIcon name="search" /></template></TextInput>
      <div class="ticket-segments" role="group" aria-label="Ticket status">
        <button v-for="option in statusOptions" :key="option.value" type="button" :aria-pressed="filters.ticket_status === option.value" @click="set({ ticket_status: option.value })">{{ option.label }}</button>
      </div>
      <div class="ticket-toolbar__chips">
        <button v-for="option in mineOptions" :key="option.value" type="button" class="ticket-chip" :aria-pressed="filters.mine === option.value" @click="toggleMine(option.value)">{{ option.label }}</button>
        <span class="ticket-toolbar__filters">
          <Button ref="trigger" variant="outline" icon-left="filter" :label="chips.length ? `Filters (${chips.length})` : 'Filters'" :aria-expanded="open" aria-controls="ticket-filter-panel" @click="open = !open" />
          <div v-if="open" id="ticket-filter-panel" ref="panel" class="ticket-filter-panel" role="dialog" aria-label="Ticket filters">
            <FormControl v-model="filters.category" label="Category" type="select" :options="categoryOptions" />
            <FormControl v-if="typeOptions.length > 1" v-model="filters.ticket_type" label="Type" type="select" :options="typeOptions" />
            <FormControl :model-value="filters.business_doctype" label="Business type" type="select" :options="[{ value: '', label: 'Any' }, ...businessTypes]" @update:model-value="value => set({ business_doctype: value, business_name: '' })" />
            <RemoteLinkField v-if="filters.business_doctype" :key="filters.business_doctype" v-model="filters.business_name" :field="{ label: 'Business', placeholder: 'Any', method: 'api.business_records', params: { doctype: filters.business_doctype }, doctype: filters.business_doctype }" />
            <ChoiceField v-model="filters.assigned_to" :field="assigneeField" />
            <div class="ticket-filter-panel__actions">
              <Button variant="outline" label="Clear" :disabled="!chips.length" @click="clearPanel" />
              <Button variant="solid" label="Done" @click="open = false" />
            </div>
          </div>
        </span>
      </div>
      <slot />
    </div>
    <div v-if="chips.length" class="ticket-toolbar__active" aria-label="Active filters">
      <span v-for="chip in chips" :key="chip.key" class="ticket-active-chip">{{ chip.label }}<button type="button" :aria-label="'Remove filter ' + chip.label" @click="remove(chip.key)"><FeatherIcon name="x" :size="14" /></button></span>
      <button type="button" class="v1-link" @click="clearAll">Clear all</button>
    </div>
  </div>
</template>

<style scoped>
.ticket-toolbar { display: flex; flex-direction: column; gap: 8px; }
.ticket-toolbar__row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.ticket-toolbar__search { flex: 1 1 220px; min-width: 0; max-width: 360px; }
.ticket-toolbar__chips { display: flex; align-items: center; gap: 6px; }
.ticket-toolbar__filters { position: relative; }
.ticket-segments { display: inline-flex; flex: none; max-width: 100%; overflow-x: auto; scrollbar-width: none; padding: 2px; border-radius: 8px; background: var(--surface-gray-2); }
.ticket-segments button { flex: none; height: 28px; padding: 0 12px; border-radius: 6px; font-size: 13px; color: var(--ink-gray-6); white-space: nowrap; }
.ticket-segments button[aria-pressed=true] { background: var(--surface-white); color: var(--ink-gray-9); font-weight: 600; box-shadow: 0 1px 2px rgb(0 0 0 / 12%); }
.ticket-chip { height: 30px; padding: 0 12px; border: 1px solid var(--outline-gray-2); border-radius: 999px; background: var(--surface-white); font-size: 13px; color: var(--ink-gray-7); white-space: nowrap; }
.ticket-chip[aria-pressed=true] { border-color: var(--outline-blue-1, var(--relay-accent)); background: var(--surface-blue-1, var(--relay-accent-soft)); color: var(--ink-blue-3); font-weight: 600; }
.ticket-filter-panel { position: absolute; z-index: 30; top: calc(100% + 6px); right: 0; width: min(320px, calc(100vw - 32px)); display: grid; gap: 12px; padding: 14px; border: 1px solid var(--outline-gray-2); border-radius: 10px; background: var(--surface-modal, var(--surface-white)); box-shadow: 0 10px 30px rgb(0 0 0 / 14%); }
.ticket-filter-panel__actions { display: flex; justify-content: flex-end; gap: 8px; }
.ticket-toolbar__active { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12.5px; }
.ticket-active-chip { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; padding: 2px 4px 2px 10px; border-radius: 999px; background: var(--surface-gray-2); color: var(--ink-gray-8); overflow-wrap: anywhere; }
.ticket-active-chip button { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 999px; color: var(--ink-gray-6); }
.ticket-active-chip button:hover { background: var(--surface-gray-3); color: var(--ink-gray-9); }
@media (max-width: 768px) {
  .ticket-toolbar__search { flex-basis: 100%; max-width: none; }
  .ticket-segments { width: 100%; }
  .ticket-filter-panel { position: fixed; top: auto; bottom: calc(72px + env(safe-area-inset-bottom)); left: 16px; right: 16px; width: auto; max-height: calc(100dvh - 120px); overflow-y: auto; }
}
</style>
