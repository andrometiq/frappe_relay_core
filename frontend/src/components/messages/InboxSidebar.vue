<script setup>
import { computed } from 'vue'
import { FeatherIcon, TextInput } from '@relay/ui'
import PageSidebar from '../shell/PageSidebar.vue'
import { useMobileLayout } from '../../composables/useMobileLayout'
import { countLabel } from '../../services/queueCounts'
import { folderColor } from '../../services/chatFolders'
import { VIEWS } from '../../services/inboxFilters'

/** Inbox views, my folders and the WhatsApp numbers: a column beside the chat list on desktop, a sheet on phones. */
const props = defineProps({
  counts: { type: Object, default: () => ({}) }, folders: { type: Array, default: () => [] }, numbers: { type: Array, default: () => [] },
  canFolders: Boolean, subtitle: String,
})
const emit = defineEmits(['start', 'edit-folder', 'delete-folder'])
const view = defineModel('view', { type: String, default: 'all' })
const folder = defineModel('folder', { type: String, default: '' })
const channels = defineModel('channels', { type: Array, default: () => [] })
const query = defineModel('query', { type: String, default: '' })
const open = defineModel('open', { type: Boolean, default: false })
const isMobile = useMobileLayout()
// Only views with a server count show one; All chats shows its unread chats.
const viewCounts = computed(() => ({ all: props.counts.unread, mine: props.counts.mine, unlinked: props.counts.unlinked }))
const sections = computed(() => [
  { key: 'views', items: VIEWS.map(([key, label, icon]) => ({ key, label, icon, count: countLabel(viewCounts.value[key]) || null, strong: key === 'all',
    countLabel: key === 'all' && viewCounts.value.all ? `${viewCounts.value.all} unread chats` : undefined })) },
  ...(props.canFolders ? [{ key: 'folders', title: 'Folders', action: { label: 'New folder', onClick: () => emit('edit-folder', {}) },
    items: props.folders.map(item => ({ key: 'folder:' + item.name, label: item.folder_name, dot: folderColor(item.name), count: countLabel(item.count) || null,
      menu: [{ label: 'Rename folder', icon: 'edit-3', onClick: () => emit('edit-folder', item) }, { label: 'Delete folder', icon: 'trash', onClick: () => emit('delete-folder', item) }] })) }] : []),
  ...(props.numbers.length > 1 ? [{ key: 'numbers', title: 'Numbers', items: props.numbers.map(item => ({ key: 'number:' + item.name, icon: 'phone', tone: 'whatsapp',
    label: [item.label, item.address].filter(Boolean).join(' · '), selected: channels.value.length === 1 && channels.value[0] === item.name })) }] : []),
])
const active = computed(() => folder.value ? 'folder:' + folder.value : view.value)
// A view or folder replaces the other; a number narrows whichever is open and a second tap clears it.
function choose(item) {
  const [kind, name] = item.key.includes(':') ? [item.key.slice(0, item.key.indexOf(':')), item.key.slice(item.key.indexOf(':') + 1)] : ['view', item.key]
  if (kind === 'number') channels.value = item.selected ? [] : [name]
  else if (kind === 'folder') { folder.value = name; view.value = 'all' }
  else { view.value = name; folder.value = '' }
}
</script>

<template>
  <PageSidebar v-model:open="open" class="inbox-side" title="Inbox" :subtitle="subtitle" label="Inbox views" :sections="sections" :active="active" :picker="false" @select="choose">
    <template #actions><button type="button" class="page-side-add inbox-side-new" aria-label="New chat" title="New chat" @click="open = false; emit('start')"><FeatherIcon name="plus" :size="16" /></button></template>
    <template v-if="!isMobile" #top>
      <form class="inbox-side-search inbox-filters" role="search" @submit.prevent>
        <TextInput v-model="query" type="search" aria-label="Search chats" placeholder="Search chats" maxlength="80"><template #prefix><FeatherIcon name="search" :size="14" /></template><template #suffix><kbd aria-hidden="true">Ctrl K</kbd></template></TextInput>
      </form>
    </template>
  </PageSidebar>
</template>
