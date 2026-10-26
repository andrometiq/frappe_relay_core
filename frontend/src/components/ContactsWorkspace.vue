<script setup>
import { recordTitle } from '../services/recordTitle'
import { inject, onMounted, onBeforeUnmount, ref } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import LoadingRows from './LoadingRows.vue'
import WorkspaceState from './WorkspaceState.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import IncomingWorkspace from './IncomingWorkspace.vue'
import ContactDetails from './ContactDetails.vue'
import NewContactDialog from './NewContactDialog.vue'
import { routeTab } from '../useViewRoute'
const capabilities = inject('relayCapabilities')
const tab = ref(routeTab(location.hash, 'contacts'))
const rows = ref([]), query = ref(''), selected = ref(''), busy = ref(false), error = ref(''), more = ref(false), creating = ref(false)
let generation = 0
async function load(append = false) {
  const ticket = ++generation; busy.value = true; error.value = ''
  try {
    const page = await coreApi('api.contact_directory', { query: query.value, after: append ? rows.value.at(-1)?.name : null })
    if (ticket === generation) { rows.value = append ? [...rows.value, ...page.items] : page.items; more.value = !!page.next }
  } catch (e) { if (ticket === generation) { error.value = e.message; rows.value = []; selected.value = '' } }
  finally { if (ticket === generation) busy.value = false }
}
function created(result) { selected.value = result.contact; load() }
function readRoute() { tab.value = routeTab(location.hash, 'contacts') }
onMounted(() => { load(); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => { ++generation; window.removeEventListener('hashchange', readRoute) })
useRealtimeRefresh(['Contact'], ['contacts', 'incoming'], () => load())
</script>
<template>
  <section class="v1-screen">
    <nav class="v1-tabs" aria-label="Contact views"><Button label="Contacts" :variant="tab === 'contacts' ? 'solid' : 'ghost'" @click="tab = 'contacts'" /><Button v-if="capabilities.manage" label="Unlinked / ambiguous senders" :variant="tab === 'unlinked' ? 'solid' : 'ghost'" @click="tab = 'unlinked'" /></nav>
    <IncomingWorkspace v-if="tab === 'unlinked' && capabilities.manage" />
    <div v-else class="v1-content">
      <WorkspaceHeading description="Customer details, channel identities and connected business records."><Button v-if="capabilities.manage" label="New contact" icon="plus" variant="solid" @click="creating = true" /><a class="relay-button" href="/desk/contact/new">New Contact in Desk</a></WorkspaceHeading>
      <form class="workspace-search" role="search" @submit.prevent="load()"><TextInput v-model="query" aria-label="Search Frappe Contacts" placeholder="Search contacts by name" type="search"><template #prefix><FeatherIcon name="search" /></template></TextInput><Button type="submit" label="Search" :loading="busy" /></form>
      <ErrorMessage :message="error" />
      <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !selected }">
        <div class="workspace-records">
          <LoadingRows v-if="busy && !rows.length" label="Loading contacts…" />
          <button v-for="row in rows" :key="row.name" class="workspace-person-row" :aria-pressed="selected === row.name" @click="selected = row.name"><Avatar :label="recordTitle(row, 'Contact')" /><span><strong>{{ recordTitle(row, 'Contact') }}</strong><small>{{ row.mobile_no || 'No mobile number' }}</small></span><FeatherIcon name="chevron-right" /></button>
          <WorkspaceState v-if="!busy && !rows.length && !error" compact title="No contacts match this search." description="Try another name or create a contact in Desk." icon="users"><Button v-if="query" label="Clear search" @click="query = ''; load()" /><a v-else class="relay-button" href="/desk/contact/new">New Contact in Desk</a></WorkspaceState>
          <Button v-if="error" label="Retry contacts" @click="load()" /><Button v-if="more" label="More contacts" :loading="busy" @click="load(true)" />
        </div>
        <ContactDetails v-if="selected" :key="selected" :contact="selected" dismissible @close="selected = ''" />
      </div>
    </div>
    <NewContactDialog v-if="capabilities.manage" v-model="creating" @created="created" />
  </section>
</template>
