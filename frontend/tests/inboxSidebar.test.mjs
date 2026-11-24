import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, ref } from 'vue'
import { countLabel } from '../src/services/queueCounts.js'
import { folderColor } from '../src/services/chatFolders.js'
import { VIEWS } from '../src/services/inboxFilters.js'

const source = await readFile(new URL('../src/components/messages/InboxSidebar.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')

function sidebar(props) {
  const models = { view: ref('all'), folder: ref(''), channels: ref([]), query: ref(''), open: ref(false) }
  const emitted = []
  const make = new Function('computed', 'defineProps', 'defineEmits', 'defineModel', 'useMobileLayout', 'countLabel', 'folderColor', 'VIEWS',
    script + '\nreturn { sections, active, choose };')
  const state = make(computed, () => props, () => (...args) => emitted.push(args), name => models[name], () => ref(false), countLabel, folderColor, VIEWS)
  return { ...state, ...models, emitted }
}
const numbers = [{ name: 'WA-1', label: 'Sales', address: '+91 1' }, { name: 'WA-2', label: 'Support', address: '+91 2' }]

test('the sidebar lists the server-backed views with server counts, my folders and the WhatsApp numbers', () => {
  const view = sidebar({ counts: { unread: 3, mine: 2, unlinked: 0, all: 9 }, folders: [{ name: 'F1', folder_name: 'Customers', count: 48 }], numbers, canFolders: true })
  const [views, folders, lines] = view.sections.value
  assert.deepEqual(views.items.map(item => [item.label, item.count]), [['All chats', '3'], ['Assigned to me', '2'], ['Starred', null], ['Not linked', null]],
    'Only views with a server count show one, and a zero shows none')
  assert.equal(views.items[0].strong, true)
  assert.deepEqual(folders.items.map(item => [item.key, item.label, item.count, item.menu.map(option => option.label)]),
    [['folder:F1', 'Customers', '48', ['Rename folder', 'Delete folder']]])
  folders.action.onClick()
  assert.deepEqual(view.emitted.at(-1), ['edit-folder', {}])
  assert.deepEqual(lines.items.map(item => item.label), ['Sales · +91 1', 'Support · +91 2'])
  assert.equal(sidebar({ counts: {}, folders: [], numbers: numbers.slice(0, 1), canFolders: false }).sections.value.length, 1, 'No folders feature and one number add no sections')
})

test('a view or folder replaces the other and a number toggles the channel filter', () => {
  const view = sidebar({ counts: {}, folders: [{ name: 'F1', folder_name: 'Customers' }], numbers, canFolders: true })
  view.choose({ key: 'folder:F1' })
  assert.deepEqual([view.folder.value, view.view.value, view.active.value], ['F1', 'all', 'folder:F1'])
  view.choose({ key: 'starred' })
  assert.deepEqual([view.folder.value, view.view.value, view.active.value], ['', 'starred', 'starred'])
  view.choose(view.sections.value[2].items[1])
  assert.deepEqual(view.channels.value, ['WA-2'])
  assert.equal(view.sections.value[2].items[1].selected, true)
  view.choose(view.sections.value[2].items[1])
  assert.deepEqual(view.channels.value, [], 'A second tap clears the number')
  assert.equal(view.view.value, 'starred', 'A number narrows the open view')
})
