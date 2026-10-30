<script setup>
import { inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, ErrorMessage } from '@relay/ui'
import WorkspaceHeading from './WorkspaceHeading.vue'
import IncomingWorkspace from './IncomingWorkspace.vue'
import ContactDetails from './ContactDetails.vue'
import ContactImportDialog from './ContactImportDialog.vue'
import NewContactDialog from './NewContactDialog.vue'
import BusinessDirectory from './messages/BusinessDirectory.vue'
import { closeRoute, openRoute, routeTab } from '../useViewRoute'
const capabilities = inject('relayCapabilities')
const tab = ref(routeTab(location.hash, 'contacts'))
const exporting = ref(false), exportError = ref('')
async function exportContacts() {
  exporting.value = true; exportError.value = ''
  try {
    const response = await fetch('/api/method/relay_core.contact_import.export', { credentials: 'same-origin' })
    if (!response.ok) throw Error('Export failed')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob), link = document.createElement('a')
    link.href = url; link.download = 'Relay contacts.xlsx'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch { exportError.value = 'Could not export contacts. Check your connection and permissions, then try again.' }
  finally { exporting.value = false }
}
const selected = ref(''), creating = ref(false), importing = ref(false), revision = ref(0)
function select(contact) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '')
  params.set('contact', contact)
  openRoute('#/contacts?' + params, !!selected.value)
  selected.value = contact
}
function close() { closeRoute('#/contacts'); selected.value = '' }
function readRoute() {
  tab.value = routeTab(location.hash, 'contacts')
  selected.value = new URLSearchParams(location.hash.split('?')[1] || '').get('contact') || ''
}
onMounted(() => { readRoute(); window.addEventListener('popstate', readRoute); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => { window.removeEventListener('popstate', readRoute); window.removeEventListener('hashchange', readRoute) })
</script>
<template>
  <section class="v1-screen contacts-page">
    <template v-if="tab === 'unlinked' && capabilities.manage">
      <nav class="v1-tabs" aria-label="Contact views"><Button icon="chevron-left" label="Contacts" variant="ghost" @click="tab = 'contacts'" /></nav>
      <IncomingWorkspace />
    </template>
    <div v-else class="v1-content">
      <WorkspaceHeading description="People and their linked business records.">
        <Button v-if="capabilities.contact_transfer" class="contact-import-trigger" label="Export contacts" icon="download" variant="outline" :loading="exporting" :disabled="exporting" @click="exportContacts" />
        <Button v-if="capabilities.contact_transfer" class="contact-import-trigger" label="Import contacts" icon="upload" variant="outline" @click="importing = true" />
        <Button v-if="capabilities.manage" label="New senders" icon="user-check" variant="ghost" @click="tab = 'unlinked'" />
        <Button v-if="capabilities.manage" label="New contact" icon="plus" variant="solid" @click="creating = true" />
      </WorkspaceHeading>
      <ErrorMessage v-if="exportError" :message="exportError" />
      <div class="v1-detail-grid contacts-grid" :class="{ 'is-browse': !selected, 'has-contact': selected }">
        <BusinessDirectory :key="revision" contacts @contact="select" @navigate="selected = ''" />
        <ContactDetails v-if="selected" :key="selected" :contact="selected" dismissible @close="close" />
      </div>
    </div>
    <ContactImportDialog v-if="capabilities.contact_transfer" v-model="importing" @imported="revision++" />
    <NewContactDialog v-if="capabilities.manage" v-model="creating" @created="result => select(result.contact)" />
  </section>
</template>

<style scoped>
.contacts-page :deep(.contact-import-trigger) { min-height:44px; }
.contacts-grid.is-browse { grid-template-columns:minmax(0,1fr); }
.contacts-grid.is-browse :deep(.business-tiles) { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr)); align-content:start; }
@media (max-width:768px) {
  .contacts-grid.has-contact > :deep(.business-browser) { display:none; }
  .contacts-page :deep(:is(button,input,select,a,summary)) { min-height:44px !important; min-width:44px; }
}
</style>
