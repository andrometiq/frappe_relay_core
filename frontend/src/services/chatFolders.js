import { ref } from 'vue'

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
    create: name => api('chat_folders.create', { folder_name: name }, true).then(changed),
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
