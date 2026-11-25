<script setup>
import { onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { linkedTitle } from '../services/linkedTitle'
import { useTask } from '../composables/useTask'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import UserAvatar from './UserAvatar.vue'
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
  <section class="settings-card" aria-label="Business types and users">
    <header><div><h3>Business types and users</h3><p>These assignments apply to every channel. Users see their assigned types and unlinked contacts. Managers see every enabled type.</p></div></header>
    <a class="settings-row" href="/desk/relay-contact-type"><span class="settings-row-text"><b>Configure business types, grouping and profile fields</b><small>Add a type, change how its records are grouped, or pick the fields the chat details show</small></span><FeatherIcon name="external-link" :size="16" /></a>
  </section>
  <ErrorMessage :message="error" /><p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>
  <LoadingRows v-if="busy && !rows.length" :count="2" label="Loading business types…" />
  <p v-if="!busy && !rows.length" class="panel-hint">Configure a business type to assign users.</p>
  <form v-for="row in rows" :key="row.business_doctype" class="settings-card" @submit.prevent="run(() => save(row))">
    <header><div><h3>{{ row.label || row.business_doctype }}</h3><p>{{ row.users.length }} {{ row.users.length === 1 ? 'user' : 'users' }} assigned</p></div><Badge :label="row.enabled ? 'Enabled' : 'Disabled'" :theme="row.enabled ? 'green' : 'gray'" /></header>
    <div v-for="user in row.users" :key="user" class="settings-row">
      <UserAvatar :user="user" :label="linkedTitle('User', user)" size="sm" />
      <span class="settings-row-text"><b>{{ linkedTitle('User', user) }}</b><small>{{ user }}</small></span>
      <Button label="Remove" :aria-label="'Remove ' + user + ' from ' + row.business_doctype" variant="outline" :disabled="busy" @click="row.users = row.users.filter(value => value !== user)" />
    </div>
    <p v-if="!row.users.length" class="settings-row panel-hint">No users assigned.</p>
    <div class="settings-card-body">
      <div class="business-type-add"><RemoteLinkField v-model="selected[row.business_doctype]" :field="{ label: 'Add user to ' + (row.label || row.business_doctype), method: 'teams.agents', readOnly: busy }" />
        <Button label="Add user" variant="outline" :disabled="busy || !selected[row.business_doctype]" @click="add(row)" /></div>
      <div><Button type="submit" label="Save users" variant="solid" :disabled="busy" /></div>
    </div>
  </form>
</template>
<style scoped>
.business-type-add { display:flex; flex-wrap:wrap; align-items:flex-end; gap:8px; }
.business-type-add > :first-child { flex:1; min-width:200px; }
</style>
