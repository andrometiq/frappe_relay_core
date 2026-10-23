<script setup>
import { onMounted, ref } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
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
    <form class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" @submit.prevent="load()">
      <FormControl v-model="filters.business_doctype" label="Business type" placeholder="Supplier or Customer" />
      <FormControl v-model="filters.business_name" label="Business record" />
      <FormControl v-model="filters.assigned_to" label="Assignee" placeholder="User email" />
      <FormControl v-model="filters.status" label="Status" type="select" :options="['', 'Open', 'In progress', 'Resolved', 'Closed']" />
      <FormControl v-model="filters.category" label="Category" type="select" :options="['', 'Query', 'Payment evidence', 'Support', 'Other']" />
      <Button type="submit" label="Filter tickets" :loading="busy" />
    </form>
    <ErrorMessage :message="error" /><p v-if="busy" role="status">Loading tickets…</p>
    <div class="v1-detail-grid">
      <div class="space-y-3">
        <button v-for="row in page.items" :key="row.name" class="v1-list-card" :aria-pressed="selected?.name === row.name" @click="select(row)"><strong>{{ row.subject }}</strong><span>{{ row.business_name || 'Conversation' }} · {{ row.status }} · {{ row.category }}</span><span>{{ row.assigned_to || 'Unassigned' }}</span></button>
        <p v-if="!busy && !error && !page.items.length">No tickets match these filters.</p>
        <div class="flex gap-3"><Button v-if="page.previous" label="Previous" :disabled="busy" @click="load(page.previous)" /><Button v-if="page.next" label="Next" :disabled="busy" @click="load(page.next)" /></div>
      </div>
      <article v-if="selected" class="workflow-card space-y-3">
        <h2 class="font-semibold">{{ selected.subject }}</h2><p>{{ selected.brief }}</p>
        <p>{{ selected.business_doctype }} {{ selected.business_name }}</p><p>{{ selected.handoff_reason }}</p>
        <a v-for="message in selected.messages" :key="message.message" class="v1-link" :href="'#/messages?message=' + encodeURIComponent(message.message)">Open conversation · {{ message.channel }}</a>
        <form v-if="selected.can_assign" class="space-y-3" @submit.prevent="update('assign', { user: owner })"><FormControl v-model="owner" label="Assign to user" placeholder="User email" /><Button type="submit" label="Assign" :disabled="busy" /></form>
        <div class="flex flex-wrap gap-3"><Button label="Start work" :disabled="busy || selected.status === 'In progress'" @click="update('update_status', { status: 'In progress' })" /><Button label="Close ticket" :disabled="busy || selected.status === 'Closed'" @click="update('update_status', { status: 'Closed' })" /></div>
      </article><p v-else class="v1-empty">Select a ticket to review the conversation and assignment.</p>
    </div>
  </div></section>
</template>
