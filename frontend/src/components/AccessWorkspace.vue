<script setup>
import { inject, onMounted, onBeforeUnmount, ref } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import { useTask } from '../composables/useTask'
import TeamsWorkspace from './TeamsWorkspace.vue'
import RemoteLinkField from './fields/RemoteLinkField.vue'
const capabilities = inject('relayCapabilities')
const tab = ref(new URLSearchParams(location.hash.split('?')[1]).has('group') ? 'groups' : 'teams')
const { busy, error, notice, run } = useTask()
const rows = ref([]), query = ref(''), next = ref(null), editing = ref(null), member = ref('')
async function load(after) {
  const page = await coreApi('teams.directory', { query: query.value, after })
  rows.value = after ? [...rows.value, ...page.items] : page.items; next.value = page.next
}
async function edit(row) { editing.value = await coreApi('teams.read', { name: row.name }); member.value = '' }
async function save() {
  editing.value = await coreApi('teams.save', { name: editing.value.name || undefined, title: editing.value.title, members: editing.value.members }, true)
  notice.value = 'Team saved'; await load()
}
function addMember() { if (member.value && !editing.value.members.includes(member.value)) editing.value.members.push(member.value); member.value = '' }
function readRoute() { if (location.hash.split('?')[0] === '#/teams' && new URLSearchParams(location.hash.split('?')[1]).has('group')) tab.value = 'groups' }
onMounted(() => window.addEventListener('hashchange', readRoute))
onBeforeUnmount(() => window.removeEventListener('hashchange', readRoute))
onMounted(() => { if (capabilities.value.manage) run(() => load()) })
useRealtimeRefresh(['Relay Team'], ['teams'], () => { if (capabilities.value.manage) return run(() => load()) })
</script>
<template>
  <section class="v1-screen">
    <nav class="v1-tabs" aria-label="Teams and access"><Button v-for="[value, label] in [['teams','Communication teams'],['groups','Business groups'],['access','Roles & access']]" :key="value" :label="label" :variant="tab === value ? 'solid' : 'ghost'" @click="tab = value" /></nav>
    <TeamsWorkspace v-if="tab === 'groups'" />
    <div v-else-if="tab === 'access'" class="v1-content space-y-4">
      <h2 class="text-lg font-semibold">Roles & access</h2>
      <article class="workflow-card"><h3>Relay Communication User</h3><p>Works on accessible business records and conversations assigned directly, through a communication team, or through business-group responsibility.</p></article>
      <article class="workflow-card"><h3>Relay Communication Manager</h3><p>Manages communication teams, conversation assignments, templates, sender linking and delivery health. Business document permissions still apply.</p></article>
      <article class="workflow-card"><h3>System Manager</h3><p>Configures the Hub connection, channels, business types, endpoints and Frappe permissions.</p></article>
      <div class="flex flex-wrap gap-3"><a class="v1-link" href="/desk/user">Users and roles</a><a class="v1-link" href="/desk/permission-manager">Role permissions</a><a class="v1-link" href="/desk/user-permission">User permissions</a></div>
    </div>
    <div v-else class="v1-content space-y-4">
      <p>Communication teams control conversation assignment. Business groups describe responsibility for business records. Assign a team or agent from a conversation’s Details action.</p>
      <template v-if="capabilities.manage">
        <form class="flex flex-wrap items-end gap-3" @submit.prevent="run(() => load())"><FormControl v-model="query" label="Search teams" /><Button type="submit" label="Search" :disabled="busy" /><Button label="New team" :disabled="busy" @click="editing = { title: '', members: [] }; error = ''; notice = ''" /></form>
        <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p><p v-if="busy" role="status">Loading / saving team…</p>
        <div class="v1-detail-grid"><div class="space-y-3"><button v-for="row in rows" :key="row.name" class="v1-list-card" :disabled="busy" @click="run(() => edit(row))"><strong>{{ row.title }}</strong><span>{{ row.name }}</span></button><p v-if="!rows.length && !busy && !error">No communication teams yet.</p><Button v-if="next" label="More teams" :disabled="busy" @click="run(() => load(next))" /></div>
          <form v-if="editing" class="workflow-card" @submit.prevent="run(save)"><h3 class="font-semibold">{{ editing.name ? 'Edit team' : 'New team' }}</h3><FormControl v-model="editing.title" label="Team name" :disabled="busy" /><ul class="space-y-2"><li v-for="user in editing.members" :key="user" class="flex items-center justify-between gap-2"><span class="break-all">{{ user }}</span><Button label="Remove" :aria-label="'Remove ' + user" :disabled="busy" @click="editing.members = editing.members.filter(value => value !== user)" /></li></ul><p v-if="!editing.members.length">Add at least one member.</p><RemoteLinkField v-model="member" :field="{ label: 'Add member', method: 'teams.agents', readOnly: busy }" /><Button label="Add member" :disabled="busy || !member" @click="addMember" /><Button type="submit" label="Save team" variant="solid" :disabled="busy || !editing.title.trim() || !editing.members.length" /><ErrorMessage :message="error" /></form>
        </div>
      </template>
      <p v-else>A Relay Communication Manager manages team membership. Review Roles & access for the permissions your administrator can grant.</p>
    </div>
  </section>
</template>
