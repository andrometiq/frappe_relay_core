import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { navAllowed } from '../src/services/navigation.js'
import { assignmentLabel } from '../src/services/assignment.js'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
const title = (_doctype, name) => name.toUpperCase()

test('the Teams page needs the teams capability, which the backend gives only while teams are on', async () => {
  assert.match(await read('SiteApp.vue'), /name: 'Teams'[^}]*teams: true/)
  assert.equal(navAllowed({ name: 'Teams', teams: true }, { manage: true, teams: false }), false)
  assert.equal(navAllowed({ name: 'Teams', teams: true }, { manage: true, teams: true }), true)
})

test('the inbox shows folder controls only while folders are on', async () => {
  const inbox = await read('components/messages/InboxDirectory.vue')
  assert.match(inbox, /<InboxFolders v-if="capabilities\.folders/)
  assert.match(inbox, /v-if="capabilities\.folders && row\.folder/)
  assert.match(inbox, /<template v-if="capabilities\.folders">\s*<Dropdown ref="rowMenu"[^]*<MoveToFolderDialog/)
  assert.match(inbox, /if \(!capabilities\.value\.folders\) return/)
  const tools = await read('components/messages/ConversationTools.vue')
  assert.match(tools, /<MoveToFolderDialog v-if="capabilities\.folders"/)
  assert.match(tools, /<RemoteLinkField v-if="capabilities\.teams_enabled" v-model="team"/)
})

test('the inbox queues are Mine, Unassigned, All and Unread, and Mine explains itself in one tooltip', async () => {
  const inbox = await read('components/messages/InboxDirectory.vue')
  assert.match(inbox, /\['mine', 'Mine', 'Chats assigned to you'\]/)
  assert.deepEqual([...inbox.matchAll(/\['(mine|unassigned|all|unread)', '/g)].map(match => match[1]), ['mine', 'unassigned', 'all', 'unread'])
  assert.match(inbox, /:title="hint"/)
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
