<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Button, FeatherIcon } from '@relay/ui'
import ChoiceField from '../fields/ChoiceField.vue'
import { coreApi } from '../../services/coreApi'
import { recordTitle } from '../../services/recordTitle'
import { useMobileLayout } from '../../composables/useMobileLayout'
import { NO_RECORD, withoutFilters } from '../../services/inboxFilters'

/** Inbox filters by channel and business record: a popover under the filter button on desktop, a bottom sheet on the phone. */
const props = defineProps({ anchor: Object, options: { type: Array, default: () => [] }, manage: Boolean })
const open = defineModel('open', { type: Boolean, default: false })
const filters = defineModel({ type: Object, required: true })
const emit = defineEmits(['browse'])
const isMobile = useMobileLayout()
const panel = ref(null), position = ref({}), types = ref([]), typeError = ref('')
const labels = new Map()
const active = computed(() => filters.value.channels.length > 0 || !!filters.value.businessType)
const recordField = computed(() => ({
  label: filters.value.businessType, placeholder: `Search ${filters.value.businessType}…`,
  initialOptions: filters.value.businessName ? [{ value: filters.value.businessName, label: filters.value.businessLabel }] : [],
  search: async (query, signal) => {
    const rows = await coreApi('api.business_records', { doctype: filters.value.businessType, query }, false, { signal })
    return rows.map(row => {
      const option = { value: row.name, label: recordTitle(row), description: row.description || '' }
      labels.set(option.value, option.label)
      return option
    })
  },
}))

function toggleChannel(name, checked) {
  const channels = filters.value.channels.filter(value => value !== name)
  filters.value = { ...filters.value, channels: checked ? [...channels, name] : channels }
}
function chooseType(value) {
  if (value !== filters.value.businessType) filters.value = { ...filters.value, businessType: value, businessName: '', businessLabel: '' }
}
function chooseRecord(value) {
  filters.value = { ...filters.value, businessName: value || '', businessLabel: value ? labels.get(value) || value : '' }
}
function clear() { filters.value = withoutFilters(filters.value) }
function browse(target) { open.value = false; emit('browse', target) }

async function loadTypes() {
  if (types.value.length) return
  try { types.value = await coreApi('api.business_types'); typeError.value = '' } catch (error) { typeError.value = error.message }
}
// The desktop popover is fixed to the filter button, so the scrolling list never clips it.
function place() {
  const box = props.anchor?.getBoundingClientRect()
  if (!box || isMobile.value) return
  const width = Math.min(340, innerWidth - 16)
  position.value = { left: `${Math.max(8, Math.min(box.left, innerWidth - width - 8))}px`, top: `${box.bottom + 6}px`, width: `${width}px` }
}
function outside(event) {
  if (!panel.value?.contains(event.target) && !props.anchor?.contains(event.target)) open.value = false
}
watch(open, async value => {
  document.removeEventListener('pointerdown', outside)
  removeEventListener('resize', place)
  if (!value) return
  place(); loadTypes()
  document.addEventListener('pointerdown', outside)
  addEventListener('resize', place)
  await nextTick()
  panel.value?.querySelector('input,button')?.focus()
})
onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); removeEventListener('resize', place) })
</script>

