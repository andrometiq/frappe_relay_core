import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { selectMessages, selectableMessage } from '../src/services/messageSelection.js'
import { groupSends } from '../src/services/sendGroups.js'
const rows = Array.from({ length: 60 }, (_, i) => ({ name: String(i), content: 'Line ' + i }))

test('click and tap toggle messages; shift adds a chronological range', () => {
  let selected = selectMessages(rows, [], '1')
  selected = selectMessages(rows, selected, '4', '1', true)
  assert.deepEqual(selected, ['1', '2', '3', '4'])
  assert.deepEqual(selectMessages(rows, selected, '2'), ['1', '3', '4'])
  assert.deepEqual(selectMessages(rows, [], '1', '4', true), ['1', '2', '3', '4'])
})
test('selection is bounded and excludes internal notes and pending messages', () => {
  const selected = rows.slice(0, 50).map(row => row.name)
  assert.equal(selectMessages(rows, selected, '50'), selected)
  assert.equal(selectMessages(rows, selected, '59', '0', true), selected)
  for (const row of [{ name: 'pending', _pending: true }, { name: 'note', note: {} }]) {
    assert.deepEqual(selectMessages([row], [], row.name), [])
  }
  assert.deepEqual(selectMessages([], ['old'], 'missing'), ['old'])
})
test('a message that shows nothing is not selectable, even inside a shift range', () => {
  const shown = [{ name: 'a', content: 'Quantity 40' }, { name: 'blank', content: '  ' }, { name: 'b', content: 'Rate 125' },
    { name: 'photo', message_type: 'photo', content: '' }, { name: 'template', message_data: { kind: 'text', text: '', template: { name: 'order' } } }]
  assert.equal(selectableMessage(shown[1]), false)
  assert.deepEqual(selectMessages(shown, ['a'], 'template', 'a', true), ['a', 'b', 'photo', 'template'])
})

const source = await readFile(new URL('../src/components/messages/MessageThread.vue', import.meta.url), 'utf8')
const script = source.split('<script setup>')[1].split('</script>')[0].replace(/^import .*\n/gm, '')
function thread(t, rows) {
  const props = reactive({ rows, selected: 'LOCAL-CONTACT', canComment: true, notes: [] })
  const events = [], cleanups = [], scope = effectScope()
  const scrolledTo = []
  const globals = { ref, computed, watch, nextTick, selectMessages, selectableMessage, groupSends,
    defineProps: () => props, defineEmits: () => (...args) => events.push(args), inject: (_, fallback) => fallback,
    useMobileLayout: () => ref(true), useRealtimeRefresh() {}, useLoadMore() {},
    useMessageInfo: () => ({ close() {} }), coreApi: async () => ({ readers: [] }),
    createScrollHold: () => ({ apply() {}, toBottom() {}, toMessage: name => { scrolledTo.push(name); return true } }),
    onMounted() {}, onBeforeUnmount: fn => cleanups.push(fn),
    document: { visibilityState: 'hidden', removeEventListener() {} }, window: { removeEventListener() {} },
    navigator: { vibrate() {} } }
  const state = scope.run(() => new Function(...Object.keys(globals), script + '\nreturn { selecting, selection, startSelection, toggleSelection, ticketFromSelection, cancelSelection, pressStart, pressEnd, pressMove };')(...Object.values(globals)))
  t.after(() => { scope.stop(); cleanups.forEach(fn => fn()) })
  return { ...state, props, events, scrolledTo }
}
const click = () => ({ type: 'click', preventDefault() {}, stopPropagation() {} })
const touch = { pointerType: 'touch', clientX: 0, clientY: 0 }

