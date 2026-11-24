<script setup>
import { onMounted, ref } from 'vue'
import { Button, Dialog, ErrorMessage, TextInput } from '@relay/ui'
import { useChatFolders } from '../../composables/useChatFolders'
import { useTask } from '../../composables/useTask'
// Create, rename and delete dialogs for my personal folders; the inbox sidebar lists them. The selected folder id is the model.
const selected = defineModel({ type: String, default: '' })
const { load, create, rename, remove } = useChatFolders()
const { busy, error, run } = useTask()
const editing = ref(null), name = ref(''), deleting = ref(null)
onMounted(() => run(load))
function openEditor(folder = {}) {
  error.value = ''
  editing.value = folder
  name.value = folder.folder_name || ''
}
function confirmRemove(folder) { error.value = ''; deleting.value = folder }
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
defineExpose({ openEditor, confirmRemove })
</script>
<template>
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
