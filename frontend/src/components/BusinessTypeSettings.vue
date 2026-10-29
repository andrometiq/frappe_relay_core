<script setup>
import { onMounted, ref } from 'vue'
import { Button, ErrorMessage } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useTask } from '../composables/useTask'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import LoadingRows from './LoadingRows.vue'
const rows = ref([]), selected = ref({})
const { busy, error, notice, run } = useTask()
async function load() { rows.value = await coreApi('business_types.list_types') }
function add(row) {
  const user = selected.value[row.business_doctype]
  if (user && !row.users.includes(user)) row.users.push(user)
  selected.value[row.business_doctype] = ''
}
async function save(row) {
  await coreApi('business_types.save', { business_doctype: row.business_doctype, enabled: row.enabled, users: row.users }, true)
  notice.value = `${row.label || row.business_doctype} users saved.`
}
onMounted(() => run(load))
</script>
<template>
  <section class="workflow-card">
    <h2 class="font-semibold">Business types and users</h2>
    <p>These assignments apply to every channel. Users see their assigned types and unlinked contacts. Managers see every enabled type.</p>
    <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
    <LoadingRows v-if="busy && !rows.length" :count="2" label="Loading business types…" />
    <p v-if="!busy && !rows.length">Configure a business type to assign users.</p>
    <form v-for="row in rows" :key="row.business_doctype" class="workflow-card" @submit.prevent="run(() => save(row))">
      <h3 class="font-semibold">{{ row.label || row.business_doctype }}{{ row.enabled ? '' : ' (Disabled)' }}</h3>
      <ul class="space-y-2"><li v-for="user in row.users" :key="user" class="flex flex-wrap items-center justify-between gap-2">
        <span class="break-all">{{ user }}</span><Button label="Remove" :aria-label="'Remove ' + user + ' from ' + row.business_doctype" variant="outline" :disabled="busy" @click="row.users = row.users.filter(value => value !== user)" />
      </li></ul>
      <p v-if="!row.users.length">No users assigned.</p>
      <RemoteLinkField v-model="selected[row.business_doctype]" :field="{ label: 'Add user to ' + (row.label || row.business_doctype), method: 'teams.agents', readOnly: busy }" />
      <div class="flex flex-wrap gap-2"><Button label="Add user" variant="outline" :disabled="busy || !selected[row.business_doctype]" @click="add(row)" /><Button type="submit" label="Save users" variant="solid" :disabled="busy" /></div>
    </form>
    <a class="v1-link" href="/desk/relay-contact-type">Configure business types and grouping</a>
  </section>
</template>