test('ticket submission retains selected evidence evicted from the paging window', async t => {
  const recent = { name: 'LOCAL-RECENT', content: 'Please review invoice 125', business_name: 'LOCAL-1' }
  const older = { name: 'LOCAL-OLDER', content: 'The quantity is 40', business_name: 'LOCAL-1' }
  const view = thread(t, [recent])
  view.startSelection(recent)
  view.props.rows = [older, ...Array.from({ length: 299 }, (_, i) => ({ name: 'LOCAL-' + i }))]
  await nextTick()
  view.toggleSelection(older, click())
  assert.deepEqual(view.selection.value, [recent.name, older.name])
  view.ticketFromSelection()
  assert.deepEqual(view.events.at(-1), ['ticket', [recent, older]])
  assert.equal(view.selecting.value, false)
  assert.deepEqual(view.selection.value, [])

  // Another chat or thread mounts a new thread view (it is keyed by chat, channel and endpoint), so no selection carries over.
  const chat = await readFile(new URL('../src/components/ConnectedMessages.vue', import.meta.url), 'utf8')
  assert.match(chat, /<MessageThread v-else :key="active \+ ':' \+ channel \+ ':' \+ state\.endpoint\.value"/)
})

test('a 1.2 second phone press consumes its release click and the next tap toggles normally', t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const message = { name: 'LOCAL-PRESS', content: 'Quantity 40' }, view = thread(t, [message])
  view.pressStart(message, touch)
  t.mock.timers.tick(450)
  assert.deepEqual(view.selection.value, [message.name])
  t.mock.timers.tick(750)
  view.pressEnd({ type: 'pointerup' })
  view.pressEnd({ type: 'pointerleave' })
  view.toggleSelection(message, click())
  assert.deepEqual(view.selection.value, [message.name])
  view.pressStart(message, touch)
  view.pressEnd({ type: 'pointerup' })
  view.toggleSelection(message, click())
  assert.deepEqual(view.selection.value, [])
})

test('scrolling and cancelled presses do not select; a missing release click does not swallow the next tap', t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const message = { name: 'LOCAL-CANCEL', content: 'Quantity 40' }, view = thread(t, [message])
  for (const cancel of [() => view.pressMove({ clientX: 0, clientY: 11 }), () => view.pressEnd({ type: 'pointercancel' })]) {
    view.pressStart(message, touch)
    t.mock.timers.tick(200)
    cancel()
    t.mock.timers.tick(1000)
    assert.equal(view.selecting.value, false)
  }
  view.pressStart(message, touch)
  t.mock.timers.tick(1200)
  view.pressEnd({ type: 'pointerup' })
  view.pressStart(message, touch)
  view.pressEnd({ type: 'pointerup' })
  view.toggleSelection(message, click())
  assert.deepEqual(view.selection.value, [])
})


test('starting selection brings the chosen message into the reserved viewport', async t => {
  const message = { name: 'LOCAL-FIRST', content: 'Quantity 40' }
  const view = thread(t, [message])
  await view.startSelection(message)
  assert.deepEqual(view.scrolledTo, [message.name])
})

test('cancelling selection before layout does not move the reader', async t => {
  const message = { name: 'LOCAL-CANCELLED', content: 'Quantity 40' }
  const view = thread(t, [message])
  const selecting = view.startSelection(message)
  view.cancelSelection()
  await selecting
  assert.deepEqual(view.scrolledTo, [])
})

test('the selection checkbox takes the avatar column and the outline stays inside the row', async () => {
  const style = source.split('<style')[1]
  assert.doesNotMatch(style, /is-selecting[^}]*padding-left/, 'Text keeps its column, so the avatar never covers it')
  assert.match(style, /\.is-selecting \.message-group-avatar, \.conversation-bubble\.is-selecting > \.message-footer > time \{ visibility:hidden; \}/)
  assert.match(style, /\.is-selected \{ outline:2px solid var\(--relay-accent\); outline-offset:-2px; \}/)
  const mobile = await readFile(new URL('../src/mobile.css', import.meta.url), 'utf8')
  assert.match(mobile, /\.is-mine>\.message-selection-check\{left:auto;right:20px\}/, 'On a phone own messages keep the checkbox on the avatar side')
})
