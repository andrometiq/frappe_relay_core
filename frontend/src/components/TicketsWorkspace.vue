<script setup>
import { recordTitle } from '../services/recordTitle'
import { linkedTitle } from '../services/linkedTitle'
import { onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import WorkspaceHeading from './WorkspaceHeading.vue'
import WorkspaceState from './WorkspaceState.vue'
import LoadingRows from './LoadingRows.vue'
import { relativeTime } from './relativeTime'
const filters = ref({ business_doctype: '', business_name: '', assigned_to: '', status: '', category: '' })
const page = ref({ items: [] }), selected = ref(null), owner = ref(''), busy = ref(false), error = ref('')
let generation = 0
async function load(cursor = {}) {
  const request = ++generation; busy.value = true; error.value = ''
  try {
    const result = await coreApi('tickets.directory', { ...filters.value, ...cursor })
    if (request === generation) page.value = result
    if (request === generation && selected.value) {
      const name = selected.value.name
      try {
        const detail = await coreApi('tickets.read', { name })
        if (request === generation && selected.value?.name === name) selected.value = detail
      } catch (e) { if (request === generation) selected.value = null; throw e }
    }
  } catch (e) { error.value = e.message }
  finally { if (request === generation) busy.value = false }
}
function reset() { filters.value = { business_doctype: '', business_name: '', assigned_to: '', status: '', category: '' }; load() }
function status(value) { filters.value.status = value; load() }
function select(row) { selected.value = row; owner.value = row.assigned_to || '' }
async function update(method, values) {
  busy.value = true; error.value = ''
  try { await coreApi('tickets.' + method, { name: selected.value.name, ...values }, true); await load() }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
onMounted(load)
useRealtimeRefresh(['Relay Ticket'], ['tickets'], () => load())
</script>
<template>
  <section class="v1-screen"><div class="v1-content space-y-4">
    <WorkspaceHeading title="Tickets" description="Review handoffs, assign an owner and follow each conversation." />
    <form class="automation-filter-bar" @submit.prevent="load()">
      <div class="automation-chips" role="group" aria-label="Ticket status">
        <button v-for="value in ['', 'Open', 'In progress', 'Resolved', 'Closed']" :key="value" type="button" class="automation-chip" :aria-pressed="filters.status === value" :disabled="busy" @click="status(value)">{{ value || 'All tickets' }}</button>
      </div>
      <FormControl v-model="filters.business_name" label="Business" placeholder="Business record" />
      <FormControl v-model="filters.assigned_to" label="Assignee" placeholder="User email" />
      <FormControl v-model="filters.category" label="Category" placeholder="Category" type="select" :options="['', 'Query', 'Payment evidence', 'Support', 'Other']" />
      <Button type="submit" label="Apply" :loading="busy" />
    </form>
    <ErrorMessage :message="error" />
    <div class="v1-detail-grid">
      <div class="space-y-3">
        <LoadingRows v-if="busy && !page.items.length" label="Loading tickets…" />
        <button v-for="row in page.items" :key="row.name" class="v1-list-card ticket-card" :aria-pressed="selected?.name === row.name" @click="select(row)">
          <div class="automation-card-heading"><strong>{{ recordTitle(row, 'Ticket') }}</strong><Badge :label="row.status" :theme="row.status === 'Open' ? 'amber' : row.status === 'In progress' ? 'blue' : 'gray'" /></div>
          <div class="flex flex-wrap items-center gap-2"><Badge class="ticket-business-badge" :label="row.business_name ? linkedTitle(row.business_doctype, row.business_name) : 'Conversation'" /><span>{{ row.category }} · {{ linkedTitle('User', row.assigned_to, 'Unassigned') }} · {{ relativeTime(row.creation) }}</span></div>
        </button>
        <WorkspaceState v-if="!busy && !error && !page.items.length" title="No matching tickets" description="Try another status or clear the filters to see all tickets." icon="bookmark"><Button label="Clear filters" @click="reset" /></WorkspaceState>
        <div class="flex gap-3"><Button v-if="page.previous" label="Previous" :disabled="busy" @click="load(page.previous)" /><Button v-if="page.next" label="Next" :disabled="busy" @click="load(page.next)" /></div>
      </div>
      <article v-if="selected" class="workflow-card">
        <div class="automation-card-heading"><h2 class="font-semibold">{{ selected.subject }}</h2><Button label="Dismiss" @click="selected = null" /></div><Badge :label="selected.status" theme="blue" class="self-start" /><p>{{ selected.brief }}</p>
        <p class="ticket-business-name">{{ linkedTitle(selected.business_doctype, selected.business_name) }}</p><p v-if="selected.handoff_reason">{{ selected.handoff_reason }}</p>
        <a v-for="message in selected.messages" :key="message.message" class="v1-link" :href="'#/messages?message=' + encodeURIComponent(message.message)">Open conversation · {{ linkedTitle('Relay Channel', message.channel, 'Conversation') }}</a>
        <form v-if="selected.can_assign" class="space-y-3" @submit.prevent="update('assign', { user: owner })"><FormControl v-model="owner" label="Assign to user" placeholder="User email" /><Button type="submit" label="Assign" :disabled="busy" /></form>
        <div class="flex flex-wrap gap-3"><Button label="Start work" :disabled="busy || selected.status === 'In progress'" @click="update('update_status', { status: 'In progress' })" /><Button label="Close ticket" :disabled="busy || selected.status === 'Closed'" @click="update('update_status', { status: 'Closed' })" /></div>
      </article><WorkspaceState v-else compact title="Your next conversation" description="Select a ticket to review its conversation and assignment." icon="message-circle" />
    </div>
  </div></section>
</template>
