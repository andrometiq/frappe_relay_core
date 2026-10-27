import test from 'node:test'
import assert from 'node:assert/strict'
import { chatFolderStore, folderLabel } from '../src/services/chatFolders.js'

function fakeApi(rows) {
  const calls = []
  const api = async (method, values, write) => {
    calls.push([method, values, write])
    return method === 'chat_folders.folders' ? rows() : { name: 'F1', folder: values.folder }
  }
  return { api, calls }
}

test('every folder change writes, then reloads the shared list', async () => {
  let rows = []
  const { api, calls } = fakeApi(() => rows)
  const store = chatFolderStore(api)
  rows = [{ name: 'F1', folder_name: 'Follow up', count: 0 }]
  await store.create('Follow up')
  assert.deepEqual(calls.slice(0, 2), [['chat_folders.create', { folder_name: 'Follow up' }, true], ['chat_folders.folders', undefined, undefined]])
  assert.equal(store.folders.value[0].folder_name, 'Follow up')
  await store.rename('F1', 'Later')
  await store.remove('F1')
  assert.deepEqual(calls.filter(call => call[2]).map(call => call[0]), ['chat_folders.create', 'chat_folders.rename', 'chat_folders.delete'])
  assert.equal(store.changes.value, 3)
})

test('moving into no folder sends an empty folder', async () => {
  const { api, calls } = fakeApi(() => [])
  const store = chatFolderStore(api)
  await store.move('CON-1', 'F1')
  await store.move('CON-1', null)
  assert.deepEqual(calls.filter(call => call[0] === 'inbox.update').map(call => call[1]),
    [{ contact: 'CON-1', folder: 'F1' }, { contact: 'CON-1', folder: '' }])
  assert.deepEqual(store.moved.value, { contact: 'CON-1', folder: '' })
})

test('a slower older list never replaces a newer one', async () => {
  const pending = []
  const store = chatFolderStore(() => new Promise(resolve => pending.push(resolve)))
  const first = store.load(), second = store.load()
  pending[1]([{ name: 'NEW' }]); pending[0]([{ name: 'OLD' }])
  await Promise.all([first, second])
  assert.deepEqual(store.folders.value, [{ name: 'NEW' }])
})

test('folder labels come from my folder list', () => {
  const folders = [{ name: 'F1', folder_name: 'Follow up' }]
  assert.equal(folderLabel(folders, 'F1'), 'Follow up')
  assert.equal(folderLabel(folders, 'F2'), '')
  assert.equal(folderLabel(folders, null), '')
})