<template>
  <Teleport to=".v1-shell" defer>
    <Transition name="relay-fade"><button v-if="open && isMobile" type="button" class="mobile-sheet-backdrop" aria-label="Close filters" @click="open = false" /></Transition>
    <Transition :name="isMobile ? 'relay-sheet' : ''">
      <div v-if="open" ref="panel" :class="['inbox-filter-panel', isMobile ? 'mobile-sheet' : 'number-pop']" :style="isMobile ? undefined : position"
        role="dialog" aria-label="Filter chats" :aria-modal="isMobile || undefined" @keydown.esc="open = false">
        <span v-if="isMobile" class="mobile-sheet-handle" aria-hidden="true" />
        <div class="inbox-filter-head"><h3>Filter chats</h3><button v-if="active" type="button" class="inbox-filter-clear" @click="clear">Clear filters</button></div>
        <fieldset v-if="options.length" class="inbox-filter-group">
          <legend>Channel</legend>
          <label v-for="option in options" :key="option.name" class="inbox-filter-check">
            <input type="checkbox" :checked="filters.channels.includes(option.name)" @change="toggleChannel(option.name, $event.target.checked)">
            <span>{{ option.label }}<small>{{ [option.medium, option.address].filter(Boolean).join(' · ') }}</small></span>
          </label>
          <p class="inbox-filter-hint">With no channel ticked, the inbox shows every channel.</p>
        </fieldset>
        <fieldset class="inbox-filter-group">
          <legend>Business record</legend>
          <div class="inbox-filter-types" role="radiogroup" aria-label="Business type">
            <button v-for="[value, label] in [['', 'Any'], ...types.map(type => [type, type]), [NO_RECORD, 'No record']]" :key="value" type="button" role="radio"
              :aria-checked="filters.businessType === value" @click="chooseType(value)">{{ label }}</button>
          </div>
          <p v-if="typeError" role="alert" class="inbox-filter-hint">{{ typeError }}</p>
          <ChoiceField v-if="filters.businessType && filters.businessType !== NO_RECORD" :key="filters.businessType" class="inbox-filter-record"
            :field="recordField" :model-value="filters.businessName" @update:model-value="chooseRecord" />
          <p v-if="filters.businessType && filters.businessType !== NO_RECORD && !filters.businessName" class="inbox-filter-hint">Leave the record empty to show every {{ filters.businessType }}.</p>
        </fieldset>
        <div class="inbox-filter-foot">
          <button type="button" class="inbox-filter-link" @click="browse('business')"><FeatherIcon name="briefcase" :size="14" />Browse businesses</button>
          <button v-if="manage" type="button" class="inbox-filter-link" @click="browse('unlinked')"><FeatherIcon name="user-x" :size="14" />Unlinked senders</button>
          <Button variant="solid" label="Done" @click="open = false" />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style>
.inbox-filter-panel { display:flex; flex-direction:column; gap:10px; padding:12px; }
.inbox-filter-panel.number-pop { max-height:min(560px,80vh); }
.inbox-filter-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.inbox-filter-head h3 { margin:0; color:var(--relay-ink); font-size:14px; font-weight:600; }
.inbox-filter-clear, .inbox-filter-link { display:inline-flex; align-items:center; gap:6px; border-radius:6px; color:var(--relay-accent-text); font-size:12.5px; }
.inbox-filter-clear:hover, .inbox-filter-link:hover { text-decoration:underline; }
.inbox-filter-group { display:grid; gap:6px; min-width:0; margin:0; padding:0; border:0; }
.inbox-filter-group legend { margin-bottom:4px; padding:0; color:var(--relay-ink-3); font-size:11.5px; font-weight:600; }
.inbox-filter-check { display:flex; align-items:center; gap:10px; min-height:36px; padding:4px 6px; border-radius:6px; color:var(--relay-ink); font-size:13px; cursor:pointer; }
.inbox-filter-check:hover { background:var(--relay-select); }
.inbox-filter-check input { flex:none; width:16px; height:16px; accent-color:var(--relay-accent); }
.inbox-filter-check span { min-width:0; overflow-wrap:anywhere; }
.inbox-filter-check small { display:block; color:var(--relay-ink-3); font-size:11.5px; }
.inbox-filter-hint { margin:0; color:var(--relay-ink-3); font-size:11.5px; }
.inbox-filter-types { display:flex; flex-wrap:wrap; gap:6px; }
.inbox-filter-types button { height:28px; padding:0 12px; border:1px solid var(--relay-stroke); border-radius:14px; background:var(--relay-layer-strong); color:var(--relay-ink-2); font-size:12.5px; }
.inbox-filter-types button[aria-checked=true] { border-color:var(--relay-accent); background:var(--relay-accent-soft); color:var(--relay-accent-text); font-weight:600; }
.inbox-filter-foot { display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding-top:8px; border-top:1px solid var(--relay-stroke); }
.inbox-filter-foot .relay-button { margin-left:auto; }
@media (max-width: 768px) {
  .inbox-filter-panel.mobile-sheet { gap:12px; padding-inline:16px; }
  .inbox-filter-check { min-height:44px; font-size:14px; }
  .inbox-filter-types button { height:34px; font-size:13.5px; }
}
</style>
