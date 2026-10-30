import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { navAllowed } from '../src/services/navigation.js'
import { assignmentLabel } from '../src/services/assignment.js'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
const title = (_doctype, name) => name.toUpperCase()

test('Roles and access replaces team controls and Settings is available to managers', async () => {
  assert.match(await read('SiteApp.vue'), /name: 'Teams'[^}]*label: 'Roles & access'/)
  assert.match(await read('SiteApp.vue'), /name: 'Settings'[^}]*manage: true/)
  assert.doesNotMatch(await read('components/AccessWorkspace.vue'), /Communication teams|teams.save|TeamsWorkspace/)
  assert.doesNotMatch(await read('components/TeamsWorkspace.vue'), /Take group|business_groups.claim/)
  assert.doesNotMatch(await read('components/SiteSettings.vue'), /Enable teams/)
})

test('the inbox shows folder controls only while folders are on', async () => {
  const inbox = await read('components/messages/InboxDirectory.vue')
  assert.match(inbox, /<InboxFolders v-if="capabilities\.folders/)
  assert.match(inbox, /v-if="capabilities\.folders && row\.folder/)
  const actions = await read('components/messages/InboxRowActions.vue')
  assert.match(actions, /<MoveToFolderDialog v-if="capabilities\.folders"/)
  assert.match(actions, /rowActionKeys\(item, \{ folders: capabilities\.value\.folders/)
})

test('the inbox tabs come from TABS, with no chat assignment anywhere in the list', async () => {
  const inbox = await read('components/messages/InboxDirectory.vue')
  assert.match(inbox, /v-for="\[value, label, hint\] in TABS"/)
  assert.match(inbox, /:title="hint"/)
  assert.doesNotMatch(inbox, /assignment|assigned|Mine|Unassigned/i)
})

test('the assignment line says who has the chat and who chose them', () => {
  const options = { user: 'me@x', teams: false, title }
  assert.equal(assignmentLabel({}, options), 'Unassigned')
  assert.equal(assignmentLabel(null, options), 'Unassigned')
  assert.equal(assignmentLabel({ assigned_to: 'me@x' }, options), 'Assigned to you')
  assert.equal(assignmentLabel({ assigned_to: 'me@x', assigned_by: 'boss' }, options), 'Assigned to you by BOSS')
  assert.equal(assignmentLabel({ assigned_to: 'ann', assigned_by: 'me@x' }, options), 'Assigned to ANN by you')
  assert.equal(assignmentLabel({ assigned_to: 'ann', assigned_by: 'ann' }, options), 'Assigned to ANN')
})

test('a team-only assignment reads Unassigned while teams are off and names the team while on', () => {
  assert.equal(assignmentLabel({ team: 'sales' }, { user: 'me', teams: false, title }), 'Unassigned')
  assert.equal(assignmentLabel({ team: 'sales' }, { user: 'me', teams: true, title }), 'Assigned to team SALES')
})
