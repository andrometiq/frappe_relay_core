import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { CHAT_TICKET_PREVIEW, chatTicketRequest, chatTicketsStore, emptyChatTicketFilters, hasChatTicketFilters } from '../src/services/chatTickets.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}
function fakeApi() {
  const calls = [], pending = []
  const api = (method, values) => { const step = deferred(); calls.push([method, values]); pending.push(step); return step.promise }
  return { api, calls, pending }
}
const rows = (from, count) => Array.from({ length: count }, (_, i) => ({ name: 'TKT-' + String(from - i).padStart(5, '0') }))

test('a chat ticket request leaves out empty filters and sends picked statuses as one list', () => {
  assert.deepEqual(chatTicketRequest('RELAY-CON-1', emptyChatTicketFilters()), { contact: 'RELAY-CON-1', limit: 20 })
  assert.deepEqual(chatTicketRequest('RELAY-CON-1', { statuses: ['Open', 'Waiting'], assignedTo: 'a@example.invalid', ticketType: 'Delivery', query: '  late parcel ' }, 'TKT-00021', 10),
    { contact: 'RELAY-CON-1', limit: 10, ticket_status: '["Open","Waiting"]', assigned_to: 'a@example.invalid', ticket_type: 'Delivery', query: 'late parcel', after: 'TKT-00021' })
  assert.equal(hasChatTicketFilters(emptyChatTicketFilters()), false)
  assert.ok(hasChatTicketFilters({ ...emptyChatTicketFilters(), query: 'late' }))
})

test('the list loads 20, appends the next 20 once, and a newer filter drops an older page', async () => {
  const { api, calls, pending } = fakeApi()
  const store = chatTicketsStore(api)
  const opened = store.open('RELAY-CON-1'); pending[0].resolve({ items: rows(40, 20), next: { after: 'TKT-00021' } }); await opened
  assert.equal(store.items.value.length, 20)
  const first = store.more(), second = store.more()
  assert.equal(first, second, 'Scrolling twice asks for the next page once')
  assert.equal(calls[1][1].after, 'TKT-00021')
  pending[1].resolve({ items: rows(20, 20), next: null }); await first
  assert.deepEqual([store.items.value.length, store.next.value], [40, null])
  assert.equal(store.more(), null, 'No next page: nothing to load')

  const late = store.open('RELAY-CON-1', { ...emptyChatTicketFilters(), statuses: ['Open'] })
  const stale = store.more()
  assert.equal(stale, null, 'A reset list has no next page yet')
  const newest = store.open('RELAY-CON-1', { ...emptyChatTicketFilters(), query: 'parcel' })
  pending[3].resolve({ items: rows(5, 1), next: null }); await newest
  pending[2].resolve({ items: rows(9, 3), next: null }); await late
  assert.deepEqual(store.items.value.map(row => row.name), ['TKT-00005'], 'The older filter result arrives late and is ignored')
  assert.equal(calls[3][1].query, 'parcel')
})

test('the chat panel shows the newest 10 tickets and the chat screen has no Advanced section', async () => {
  const read = path => readFile(new URL('../src/components/' + path, import.meta.url), 'utf8')
  assert.equal(CHAT_TICKET_PREVIEW, 10)
  assert.match(await read('tickets/ChatTickets.vue'), /chatTicketsStore\(coreApi, CHAT_TICKET_PREVIEW\)/)
  assert.equal((await read('ConnectedMessages.vue')).match(/<ChatTickets v-if="!linking && conversationContact" :contact="conversationContact" \/>/g).length, 2,
    'Desktop details panel and phone info page')
  assert.match(await read('ContactDetails.vue'), /<details v-if="capabilities\.manage && !compact" class="info-section">/)
  const dialog = await read('tickets/ChatTicketsDialog.vue')
  assert.match(dialog, /useDebouncedSearch\(query, reload\)/)
  assert.match(dialog, /useLoadMore\(\{ root, loading: busy, hasMore: \(\) => !!next\.value, error, load: more \}\)/)
})
