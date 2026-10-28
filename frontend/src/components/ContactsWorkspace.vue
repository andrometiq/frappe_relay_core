<script setup>
import { useDebouncedSearch } from '../composables/useDebouncedSearch'
import { useLoadMore } from '../composables/useLoadMore'
import { recordTitle } from '../services/recordTitle'
import { computed, inject, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Avatar, Button, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import LoadingRows from './LoadingRows.vue'
import RelaySelect from './RelaySelect.vue'
import WorkspaceState from './WorkspaceState.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import UnlinkedContacts from './UnlinkedContacts.vue'
import ContactDetails from './ContactDetails.vue'
import NewContactDialog from './NewContactDialog.vue'
import { routeTab } from '../useViewRoute'
const capabilities = inject('relayCapabilities')
const tab = ref(routeTab(location.hash, 'contacts'))
const businessType = ref(''), businessTypes = ref([])
const typeOptions = computed(() => [{ label: 'All record types', value: '' }, ...businessTypes.value.map(value => ({ label: value, value }))])
const rows = ref([]), query = ref(''), selected = ref(''), busy = ref(false), error = ref(''), more = ref(false), creating = ref(false)
let generation = 0
async function load(append = false) {
  const ticket = ++generation; busy.value = true; error.value = ''
  try {
    const page = await coreApi('api.contact_directory', { query: query.value, after: append ? rows.value.at(-1)?.name : null, business_type: businessType.value || null })
    if (ticket === generation) { rows.value = append ? [...rows.value, ...page.items] : page.items; more.value = !!page.next }
  } catch (e) { if (ticket === generation) { error.value = e.message; rows.value = []; selected.value = '' } }
  finally { if (ticket === generation) busy.value = false }
}
const searchContacts = useDebouncedSearch(query, () => load(), () => { ++generation; more.value = false; rows.value = []; busy.value = true })
watch(businessType, () => { more.value = false; rows.value = []; load() })
async function loadTypes() { try { businessTypes.value = await coreApi('api.business_types') } catch { businessTypes.value = [] } }
function created(result) { selected.value = result.contact; load() }
function readRoute() { tab.value = routeTab(location.hash, 'contacts') }
onMounted(() => { load(); loadTypes(); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => { ++generation; window.removeEventListener('hashchange', readRoute) })
useRealtimeRefresh(['Contact'], ['contacts', 'incoming'], () => load())
const moreSentinel = useLoadMore({ loading: busy, hasMore: more, error, load: () => load(true) })
</script>
<template>
  <section class="v1-screen">
    <nav class="v1-tabs" aria-label="Contact views"><Button label="Contacts" :variant="tab === 'contacts' ? 'solid' : 'ghost'" @click="tab = 'contacts'" /><Button v-if="capabilities.manage" label="Unlinked contacts" :variant="tab === 'unlinked' ? 'solid' : 'ghost'" @click="tab = 'unlinked'" /></nav>
    <UnlinkedContacts v-if="tab === 'unlinked' && capabilities.manage" />
    <div v-else class="v1-content">
      <WorkspaceHeading description="Customer details, channel identities and connected business records."><Button v-if="capabilities.manage" label="New contact" icon="plus" variant="solid" @click="creating = true" /><a class="relay-button" href="/desk/contact/new">New Contact in Desk</a></WorkspaceHeading>
      <form class="workspace-search contacts-filters" role="search" @submit.prevent="searchContacts"><TextInput v-model="query" aria-label="Search Frappe Contacts" placeholder="Search contacts by name" type="search"><template #prefix><FeatherIcon name="search" /></template></TextInput><RelaySelect v-if="businessTypes.length" v-model="businessType" label="Record type" :options="typeOptions" /></form>
      <ErrorMessage :message="error" />
      <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !selected }">
        <div class="workspace-records">
          <LoadingRows v-if="busy && !rows.length" label="Loading contacts…" />
          <button v-for="row in rows" :key="row.name" class="workspace-person-row" :aria-pressed="selected === row.name" @click="selected = row.name"><Avatar :label="recordTitle(row, 'Contact')" /><span><strong>{{ recordTitle(row, 'Contact') }}</strong><small>{{ row.mobile_no || 'No mobile number' }}</small></span><FeatherIcon name="chevron-right" /></button>
          <WorkspaceState v-if="!busy && !rows.length && !error" compact title="No contacts match these filters." description="Try another name or create a contact in Desk." icon="users"><Button v-if="query || businessType" label="Clear filters" @click="query = ''; businessType = ''" /><a v-else class="relay-button" href="/desk/contact/new">New Contact in Desk</a></WorkspaceState>
          <Button v-if="error" label="Retry contacts" @click="load()" /><div v-if="more" ref="moreSentinel" class="h-px" aria-hidden="true" />
        </div>
        <ContactDetails v-if="selected" :key="selected" :contact="selected" dismissible @close="selected = ''" />
      </div>
    </div>
    <NewContactDialog v-if="capabilities.manage" v-model="creating" @created="created" />
  </section>
</template>
