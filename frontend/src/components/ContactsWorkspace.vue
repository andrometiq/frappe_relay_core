<script setup>
import { inject, onMounted, onBeforeUnmount, ref } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { frappeRequest } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import LoadingRows from './LoadingRows.vue'
import WorkspaceState from './WorkspaceState.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import IncomingWorkspace from './IncomingWorkspace.vue'
import ContactDetails from './ContactDetails.vue'
const capabilities = inject('relayCapabilities')
const tab = ref(new URLSearchParams(location.hash.split('?')[1]).get('tab') || 'contacts')
const rows = ref([]), query = ref(''), selected = ref(''), busy = ref(false), error = ref(''), more = ref(false)
let generation = 0
async function load(append = false) {
  const ticket = ++generation; busy.value = true; error.value = ''
  try {
    const filters = query.value ? { full_name: ['like', '%' + query.value.replace(/[\\%_]/g, '\\$&') + '%'] } : {}
    const page = await frappeRequest('frappe.client.get_list', { doctype: 'Contact', fields: JSON.stringify(['name', 'full_name', 'mobile_no']), filters: JSON.stringify(filters), order_by: 'name asc', limit_start: append ? rows.value.length : 0, limit_page_length: 31 })
    if (ticket === generation) { rows.value = append ? [...rows.value, ...page.slice(0, 30)] : page.slice(0, 30); more.value = page.length > 30 }
  } catch (e) { if (ticket === generation) error.value = e.message }
  finally { if (ticket === generation) busy.value = false }
}
function readRoute() { tab.value = new URLSearchParams(location.hash.split('?')[1]).get('tab') || 'contacts' }
onMounted(() => { load(); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => { ++generation; window.removeEventListener('hashchange', readRoute) })
useRealtimeRefresh(['Contact'], ['contacts', 'incoming'], () => load())
</script>
<template>
  <section class="v1-screen">
    <nav class="v1-tabs" aria-label="Contact views"><Button label="Contacts" :variant="tab === 'contacts' ? 'solid' : 'ghost'" @click="tab = 'contacts'" /><Button v-if="capabilities.manage" label="Unlinked / ambiguous senders" :variant="tab === 'unlinked' ? 'solid' : 'ghost'" @click="tab = 'unlinked'" /></nav>
    <IncomingWorkspace v-if="tab === 'unlinked' && capabilities.manage" />
    <div v-else class="v1-content">
      <WorkspaceHeading title="Your contacts" description="Customer details, WhatsApp numbers and connected business records." icon="users"><a class="relay-button relay-button--solid" href="/desk/contact/new"><FeatherIcon name="plus" />New Contact in Desk</a></WorkspaceHeading>
      <form class="workspace-search" role="search" @submit.prevent="load()"><TextInput v-model="query" aria-label="Search Frappe Contacts" placeholder="Search contacts by name" type="search"><template #prefix><FeatherIcon name="search" /></template></TextInput><Button type="submit" label="Search" :loading="busy" /></form>
      <ErrorMessage :message="error" />
      <div class="v1-detail-grid">
        <div class="workspace-records">
          <LoadingRows v-if="busy && !rows.length" label="Loading contacts…" />
          <button v-for="row in rows" :key="row.name" class="workspace-person-row" :aria-pressed="selected === row.name" @click="selected = row.name"><Avatar :label="row.full_name || row.name" /><span><strong>{{ row.full_name || row.name }}</strong><small>{{ row.mobile_no || 'No mobile number' }}</small></span><FeatherIcon name="chevron-right" /></button>
          <WorkspaceState v-if="!busy && !rows.length && !error" compact title="No contacts match this search." description="Try another name or create a contact in Desk." icon="users"><Button v-if="query" label="Clear search" @click="query = ''; load()" /><a v-else class="relay-button" href="/desk/contact/new">New Contact in Desk</a></WorkspaceState>
          <Button v-if="error" label="Retry contacts" @click="load()" /><Button v-if="more" label="More contacts" :loading="busy" @click="load(true)" />
        </div>
        <ContactDetails v-if="selected" :key="selected" :contact="selected" /><WorkspaceState v-else compact title="Contact details at a glance" description="Select a contact to review WhatsApp endpoints and business links." icon="user" />
      </div>
    </div>
  </section>
</template>
