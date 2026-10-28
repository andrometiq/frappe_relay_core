import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dayDividers, dayLabel, quoteIndex } from '../src/components/messages/threadIndex.js'

const row = (index, values = {}) => ({ name: 'M' + index, channel: 'CH', sender_endpoint: '91', sent_at: values.at || '2026-10-01 10:00:00',
  provider_context: JSON.stringify({ message_id: 'w' + index, ...(values.reply ? { reply_to_message_id: values.reply } : {}) }) })

test('a reply finds the quoted message of the same chat endpoint', () => {
  const rows = [row(1), row(2, { reply: 'w1' }), { ...row(3, { reply: 'w1' }), sender_endpoint: '92' }, row(4, { reply: 'gone' })]
  const quoted = quoteIndex(rows)
  assert.equal(quoted(rows[1]), rows[0])
  assert.equal(quoted(rows[2]), undefined, 'Another endpoint never quotes this chat')
  assert.equal(quoted(rows[3]), undefined)
  assert.equal(quoted(rows[0]), undefined, 'A message that quotes nothing has no quote')
})

test('a thread render parses each provider context once, not once per pair of messages', () => {
  let parses = 0
  const rows = Array.from({ length: 300 }, (_, index) => {
    const value = row(index, { reply: index ? 'w' + (index - 1) : undefined })
    const context = value.provider_context
    return Object.defineProperty(value, 'provider_context', { get: () => { parses++; return context } })
  })
  const quoted = quoteIndex(rows)
  for (let render = 0; render < 4; render++) for (const message of rows) quoted(message)
  assert.equal(parses, 300)
  assert.equal(quoted(rows[10]), rows[9])
})

test('a day divider starts each new day, with Today and Yesterday by name', () => {
  const today = new Date('2026-10-28T12:00:00')
  const rows = [row(1, { at: '2026-10-26 09:00:00' }), row(2, { at: '2026-10-26 18:00:00' }), row(3, { at: '2026-10-27 08:00:00' }),
    row(4, { at: '2026-10-28 08:00:00' }), { name: 'note', creation: 'not a date' }, row(5, { at: '2026-10-28 09:00:00' })]
  const dividers = dayDividers(rows, today)
  assert.deepEqual([...dividers.keys()], ['M1', 'M3', 'M4', 'M5'], 'A row without a time starts the day again after it, as before')
  assert.equal(dividers.get('M3'), 'Yesterday')
  assert.equal(dividers.get('M4'), 'Today')
  assert.equal(dayLabel(null), '')
})

test('the thread looks quotes and dividers up instead of scanning all rows in every bubble render', async () => {
  const thread = await readFile(new URL('../src/components/messages/MessageThread.vue', import.meta.url), 'utf8')
  assert.match(thread, /const quoted = computed\(\(\) => quoteIndex\(props\.rows \|\| \[\]\)\)/)
  assert.match(thread, /const dividers = computed\(\(\) => dayDividers\(threadRows\.value\)\)/)
  assert.match(thread, /<div v-if="dividers\.has\(message\.name\)" class="message-date-divider">/)
  assert.doesNotMatch(thread, /props\.rows\.find\(|function dayLabel|toLocaleDateString/)
})
