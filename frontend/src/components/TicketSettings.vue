<script setup>
import { computed, ref } from 'vue'
import { Button, ErrorMessage, FormControl, toast } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useTicketSettings } from '../composables/useTicketSettings'
import { COLOURS, movedNames, removalHint } from '../services/ticketSettings'

const { settings, apply } = useTicketSettings()
const busy = ref(false), error = ref(''), drafts = ref({}), adding = ref({ status: '', type: '' })
const sections = computed(() => [
  { kind: 'status', title: 'Statuses', hint: 'Each status is Open or Closed. New tickets start in the first Open status; Close moves a ticket to the first Closed status.', rows: settings.value.statuses },
  { kind: 'type', title: 'Types', hint: 'What a ticket is about.', rows: settings.value.types },
])
const typeOptions = computed(() => settings.value.status_types.map(value => ({ value, label: value })))

async function run(call) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { apply(await call()); toast('Saved') } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
const save = (kind, row, changes) => run(() => coreApi('ticket_settings.save', { kind, name: row.name, label: row.label, ...changes }, true))
function rename(kind, row) {
  const label = (drafts.value[kind + row.name] ?? row.label).trim()
  delete drafts.value[kind + row.name]
  if (label && label !== row.label) save(kind, row, { label })
}
const add = kind => {
  const label = adding.value[kind].trim()
  if (!label) return
  adding.value[kind] = ''
  run(() => coreApi('ticket_settings.save', { kind, label, ...(kind === 'status' ? { state: 'Open' } : {}) }, true))
}
const remove = (kind, row) => run(() => coreApi('ticket_settings.remove', { kind, name: row.name }, true))
function move(kind, rows, index, step) {
  const names = movedNames(rows, index, step)
  if (names) run(() => coreApi('ticket_settings.reorder', { kind, names }, true))
}
</script>

<template>
  <div class="ticket-settings">
    <ErrorMessage :message="error" />
    <section v-for="section in sections" :key="section.kind" class="workflow-card ticket-settings__list" :aria-label="section.title">
      <header><h2 class="font-semibold">{{ section.title }}</h2><p>{{ section.hint }}</p></header>
      <ul>
        <li v-for="(row, index) in section.rows" :key="row.name">
          <div class="ticket-settings__swatches" role="radiogroup" :aria-label="'Colour of ' + row.label">
            <button v-for="colour in COLOURS" :key="colour" type="button" role="radio" :class="['ticket-swatch', 'ticket-swatch--' + colour]" :aria-checked="row.colour === colour" :aria-label="colour" :title="colour" :disabled="busy" @click="row.colour !== colour && save(section.kind, row, { colour })" />
          </div>
          <FormControl class="ticket-settings__name" :model-value="drafts[section.kind + row.name] ?? row.label" :aria-label="'Name of ' + row.label" maxlength="60" :disabled="busy" @update:model-value="value => drafts[section.kind + row.name] = value" @blur="rename(section.kind, row)" @keydown.enter.prevent="rename(section.kind, row)" />
          <FormControl v-if="section.kind === 'status'" class="ticket-settings__state" type="select" :model-value="row.state" label="Type" :options="typeOptions" :disabled="busy" @update:model-value="state => save('status', row, { state })" />
          <span class="ticket-settings__order">
            <Button icon="arrow-up" variant="ghost" :aria-label="'Move ' + row.label + ' up'" title="Move up" :disabled="busy || index === 0" @click="move(section.kind, section.rows, index, -1)" />
            <Button icon="arrow-down" variant="ghost" :aria-label="'Move ' + row.label + ' down'" title="Move down" :disabled="busy || index === section.rows.length - 1" @click="move(section.kind, section.rows, index, 1)" />
            <Button icon="trash" variant="ghost" :aria-label="'Delete ' + row.label" :title="removalHint(row) || 'Delete'" :disabled="busy || !!row.tickets" @click="remove(section.kind, row)" />
          </span>
        </li>
      </ul>
      <form class="ticket-settings__add" @submit.prevent="add(section.kind)">
        <FormControl v-model="adding[section.kind]" :aria-label="'New ' + section.kind + ' name'" :placeholder="'New ' + section.kind" maxlength="60" :disabled="busy" />
        <Button type="submit" variant="outline" icon-left="plus" :label="'Add ' + section.kind" :disabled="busy" />
      </form>
    </section>
  </div>
</template>

<style scoped>
.ticket-settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 12px; align-items: start; overflow-y: auto; min-height: 0; }
.ticket-settings__list { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.ticket-settings__list header p { font-size: 12px; color: var(--ink-gray-6); }
.ticket-settings__list ul { display: flex; flex-direction: column; gap: 6px; }
.ticket-settings__list li { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 6px 0; border-top: 1px solid var(--outline-gray-2); }
.ticket-settings__swatches { display: flex; gap: 8px; }
.ticket-swatch { width: 22px !important; height: 22px !important; min-width: 0 !important; min-height: 0 !important; padding: 0 !important; border-radius: 999px; border: 2px solid transparent; outline: 1px solid var(--outline-gray-3); }
.ticket-swatch[aria-checked=true] { border-color: var(--surface-white); outline: 2px solid var(--ink-gray-8); }
.ticket-swatch--gray { background: var(--ink-gray-4); }
.ticket-swatch--blue { background: var(--ink-blue-3); }
.ticket-swatch--green { background: var(--ink-green-2); }
.ticket-swatch--amber { background: #d69e2e; }
.ticket-swatch--red { background: var(--ink-red-3); }
.ticket-settings__name { flex: 1 1 140px; min-width: 120px; }
.ticket-settings__state { flex: 0 0 120px; }
.ticket-settings :deep(.relay-field__label) { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.ticket-settings__order { display: inline-flex; margin-left: auto; }
.ticket-settings__add { display: flex; gap: 8px; align-items: center; }
.ticket-settings__add > :first-child { flex: 1; }
</style>
