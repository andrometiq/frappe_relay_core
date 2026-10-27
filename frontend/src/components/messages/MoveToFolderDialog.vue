<script setup>
import { ref, watch } from 'vue'
import { Button, Dialog, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { useChatFolders } from '../../composables/useChatFolders'
import { useTask } from '../../composables/useTask'
const props = defineProps({ modelValue: Boolean, contact: String, current: String })
const emit = defineEmits(['update:modelValue', 'moved'])
const { folders, load, create, move } = useChatFolders()
const { busy, error, run } = useTask()
const newName = ref('')
watch(() => props.modelValue, open => {
  if (!open) return
  newName.value = ''; error.value = ''
  run(load)
})
async function moveTo(folder) {
  const result = await run(() => move(props.contact, folder))
  if (error.value) return
  emit('moved', result)
  emit('update:modelValue', false)
}
async function createAndMove() {
  const folder = await run(() => create(newName.value))
  if (folder) await moveTo(folder.name)
}
</script>
<template>
  <Dialog :model-value="modelValue" :options="{ title: 'Move to folder', size: 'sm' }" @update:model-value="value => emit('update:modelValue', value)">
    <ErrorMessage :message="error" />
    <div class="folder-choices" role="list" aria-label="My folders">
      <button v-for="folder in folders" :key="folder.name" type="button" role="listitem" class="folder-choice" :aria-current="folder.name === current" :disabled="busy || folder.name === current" @click="moveTo(folder.name)">
        <FeatherIcon name="folder" :size="15" /><span>{{ folder.folder_name }}</span><small v-if="folder.name === current">Current</small>
      </button>
      <p v-if="!folders.length" class="text-xs text-ink-gray-5">You have no folders yet. Create one below.</p>
    </div>
    <form class="folder-new" @submit.prevent="newName.trim() && createAndMove()">
      <TextInput v-model="newName" aria-label="New folder name" placeholder="New folder name" maxlength="50" />
      <Button type="submit" label="Create and move" :disabled="busy || !newName.trim()" />
    </form>
    <template v-if="current" #actions><Button label="Remove from folder" icon="folder-minus" :disabled="busy" @click="moveTo('')" /></template>
  </Dialog>
</template>

<style scoped>
.folder-choices { display:flex; flex-direction:column; gap:2px; max-height:280px; overflow-y:auto; margin:4px 0 12px; }
.folder-choice { display:flex; align-items:center; gap:8px; min-height:36px; padding:6px 10px; border-radius:6px; font-size:13px; text-align:left; }
.folder-choice:hover:not(:disabled) { background:var(--surface-gray-2); }
.folder-choice[aria-current=true] { background:var(--surface-blue-1); color:var(--ink-blue-3); font-weight:600; }
.folder-choice small { margin-left:auto; font-weight:400; }
.folder-new { display:flex; gap:8px; align-items:center; }
.folder-new > :first-child { flex:1; }
</style>
