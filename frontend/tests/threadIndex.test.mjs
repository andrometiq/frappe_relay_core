import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dayDividers, dayLabel, groupStarts, isMine, quoteIndex, senderKey } from '../src/components/messages/threadIndex.js'

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

test('messages group by sender: a new group starts on the other side, another contact, a note, the unread line, a new day or a 10 minute gap', () => {
  const at = time => '2026-10-01 ' + time
  const message = (name, direction, time, contact = 'C1') => ({ name, direction, relay_contact: contact, sent_at: at(time) })
  const rows = [message('M1', 'Incoming', '10:00:00'), message('M2', 'Incoming', '10:04:00'), message('M3', 'Outgoing', '10:05:00'),
    message('M4', 'Outgoing', '10:06:00'), { name: 'N1', note: { body: 'note' }, sent_at: at('10:07:00') }, message('M5', 'Outgoing', '10:08:00'),
    message('M6', 'Outgoing', '10:30:00'), message('M7', 'Incoming', '10:31:00', 'C2'), message('M8', 'Incoming', '10:32:00', 'C2'),
    message('M9', 'Incoming', '10:33:00', 'C2'), { ...message('M10', 'Incoming', '10:34:00', 'C2'), sent_at: '2026-10-02 00:01:00' }]
  assert.deepEqual([...groupStarts(rows, 'M9')], ['M1', 'M3', 'M5', 'M6', 'M7', 'M9', 'M10'])
  assert.deepEqual([...groupStarts([])], [])
})

test('my own sends sit on the left; the contact, colleagues and automation sit on the right, each in their own group', () => {
  const me = 'anitha@example.invalid', at = time => '2026-10-01 ' + time
  const rows = [
    { name: 'M1', direction: 'Incoming', relay_contact: 'C1', sent_at: at('10:00:00') },
    { name: 'M2', direction: 'Outgoing', sender: { user: me }, sent_at: at('10:01:00') },
    { name: 'M3', direction: 'Outgoing', _pending: true, sent_at: at('10:02:00') },
    { name: 'M4', direction: 'Outgoing', sender: { user: 'prakash@example.invalid' }, sent_at: at('10:03:00') },
    { name: 'M5', direction: 'Outgoing', sender: { automated: 1, name: 'Automation' }, sent_at: at('10:04:00') },
    { name: 'M6', direction: 'Outgoing', sent_at: at('10:05:00') }]
  assert.deepEqual(rows.map(row => isMine(row, me)), [false, true, true, false, false, false], 'A row without a sender is not claimed as mine')
  assert.equal(isMine(rows[1], ''), false, 'Without a session user nothing is mine')
  assert.deepEqual(rows.map(row => senderKey(row, me)), ['in:C1', 'me', 'me', 'out:prakash@example.invalid', 'automation', 'out:'])
  assert.deepEqual([...groupStarts(rows, '', me)], ['M1', 'M2', 'M4', 'M5', 'M6'], 'A send in flight joins my group')
})

test('the thread shows the sender head once per group', async () => {
  const thread = await readFile(new URL('../src/components/messages/MessageThread.vue', import.meta.url), 'utf8')
  assert.match(thread, /const starts = computed\(\(\) => groupStarts\(threadRows\.value, props\.unread, me\)\)/)
  assert.match(thread, /'is-mine': isMine\(message, me\),\s*'is-other': !isMine\(message, me\)/)
  assert.match(thread, /<header v-if="starts\.has\(message\.name\)" class="message-group-head">/)
  assert.match(thread, /v-memo="\[starts\.has\(message\.name\),/, 'A row repaints when it starts or stops a group')
})
