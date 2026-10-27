<script setup>
import { computed, onMounted, ref } from 'vue'
import { Button, Dialog, Dropdown, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { useChatFolders } from '../../composables/useChatFolders'
import { useTask } from '../../composables/useTask'
import { countLabel } from '../../services/queueCounts'
// My personal folders as inbox filter tabs; the selected folder id is the model.
const selected = defineModel({ type: String, default: '' })
const { folders, load, create, rename, remove } = useChatFolders()
const { busy, error, run } = useTask()
const editing = ref(null), name = ref(''), deleting = ref(null)
const current = computed(() => folders.value.find(folder => folder.name === selected.value))
const folderActions = computed(() => [
  { label: 'Rename folder', icon: 'edit-3', onClick: () => openEditor(current.value) },
  { label: 'Delete folder', icon: 'trash', onClick: () => { error.value = ''; deleting.value = current.value } },
])
onMounted(() => run(load))
function openEditor(folder = {}) {
  error.value = ''
  editing.value = folder
  name.value = folder.folder_name || ''
}
async function save() {
  const folder = editing.value
  const result = await run(() => folder.name ? rename(folder.name, name.value) : create(name.value))
  if (!result) return
  editing.value = null
  selected.value = result.name
}
async function confirmDelete() {
  const folder = deleting.value
  await run(() => remove(folder.name))
  if (error.value) return
  deleting.value = null
  if (selected.value === folder.name) selected.value = ''
}
</script>
<template>
  <nav class="v1-queues inbox-folders" aria-label="Folders">
    <span class="inbox-folders__label"><FeatherIcon name="folder" :size="14" />Folders</span>
    <button type="button" class="inbox-folders__new" aria-label="New folder" title="New folder" @click="openEditor()"><FeatherIcon name="folder-plus" :size="14" /><span v-if="!folders.length">New folder</span></button>
    <button v-for="folder in folders" :key="folder.name" type="button" :aria-pressed="selected === folder.name"
      :aria-label="countLabel(folder.count) ? `${folder.folder_name}, ${folder.count} conversations` : folder.folder_name"
      @click="selected = selected === folder.name ? '' : folder.name">{{ folder.folder_name }}<span v-if="countLabel(folder.count)" class="queue-count" aria-hidden="true">{{ countLabel(folder.count) }}</span></button>
    <Dropdown v-if="current" :options="folderActions"><Button icon="more-horizontal" variant="ghost" aria-label="Folder actions" title="Folder actions" /></Dropdown>
  </nav>
  <ErrorMessage v-if="error && !editing && !deleting" class="px-4" :message="error" />
  <Dialog :model-value="Boolean(editing)" :options="{ title: editing?.name ? 'Rename folder' : 'New folder', size: 'sm' }" @update:model-value="value => { if (!value) editing = null }">
    <form id="relay-folder-form" @submit.prevent="name.trim() && save()">
      <TextInput v-model="name" aria-label="Folder name" placeholder="e.g. Follow up" maxlength="50" autofocus />
      <p class="text-xs text-ink-gray-5 mt-2">Only you see your folders.</p>
    </form>
    <ErrorMessage :message="error" />
    <template #actions><Button variant="solid" type="submit" form="relay-folder-form" :label="editing?.name ? 'Rename' : 'Create folder'" :disabled="busy || !name.trim()" /></template>
  </Dialog>
  <Dialog :model-value="Boolean(deleting)" :options="{ title: 'Delete folder', size: 'sm' }" @update:model-value="value => { if (!value) deleting = null }">
    <p class="text-sm">Delete “{{ deleting?.folder_name }}”? Its conversations stay in your inbox.</p>
    <ErrorMessage :message="error" />
    <template #actions><Button theme="red" variant="solid" label="Delete folder" :disabled="busy" @click="confirmDelete" /></template>
  </Dialog>
</template>

<style scoped>
.inbox-folders { align-items:center; }
.inbox-folders__label { display:flex; align-items:center; gap:5px; padding:0 6px 0 2px; color:var(--ink-gray-5); font-size:12px; }
.inbox-folders__new { gap:5px; color:var(--ink-gray-6); }
.queue-count { margin-left:5px; color:var(--ink-gray-5); font-size:12px; font-weight:400; font-variant-numeric:tabular-nums; }
[aria-pressed=true] > .queue-count { color:inherit; font-weight:600; }
</style>
