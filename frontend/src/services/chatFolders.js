import { ref } from 'vue'
import { stableSubmission } from './submission.js'

// Personal chat folders: one shared list per app, refreshed after every folder or move change.
export function chatFolderStore(api) {
  const folders = ref([]), changes = ref(0), moved = ref(null)
  let generation = 0
  async function load() {
    const ticket = ++generation
    const rows = await api('chat_folders.folders')
    if (ticket === generation) folders.value = rows
  }
  async function changed(result) {
    changes.value++
    await load()
    return result
  }
  return {
    folders, changes, moved, load,
    create: name => stableSubmission('relay-folder', { folder_name: name },
      key => api('chat_folders.create', { folder_name: name, request_key: key }, true)).then(changed),
    rename: (folder, name) => api('chat_folders.rename', { folder, folder_name: name }, true).then(changed),
    remove: folder => api('chat_folders.delete', { folder }, true).then(changed),
    // An empty folder removes the conversation from its folder.
    move: (contact, folder) => api('inbox.update', { contact, folder: folder || '' }, true).then(result => {
      moved.value = { contact, folder: result.folder || '' }
      return changed(result)
    }),
  }
}

export function folderLabel(folders, id) {
  return folders.find(folder => folder.name === id)?.folder_name || ''
}

// Folders have no stored colour, so each gets a steady one from its id.
export const FOLDER_COLORS = Object.freeze(['#3e63dd', '#30a46c', '#f76b15', '#8e4ec6', '#e5484d', '#12a594'])
export function folderColor(id) {
  let hash = 0
  for (const character of String(id || '')) hash = (hash * 31 + character.codePointAt(0)) >>> 0
  return FOLDER_COLORS[hash % FOLDER_COLORS.length]
}
