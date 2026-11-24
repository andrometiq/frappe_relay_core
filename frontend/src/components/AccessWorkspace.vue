<script setup>
import { computed, onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon, TextInput, toast } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { ROLE_COLUMNS, ROLE_MATRIX, ROLE_OPTIONS, accessChanges, filterAccessRows, labelList, roleBadges, seesAllTypes } from '../services/accessRoles'
import SettingsLayout from './settings/SettingsLayout.vue'
import SidePanel from './shell/SidePanel.vue'
import ToggleSwitch from './fields/ToggleSwitch.vue'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import UserAvatar from './UserAvatar.vue'
import LoadingRows from './LoadingRows.vue'

// Who can use Relay: Frappe roles, Relay Team members and Relay Contact Type users. Managers change them; everyone reads their own.
const data = ref({ can_edit: false, items: [], teams: [], business_types: [] })
const loading = ref(true), saving = ref(false), error = ref(''), panelError = ref('')
const filters = ref({ query: '', role: '', team: '', businessType: '' })
const editing = ref(null), draft = ref(null), newUser = ref('')
const rows = computed(() => filterAccessRows(data.value.items, filters.value))
const typeOptions = computed(() => data.value.business_types.map(row => ({ ...row, label: row.enabled ? row.label : row.label + ' (off)' })))
const changes = computed(() => editing.value && draft.value ? accessChanges(editing.value, draft.value) : {})
const changed = computed(() => Object.keys(changes.value).length > 0)
const addable = (options, chosen) => options.filter(option => !chosen.includes(option.value))

