import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { mediumChips } from '../src/services/enabledChannels.js'
import { TABS } from '../src/services/inboxFilters.js'
import { canLinkRow, readStateRequest, rowActionKeys } from '../src/services/inboxRows.js'

const inbox = await readFile(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')

test('the inbox lists business records and opens a record row as its business chat', () => {
  assert.match(inbox, /coreApi\('inbox\.directory', \{ rows: 'business'/)
  assert.match(inbox, /useQueueCounts\(medium, computed\(\(\) => \(\{ \.\.\.params\.value, \.\.\.INBOX_ROWS \}\)\)\)/, 'Tab counts count the same rows')
  assert.match(inbox, /if \(row\.kind === 'business'\) emit\('business', row\.doctype, \{ name: row\.record, label: row\.title \}\)\n  else emit\('select', row\.name\)/)
  assert.match(inbox, /businessType === row\.doctype && businessName === row\.record : selected === row\.name/)
  assert.doesNotMatch(inbox, /\{\{ row\.doctype \}\}<template v-if="row\.contact_name">/, 'A record row is two lines: name and latest message')
})

test('a chat without a customer says Not linked, and only a manager gets a Link button', () => {
  assert.match(inbox, /<span v-if="row\.unlinked && !rowActions\?\.canLink\(row\)" class="directory-unlinked">Not linked<\/span>/)
  assert.match(inbox, /<button v-if="rowActions\?\.canLink\(row\)"[^>]*>Link<\/button>/)
  assert.deepEqual(TABS.at(-1).slice(0, 2), ['unlinked', 'Not linked'])
  assert.equal(canLinkRow({ unlinked: true }, true), true)
  assert.equal(canLinkRow({ unlinked: true }, false), false, 'A user who cannot link never sees a dead-end button')
  assert.equal(canLinkRow({ kind: 'business', unlinked: true }, true), false)
  assert.equal(canLinkRow({ unlinked: false }, true), false)
})

test('the row menu offers read state, star, folders and link only where they apply', () => {
  assert.deepEqual(rowActionKeys({ unread: 2, unlinked: true, folder: 'F1' }, { folders: true, manage: true }), ['read', 'star', 'move', 'unfile', 'link'])
  assert.deepEqual(rowActionKeys({ unread: 0 }, {}), ['unread', 'star'])
  assert.deepEqual(rowActionKeys({ kind: 'business', unread: 0, folder: 'F1' }, { folders: true, manage: true }), ['unread'])
})

test('a business row marks every chat of its record, a chat row only itself', () => {
  const business = { kind: 'business', name: 'Customer:C1', doctype: 'Customer', record: 'C1', contact: 'RELAY-CON-2' }
  assert.deepEqual(readStateRequest(business, true), { business_doctype: 'Customer', business_name: 'C1', read: 1 })
  assert.deepEqual(readStateRequest({ name: 'RELAY-CON-1' }, false), { contact: 'RELAY-CON-1', read: 0 })
})

test('a chat with no saved name shows its number, and avatars carry no channel dot with one channel', () => {
  assert.match(inbox, /recordTitle\(row\.kind === 'business' \? row : \{ display_name: row\.display_name \|\| row\.contact \}, 'Unknown number'\)/)
  assert.match(inbox, /<span v-if="manyMediums" class="directory-channel"/)
  assert.match(inbox, /v-if="mode !== 'business' && manyMediums" class="inbox-channel-chips"/)
})

test('the channel row shows only switched-on channels, with no "soon" placeholders', () => {
  assert.match(inbox, /mediumChips\(capabilities\.value\)\.filter\(chip => chip\.enabled\)/)
  assert.doesNotMatch(inbox, />soon</)
  const shown = mediumChips({ enabled_channels: ['WhatsApp'] }).filter(chip => chip.enabled).map(chip => chip.value)
  assert.deepEqual(shown, ['WhatsApp'])
})

test('a shared read change by any user reloads the chat list and its counts', async () => {
  const counts = await readFile(new URL('../src/composables/useQueueCounts.js', import.meta.url), 'utf8')
  assert.match(inbox, /useRealtimeRefresh\(\['Relay Message'\], \[[^\]]*'chats'/)
  assert.match(counts, /watchRealtime\(\['Relay Message'\], \[[^\]]*'chats'/)
})
