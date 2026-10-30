import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { notesInThread } from '../src/services/threadNotes.js'

const message = (name, sent_at) => ({ name, sent_at })
const note = (name, creation, extra = {}) => ({ name, creation, body: 'Check stock', author_name: 'Asha', ...extra })
const rows = [message('M1', '2026-10-28 10:00:00'), message('M2', '2026-10-28 12:00:00')]

test('internal notes sit between messages at their time', () => {
  const thread = notesInThread(rows, [note('N1', '2026-10-28 11:00:00.123456'), note('N2', '2026-10-28 13:00:00')])
  assert.deepEqual(thread.map(row => row.name), ['M1', 'N1', 'M2', 'N2'])
  assert.equal(thread[1].note.body, 'Check stock')
})

test('removed notes and notes outside the loaded messages stay out of the thread', () => {
  const notes = [note('N0', '2026-10-28 09:00:00'), note('N1', '2026-10-28 11:00:00', { deleted: true }), note('N2', '2026-10-28 13:00:00')]
  assert.deepEqual(notesInThread(rows, notes, { more: true, newer: true }).map(row => row.name), ['M1', 'M2'])
  assert.deepEqual(notesInThread(rows, notes).map(row => row.name), ['N0', 'M1', 'M2', 'N2'])
  assert.deepEqual(notesInThread([], [note('N1', '2026-10-28 11:00:00')]).map(row => row.name), ['N1'])
})

test('a pending message without a time keeps its place', () => {
  const thread = notesInThread([...rows, { name: 'local-1', _pending: true }], [note('N1', '2026-10-28 13:00:00')])
  assert.deepEqual(thread.map(row => row.name), ['M1', 'M2', 'local-1', 'N1'])
})

test('added notes show in the thread at once and live note changes come from Socket.IO', async () => {
  const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
  const notes = await read('composables/useThreadNotes.js'), messages = await read('components/ConnectedMessages.vue')
  assert.match(notes, /useRealtimeRefresh\(\[\], \['comments'\], load\)/)
  assert.doesNotMatch(notes, /setInterval|setTimeout/)
  assert.equal((messages.match(/@added="showToast\('Note added'\); threadNotes\.load\(\)"/g) || []).length, 3)
  assert.match(messages, /:notes="threadNotes\.items\.value"/)
  const thread = await read('components/messages/MessageThread.vue')
  assert.match(thread, /<article v-if="message\.note" class="note-bubble"/)
  assert.match(thread, /Only your team sees this/)
})
