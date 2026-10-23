<script setup>
import { inject, onMounted, onBeforeUnmount, ref } from 'vue'
import { Avatar, Badge, Button, ErrorMessage, FeatherIcon, FormControl, TextInput } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import { useTask } from '../composables/useTask'
import LoadingRows from './LoadingRows.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import WorkspaceState from './WorkspaceState.vue'
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
    <nav class="v1-tabs" aria-label="Teams and access"><Button v-for="[value, label] in [['teams','Communication teams'],['groups','Business groups'],['access','Roles & access']]" :key="value" :label="label" :aria-pressed="tab === value" :variant="tab === value ? 'solid' : 'ghost'" @click="tab = value" /></nav>
    <TeamsWorkspace v-if="tab === 'groups'" />
    <div v-else-if="tab === 'access'" class="v1-content space-y-4">
      <WorkspaceHeading title="Roles & access" description="Give each teammate the right level of access." icon="lock" />
      <article class="workflow-card"><h3>Relay Communication User</h3><p>Works on accessible business records and conversations assigned directly, through a communication team, or through business-group responsibility.</p></article>
      <article class="workflow-card"><h3>Relay Communication Manager</h3><p>Manages communication teams, conversation assignments, templates, sender linking and delivery health. Business document permissions still apply.</p></article>
      <article class="workflow-card"><h3>System Manager</h3><p>Configures the Hub connection, channels, business types, endpoints and Frappe permissions.</p></article>
      <div class="flex flex-wrap gap-3"><a class="v1-link" href="/desk/user">Users and roles</a><a class="v1-link" href="/desk/permission-manager">Role permissions</a><a class="v1-link" href="/desk/user-permission">User permissions</a></div>
    </div>
    <div v-else class="v1-content space-y-4">
      <WorkspaceHeading title="Communication teams" description="Organize the people who handle your customer conversations." icon="user-check"><Button v-if="capabilities.manage" label="New team" icon-left="plus" variant="solid" :disabled="busy" @click="editing = { title: '', members: [] }; error = ''; notice = ''" /></WorkspaceHeading>
      <p class="workspace-help">Assign teams from a conversation’s Details action. Business groups manage responsibility for business records separately.</p>
      <template v-if="capabilities.manage">
        <form class="workspace-search" role="search" @submit.prevent="run(() => load())"><TextInput v-model="query" aria-label="Search teams" placeholder="Search teams"><template #prefix><FeatherIcon name="search" /></template></TextInput><Button type="submit" label="Search" :disabled="busy" /></form>
        <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p><LoadingRows v-if="busy && !rows.length" label="Loading teams…" :count="3" />
        <div class="v1-detail-grid"><div class="workspace-records"><button v-for="row in rows" :key="row.name" class="workspace-person-row" :aria-pressed="editing?.name === row.name" :disabled="busy" @click="run(() => edit(row))"><Avatar :label="row.title" /><span><strong>{{ row.title }}</strong><small>Communication team</small></span><FeatherIcon name="chevron-right" /></button><WorkspaceState v-if="!rows.length && !busy && !error" compact :title="query ? 'No teams found' : 'Build your first team'" description="Bring agents together to share conversation assignments." icon="users"><Button v-if="query" label="Clear search" @click="query = ''; run(() => load())" /><Button v-else label="Create team" @click="editing = { title: '', members: [] }" /></WorkspaceState><Button v-if="next" label="More teams" :disabled="busy" @click="run(() => load(next))" /></div>
          <form v-if="editing" class="workflow-card team-editor" @submit.prevent="run(save)"><h3 class="font-semibold">{{ editing.name ? 'Edit team' : 'New team' }}</h3><FormControl v-model="editing.title" label="Team name" :disabled="busy" /><Badge :label="`${editing.members.length} ${editing.members.length === 1 ? 'member' : 'members'}`" /><ul class="team-members"><li v-for="user in editing.members" :key="user" class="flex items-center justify-between gap-2"><span class="break-all">{{ user }}</span><Button label="Remove" :aria-label="'Remove ' + user" :disabled="busy" @click="editing.members = editing.members.filter(value => value !== user)" /></li></ul><p v-if="!editing.members.length">Add at least one member.</p><RemoteLinkField v-model="member" :field="{ label: 'Add member', method: 'teams.agents', readOnly: busy }" /><Button label="Add member" :disabled="busy || !member" @click="addMember" /><Button type="submit" label="Save team" variant="solid" :disabled="busy || !editing.title.trim() || !editing.members.length" /><ErrorMessage :message="error" /></form>
          <WorkspaceState v-else compact title="A shared place for your team" description="Choose a team to review its members and manage access." icon="users" />
        </div>
      </template>
      <p v-else>A Relay Communication Manager manages team membership. Review Roles & access for the permissions your administrator can grant.</p>
    </div>
  </section>
</template>
