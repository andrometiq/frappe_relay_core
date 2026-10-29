import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { selectMessages, selectableMessage } from '../src/services/messageSelection.js'
import { groupSends } from '../src/services/sendGroups.js'
const rows = Array.from({ length: 60 }, (_, i) => ({ name: String(i) }))

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

const source = await readFile(new URL('../src/components/messages/MessageThread.vue', import.meta.url), 'utf8')
const script = source.split('<script setup>')[1].split('</script>')[0].replace(/^import .*\n/gm, '')
function thread(t, rows) {
  const props = reactive({ rows, selected: 'LOCAL-CONTACT', canComment: true, notes: [] })
  const events = [], cleanups = [], scope = effectScope()
  const globals = { ref, computed, watch, nextTick, selectMessages, selectableMessage, groupSends,
    defineProps: () => props, defineEmits: () => (...args) => events.push(args), inject: (_, fallback) => fallback,
    useMobileLayout: () => ref(true), useRealtimeRefresh() {}, useLoadMore() {},
    useMessageInfo: () => ({ close() {} }), coreApi: async () => ({ readers: [] }),
    createScrollHold: () => ({ apply() {}, toBottom() {}, toMessage: () => false }),
    onMounted() {}, onBeforeUnmount: fn => cleanups.push(fn),
    document: { visibilityState: 'hidden', removeEventListener() {} }, window: { removeEventListener() {} },
    navigator: { vibrate() {} } }
  const state = scope.run(() => new Function(...Object.keys(globals), script + '\nreturn { selecting, selection, startSelection, toggleSelection, ticketFromSelection, cancelSelection, pressStart, pressEnd, pressMove };')(...Object.values(globals)))
  t.after(() => { scope.stop(); cleanups.forEach(fn => fn()) })
  return { ...state, props, events }
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

  view.startSelection(older)
  view.props.selected = 'OTHER-LOCAL-CONTACT'
  await nextTick()
  assert.deepEqual(view.selection.value, [])
})

test('a 1.2 second phone press consumes its release click and the next tap toggles normally', t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const message = { name: 'LOCAL-PRESS' }, view = thread(t, [message])
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
  const message = { name: 'LOCAL-CANCEL' }, view = thread(t, [message])
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
