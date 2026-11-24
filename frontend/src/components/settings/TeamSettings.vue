<script setup>
import { computed, onMounted, ref } from 'vue'
import { Button, ErrorMessage, FeatherIcon, TextInput, toast } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { linkedTitle } from '../../services/linkedTitle'
import { ALL, GROUP, RECORD, accessModes, accessSummary, businessRows, fieldLabel, teamDraft } from '../../services/teamAccess'
import SettingsLayout from './SettingsLayout.vue'
import SidePanel from '../shell/SidePanel.vue'
import RemoteLinkField from '../fields/RemoteLinkField.vue'
import TeamGroupPicker from './TeamGroupPicker.vue'
import UserAvatar from '../UserAvatar.vue'
import LoadingRows from '../LoadingRows.vue'

// Teams and the business records their members see while Teams are on. Managers only.
const teams = ref([]), next = ref(null), enabled = ref(false), types = ref([])
const loading = ref(true), saving = ref(false), error = ref(''), panelError = ref('')
const draft = ref(null)
const typeOf = doctype => types.value.find(row => row.business_doctype === doctype)
const typeLabel = doctype => typeOf(doctype)?.label || doctype
const addableTypes = computed(() => types.value.filter(row => row.enabled && !draft.value?.types.some(type => type.doctype === row.business_doctype)))
const modeLabel = { [GROUP]: 'Pick groups', [RECORD]: 'Pick records', [ALL]: 'All records' }

async function load(append = false) {
  loading.value = true; error.value = ''
  try {
    const [result, rows] = await Promise.all([coreApi('teams.directory', { after: append ? next.value : undefined }),
      append ? types.value : coreApi('business_types.list_types')])
    teams.value = append ? [...teams.value, ...result.items] : result.items
    next.value = result.next; enabled.value = result.teams_enabled; types.value = rows
  } catch (e) { error.value = e.message }
  finally { loading.value = false }
}
async function edit(team) {
  panelError.value = ''
  draft.value = teamDraft(team)
  if (!team.name) return
  try { draft.value = teamDraft(await coreApi('teams.read', { name: team.name })) }
  catch (e) { panelError.value = e.message }
}
function addType(doctype) {
  if (doctype) draft.value.types.push({ doctype, mode: accessModes(typeOf(doctype))[0], values: [] })
}
function setMode(type, mode) { type.mode = mode; type.values = [] }
function close() { draft.value = null; panelError.value = '' }
async function save() {
  saving.value = true; panelError.value = ''
  try {
    const { name, title, members, types: chosen } = draft.value
    await coreApi('teams.save', { name: name || undefined, title, members: JSON.stringify(members), business: JSON.stringify(businessRows(chosen)) }, true)
    toast('Team saved'); close(); await load()
  } catch (e) { panelError.value = e.message }
  finally { saving.value = false }
}
onMounted(() => load())
</script>