async function load() {
  loading.value = true; error.value = ''
  try { data.value = await coreApi('access.directory') }
  catch (e) { error.value = e.message }
  finally { loading.value = false }
}
function edit(row) {
  if (!data.value.can_edit) return
  panelError.value = ''; newUser.value = ''
  editing.value = row
  draft.value = { ...row, teams: [...row.teams], business_types: [...row.business_types] }
}
// Add user starts an empty row; picking a staff user fills it with that user's current access.
function addUser() {
  edit({ user: '', full_name: '', role: '', team_user: false, teams: [], business_types: [], role_locked: '', added: true })
  draft.value.role = 'User'
}
function pickUser(user) {
  newUser.value = user
  const known = data.value.items.find(row => row.user === user)
  if (known) { edit(known); return }
  editing.value = { ...editing.value, user }
  draft.value = { ...draft.value, user }
}
function close() { editing.value = null; draft.value = null; panelError.value = '' }
async function save() {
  if (!draft.value.user || !changed.value) return
  saving.value = true; panelError.value = ''
  try {
    const row = await coreApi('access.save', { user: draft.value.user, ...changes.value }, true)
    const index = data.value.items.findIndex(item => item.user === row.user)
    if (index >= 0) data.value.items.splice(index, 1, row)
    else data.value.items.push(row)
    toast('Access saved for ' + (row.full_name || row.user))
    close()
  } catch (e) { panelError.value = e.message }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <SettingsLayout active="access" :panel="Boolean(draft)">
    <main class="page-main" aria-label="Access">
      <header class="page-head">
        <h2>Access</h2><small>Who can see and do what</small>
        <div class="page-head-actions"><Button v-if="data.can_edit" label="Add user" icon-left="plus" variant="solid" @click="addUser" /></div>
      </header>
      <div v-if="data.can_edit" class="page-bar">
        <TextInput v-model="filters.query" class="page-search" type="search" placeholder="Search users" aria-label="Search users"><template #prefix><FeatherIcon name="search" /></template></TextInput>
        <select v-model="filters.role" class="page-select" aria-label="Role"><option value="">All roles</option><option v-for="role in ['User', 'Team User', 'Manager', 'System Manager']" :key="role" :value="role">{{ role }}</option></select>
        <select v-if="data.teams.length" v-model="filters.team" class="page-select" aria-label="Team"><option value="">All teams</option><option v-for="team in data.teams" :key="team.value" :value="team.value">{{ team.label }}</option></select>
        <select v-if="data.business_types.length" v-model="filters.businessType" class="page-select" aria-label="Business type"><option value="">All business types</option><option v-for="type in typeOptions" :key="type.value" :value="type.value">{{ type.label }}</option></select>
      </div>
      <p v-else-if="!loading" class="page-note">This is your own access. A communication manager can change it.</p>
      <div v-if="error" class="page-feedback"><ErrorMessage :message="error" /></div>
      <LoadingRows v-if="loading" label="Loading access…" />
      <table v-else-if="rows.length" class="page-table access-table">
        <thead><tr><th>User</th><th>Role</th><th>Teams</th><th>Business types</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.user" :class="{ selected: draft?.user === row.user, readonly: !data.can_edit }" :tabindex="data.can_edit ? 0 : undefined"
            @click="edit(row)" @keydown.enter.prevent="edit(row)">
            <td class="cell-main"><span class="page-person"><UserAvatar :user="row.user" :label="row.full_name" size="sm" /><span><b class="cell-title" :title="row.full_name">{{ row.full_name }}</b><small :title="row.user">{{ row.user }}</small></span></span></td>
            <td data-label="Role"><span class="cell-wrap"><Badge v-for="badge in roleBadges(row)" :key="badge.label" :label="badge.label" :theme="badge.theme" /></span></td>
            <td data-label="Teams" :class="{ muted: !row.teams.length }">{{ labelList(row.teams, data.teams) || '—' }}</td>
            <td data-label="Business types" :class="{ muted: !row.business_types.length && !seesAllTypes(row) }">{{ seesAllTypes(row) ? 'All' : labelList(row.business_types, data.business_types) || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!error" class="page-empty"><strong>No users match</strong><p>Try another search or filter.</p></div>

      <div class="settings-page access-matrix">
        <section class="settings-card" aria-label="What each role can do">
          <header><div><h3>What each role can do</h3><p>Roles are Frappe roles. Business types narrow what a User sees. A System Manager can do everything, including setup and the Hub connection.</p></div></header>
          <div class="access-matrix-scroll">
            <table class="role-matrix">
              <thead><tr><th><span class="sr-only">Action</span></th><th v-for="role in ROLE_COLUMNS" :key="role">{{ role }}</th></tr></thead>
              <tbody><tr v-for="row in ROLE_MATRIX" :key="row.action"><td>{{ row.action }}</td>
                <td v-for="role in ROLE_COLUMNS" :key="role"><template v-if="typeof row[role] === 'string'">{{ row[role] }}</template><span v-else-if="row[role]" aria-label="Yes">✓</span><span v-else aria-label="No">–</span></td></tr></tbody>
            </table>
          </div>
        </section>
      </div>
    </main>

    <SidePanel v-if="draft" :title="draft.full_name || 'Add user'" label="Edit access" @close="close">
      <template #title><h2 class="access-panel-title"><UserAvatar v-if="draft.user" :user="draft.user" :label="draft.full_name" size="sm" /><span>{{ draft.full_name || draft.user || 'Add user' }}</span></h2></template>
      <ErrorMessage v-if="panelError" :message="panelError" />
      <div v-if="editing.added" class="panel-field">
        <RemoteLinkField :model-value="newUser" :field="{ label: 'Staff user', method: 'access.user_options', placeholder: 'Search by name or email' }" @update:model-value="pickUser" />
        <p class="panel-hint">Pick a staff user. Website users cannot get Relay access.</p>
      </div>
      <div class="panel-field">
        <h3 id="access-role-label">Role</h3>
        <p v-if="draft.role === 'System Manager'" class="panel-hint">System Managers can do everything in Relay. Change this role in Desk.</p>
        <div v-else class="segmented" role="group" aria-labelledby="access-role-label">
          <button v-for="option in ROLE_OPTIONS" :key="option.value" type="button" :aria-pressed="draft.role === option.value" :disabled="Boolean(draft.role_locked) || saving" @click="draft.role = option.value">{{ option.label }}</button>
        </div>
        <p v-if="draft.role_locked" class="panel-hint">{{ draft.role_locked }}</p>
      </div>
      <div class="settings-row access-toggle">
        <span class="settings-row-text"><b>Team User</b><small>Can filter chats by every team, not only their own</small></span>
        <ToggleSwitch v-model="draft.team_user" label="Team User" :disabled="Boolean(draft.role_locked) || saving" />
      </div>
      <div class="panel-field">
        <h3>Teams</h3>
        <div class="token-list">
          <span v-for="team in draft.teams" :key="team" class="token">{{ labelList([team], data.teams) }}<button type="button" :aria-label="'Remove from ' + labelList([team], data.teams)" :disabled="saving" @click="draft.teams = draft.teams.filter(value => value !== team)"><FeatherIcon name="x" :size="12" /></button></span>
          <select v-if="addable(data.teams, draft.teams).length" class="token-add" aria-label="Add to team" :disabled="saving" @change="draft.teams.push($event.target.value); $event.target.value = ''">
            <option value="">+ Add team</option><option v-for="team in addable(data.teams, draft.teams)" :key="team.value" :value="team.value">{{ team.label }}</option>
          </select>
          <span v-if="!data.teams.length" class="panel-hint">No teams exist yet.</span>
        </div>
      </div>
      <div class="panel-field">
        <h3>Business types (from Relay Contact Type)</h3>
        <div class="token-list">
          <span v-for="type in draft.business_types" :key="type" class="token">{{ labelList([type], data.business_types) }}<button type="button" :aria-label="'Remove ' + labelList([type], data.business_types)" :disabled="saving" @click="draft.business_types = draft.business_types.filter(value => value !== type)"><FeatherIcon name="x" :size="12" /></button></span>
          <select v-if="addable(typeOptions, draft.business_types).length" class="token-add" aria-label="Add business type" :disabled="saving" @change="draft.business_types.push($event.target.value); $event.target.value = ''">
            <option value="">+ Add business type</option><option v-for="type in addable(typeOptions, draft.business_types)" :key="type.value" :value="type.value">{{ type.label }}</option>
          </select>
        </div>
        <p v-if="seesAllTypes(draft)" class="panel-hint">Managers see every enabled business type, whatever is assigned here.</p>
      </div>
      <template #footer>
        <Button label="Save" variant="solid" :loading="saving" :disabled="!draft.user || !changed" @click="save" />
        <Button label="Cancel" variant="outline" :disabled="saving" @click="close" />
      </template>
    </SidePanel>
  </SettingsLayout>
</template>

<style scoped>
.access-table tbody tr.readonly { cursor:default; }
.access-matrix { padding-top:20px; max-width:none; }
.access-matrix-scroll { overflow-x:auto; }
.access-panel-title { display:flex; align-items:center; gap:8px; }
.access-toggle { padding:4px 0; border:0; min-height:0; }
</style>
