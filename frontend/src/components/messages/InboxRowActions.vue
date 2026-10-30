<script setup>
import { computed, inject, ref } from 'vue'
import { Dialog, Dropdown, toast } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useChatFolders } from '../../composables/useChatFolders'
import { canLinkRow, readStateRequest, rowActionKeys } from '../../services/inboxRows'
import ContactDetails from '../ContactDetails.vue'
import MoveToFolderDialog from './MoveToFolderDialog.vue'

/** The chat list row menu: read state, star, folder and link. A business row changes the read state of all its chats. */
const emit = defineEmits(['changed', 'error'])
const capabilities = inject('relayCapabilities')
const { move } = useChatFolders()
const menu = ref(), row = ref(null), moving = ref(false), linking = ref(false)
const canLink = item => canLinkRow(item, capabilities.value.manage)
const options = computed(() => {
  const item = row.value
  if (!item) return []
  const actions = {
    read: { label: 'Mark as read', icon: 'check', onClick: () => markRead(item, true) },
    unread: { label: 'Mark as unread', icon: 'circle', onClick: () => markRead(item, false) },
    star: { label: item.starred ? 'Remove star' : 'Star', icon: 'star', onClick: () => star(item) },
    move: { label: 'Move to folder', icon: 'folder-input', onClick: () => { moving.value = true } },
    unfile: { label: 'Remove from folder', icon: 'folder-minus', onClick: () => run(() => move(item.name, ''), 'Removed from folder') },
    link: { label: 'Link to business record', icon: 'link', onClick: () => link(item) },
  }
  return rowActionKeys(item, { folders: capabilities.value.folders, manage: capabilities.value.manage }).map(key => actions[key])
})

async function run(action, message) {
  try { await action(); toast(message) }
  catch (e) { emit('error', e.message) }
}
function markRead(item, read) {
  return run(async () => {
    const result = await coreApi('message_reads.mark_chat', readStateRequest(item, read), true)
    emit('changed', item, { unread: result.unread })
  }, read ? 'Marked as read' : 'Marked as unread')
}
function star(item) {
  const starred = item.starred ? 0 : 1
  return run(async () => {
    await coreApi('inbox.update', { contact: item.name, starred }, true)
    emit('changed', item, { starred })
  }, starred ? 'Starred' : 'Star removed')
}
function link(item) { row.value = item; linking.value = true }
function linked() {
  linking.value = false
  emit('changed', row.value, { unlinked: false })
}
// A right-click and an Android long-press both fire, so a second open right after the first is ignored.
let openedAt = 0
function open(event, target, item) {
  if (Date.now() - openedAt < 700) return
  openedAt = Date.now()
  row.value = item
  menu.value.toggle(event, target)
}
defineExpose({ open, link, canLink })
</script>
<template>
  <Dropdown ref="menu" :options="options" />
  <MoveToFolderDialog v-if="capabilities.folders" v-model="moving" :contact="row?.name" :current="row?.folder" @moved="toast('Moved to folder')" />
  <Dialog v-model="linking" :options="{ title: 'Link to a business record', size: 'md' }">
    <ContactDetails v-if="linking && row" :contact="row.contact" compact link @changed="linked" @close="linking = false" />
  </Dialog>
</template>
