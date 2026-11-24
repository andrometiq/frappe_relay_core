import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch } from 'vue'

const read = path => readFile(new URL(path, import.meta.url), 'utf8')
const source = await read('../src/components/messages/InboxFilterPanel.vue')
const choice = await read('../src/components/fields/ChoiceField.vue')
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
const make = new Function('computed', 'nextTick', 'onBeforeUnmount', 'ref', 'watch', 'defineProps', 'defineModel', 'defineEmits', 'useMobileLayout', 'coreApi', 'recordTitle', 'NO_RECORD', 'withoutFilters',
  script + '\nreturn { open, filters, panel, chooseRecord };')
const element = (selector = '') => ({ contains: () => false, querySelector: () => null, closest: wanted => wanted === selector ? {} : null })

test('picking a record in the floating results keeps the filter panel open and sets the record', { timeout: 3000 }, async t => {
  assert.match(choice, /<Teleport to="body">\s*<div v-if="open" ref="results" class="choice-results"/, 'The record results float in the page body')
  const original = { document: globalThis.document, addEventListener: globalThis.addEventListener, removeEventListener: globalThis.removeEventListener }
  const listeners = new Map()
  globalThis.document = { addEventListener: (name, listener) => listeners.set(name, listener), removeEventListener: name => listeners.delete(name) }
  globalThis.addEventListener = globalThis.removeEventListener = () => {}
  const scope = effectScope()
  t.after(() => { scope.stop(); Object.assign(globalThis, original) })
  const models = { open: ref(false), medium: ref('all'), modelValue: ref({ channels: [], businessType: 'Customer', businessName: '', businessLabel: '' }) }
  const state = scope.run(() => make(computed, nextTick, () => {}, ref, watch, () => ({ anchor: undefined, options: [], mediums: [] }), name => models[typeof name === 'string' ? name : 'modelValue'], () => () => {},
    () => ref(false), async () => [], row => row, '__none__', value => value))
  state.panel.value = element()
  state.open.value = true
  await nextTick()

  listeners.get('pointerdown')({ target: element('.choice-results') })
  assert.equal(state.open.value, true, 'A press on a record result is not a press outside the panel')
  state.chooseRecord('CUST-1')
  assert.deepEqual(state.filters.value, { channels: [], businessType: 'Customer', businessName: 'CUST-1', businessLabel: 'CUST-1' })

  listeners.get('pointerdown')({ target: element() })
  assert.equal(state.open.value, false, 'A press elsewhere still closes the panel')
})