<template>
  <SettingsLayout active="teams" :panel="Boolean(draft)">
    <main class="page-main" aria-label="Teams">
      <header class="page-head">
        <h2>Teams</h2><small>Who sees which business records</small>
        <div class="page-head-actions"><Button label="New team" icon-left="plus" variant="solid" @click="edit({})" /></div>
      </header>
      <p v-if="!loading && !enabled" class="page-note">Teams are off, so every user still sees all records of their business types. Turn on Teams in Settings › Features when the teams are ready.</p>
      <div v-if="error" class="page-feedback"><ErrorMessage :message="error" /></div>
      <LoadingRows v-if="loading && !teams.length" label="Loading teams…" />
      <table v-else-if="teams.length" class="page-table team-table">
        <thead><tr><th>Team</th><th>Members</th><th class="col-optional">Business types</th><th>Access</th></tr></thead>
        <tbody>
          <tr v-for="team in teams" :key="team.name" :class="{ selected: draft?.name === team.name }" tabindex="0" @click="edit(team)" @keydown.enter.prevent="edit(team)">
            <td class="cell-main"><b class="cell-title" :title="team.title">{{ team.title }}</b></td>
            <td data-label="Members"><span class="team-avatars"><UserAvatar v-for="user in team.members.slice(0, 2)" :key="user" :user="user" :label="linkedTitle('User', user)" size="sm" /><span v-if="team.members.length > 2">+{{ team.members.length - 2 }}</span></span></td>
            <td data-label="Business types" class="col-optional" :class="{ muted: !team.business.length }">{{ team.business.map(row => typeLabel(row.business_doctype)).join(', ') || '—' }}</td>
            <td data-label="Access" :class="{ muted: !team.business.length }"><span v-for="line in accessSummary(team.business, typeLabel)" :key="line" class="team-access-line">{{ line }}</span><template v-if="!team.business.length">No records</template></td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!error" class="page-empty"><strong>No teams yet</strong><p>Create a team, add its members and pick the business records they handle.</p></div>
      <div v-if="next" class="team-more"><Button variant="outline" label="Show more teams" :loading="loading" @click="load(true)" /></div>
    </main>

    <SidePanel v-if="draft" :title="draft.title || 'New team'" label="Edit team" wide @close="close">
      <ErrorMessage v-if="panelError" :message="panelError" />
      <div class="panel-field"><label for="team-title">Team name</label><TextInput id="team-title" v-model="draft.title" maxlength="100" :disabled="saving" /></div>
      <div class="panel-field"><RemoteLinkField v-model="draft.members" multiple :field="{ label: 'Members', method: 'teams.agents', placeholder: 'Add a member', readOnly: saving }" /></div>
      <section v-for="(type, index) in draft.types" :key="type.doctype + type.mode + index" class="panel-field team-type">
        <h3>Business type {{ index + 1 }} · {{ typeLabel(type.doctype) }} <small>{{ typeOf(type.doctype)?.grouping_fields?.length ? '(grouped by ' + fieldLabel(typeOf(type.doctype).grouping_fields[0]) + ')' : '(no grouping field)' }}</small>
          <button type="button" class="team-type-remove" :aria-label="'Remove ' + typeLabel(type.doctype)" :disabled="saving" @click="draft.types.splice(index, 1)"><FeatherIcon name="x" :size="14" /></button></h3>
        <div class="segmented" role="group" :aria-label="typeLabel(type.doctype) + ' access'">
          <button v-for="mode in accessModes(typeOf(type.doctype))" :key="mode" type="button" :aria-pressed="type.mode === mode" :disabled="saving" @click="setMode(type, mode)">{{ modeLabel[mode] }}</button>
        </div>
        <TeamGroupPicker v-if="type.mode === GROUP" v-model="type.values" :doctype="type.doctype" :label="typeLabel(type.doctype)" :disabled="saving" />
        <RemoteLinkField v-else-if="type.mode === RECORD" v-model="type.values" multiple :field="{ label: '', method: 'api.business_records', params: { doctype: type.doctype }, placeholder: 'Search and add records', readOnly: saving }" />
        <p v-else class="panel-hint">Every {{ typeLabel(type.doctype) }} record, including new ones.</p>
      </section>
      <div class="panel-field">
        <select v-if="addableTypes.length" class="page-select" aria-label="Add business type" :disabled="saving" @change="addType($event.target.value); $event.target.value = ''">
          <option value="">+ Add business type</option><option v-for="type in addableTypes" :key="type.business_doctype" :value="type.business_doctype">{{ type.label || type.business_doctype }}</option>
        </select>
        <p class="panel-hint">A type with a grouping field gives groups to tick. A type without one: pick records one by one.</p>
      </div>
      <template #footer>
        <Button label="Save team" variant="solid" :loading="saving" :disabled="!draft.title.trim() || !draft.members.length" @click="save" />
        <Button label="Cancel" variant="outline" :disabled="saving" @click="close" />
      </template>
    </SidePanel>
  </SettingsLayout>
</template>

<style scoped>
.team-avatars { display:inline-flex; align-items:center; gap:4px; color:var(--relay-ink-3); font-size:12.5px; }
.team-access-line { display:block; white-space:nowrap; }
.team-access-line + .team-access-line { color:var(--relay-ink-soft); font-size:12px; }
.team-more { padding:12px 20px; }
.team-type { padding-top:4px; }
.team-type h3 { display:flex; align-items:center; gap:6px; }
.team-type h3 small { color:var(--relay-ink-soft); font-weight:400; }
.team-type-remove { display:grid; place-items:center; width:24px; height:24px; margin-left:auto; border-radius:4px; color:var(--relay-ink-soft); }
.team-type-remove:hover { background:var(--relay-hover); }
@media (max-width: 640px) { .team-type-remove { width:44px; height:44px; } }
</style>
