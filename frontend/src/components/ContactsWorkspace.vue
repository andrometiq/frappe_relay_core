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
import IncomingWorkspace from './IncomingWorkspace.vue'
import ContactDetails from './ContactDetails.vue'
import NewContactDialog from './NewContactDialog.vue'
import { routeTab } from '../useViewRoute'
const capabilities = inject('relayCapabilities')
const tab = ref(routeTab(location.hash, 'contacts'))
const businessType = ref(''), businessTypes = ref([])
const typeOptions = computed(() => [{ label: 'All types', value: '' }, ...businessTypes.value.map(value => ({ label: value, value }))])
const rows = ref([]), query = ref(''), selected = ref(''), busy = ref(false), error = ref(''), more = ref(false), creating = ref(false)
const emptyDescription = computed(() => query.value || businessType.value ? 'Try another name or clear the filters.'
  : capabilities.value.manage ? 'Add your first contact to start a conversation.' : 'No contacts are assigned to you yet. Ask your Relay administrator to give you access to contacts.')
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
    <template v-if="tab === 'unlinked' && capabilities.manage">
      <nav class="v1-tabs" aria-label="Contact views"><Button icon="chevron-left" label="Contacts" variant="ghost" @click="tab = 'contacts'" /></nav>
      <IncomingWorkspace />
    </template>
    <div v-else class="v1-content">
      <WorkspaceHeading description="People you chat with and the customers they belong to.">
        <Button v-if="capabilities.manage" label="New senders" icon="user-check" variant="ghost" @click="tab = 'unlinked'" />
        <Button v-if="capabilities.manage" label="New contact" icon="plus" variant="solid" @click="creating = true" />
      </WorkspaceHeading>
      <form class="workspace-search contacts-filters" role="search" @submit.prevent="searchContacts"><TextInput v-model="query" maxlength="80" aria-label="Search contacts" placeholder="Search name or number" type="search"><template #prefix><FeatherIcon name="search" /></template></TextInput><RelaySelect v-if="businessTypes.length" v-model="businessType" label="Customer type" :options="typeOptions" /></form>
      <ErrorMessage :message="error" />
      <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !selected }">
        <div class="workspace-records">
          <LoadingRows v-if="busy && !rows.length" label="Loading contacts…" />
          <button v-for="row in rows" :key="row.name" class="workspace-person-row" :aria-pressed="selected === row.name" @click="selected = row.name"><Avatar :label="recordTitle(row, 'Contact')" /><span><strong>{{ recordTitle(row, 'Contact') }}</strong><small>{{ row.mobile_no || 'No mobile number' }}</small></span><FeatherIcon name="chevron-right" /></button>
          <WorkspaceState v-if="!busy && !rows.length && !error" compact :title="query || businessType ? 'No contacts match these filters' : 'No contacts yet'" icon="users" :description="emptyDescription"><Button v-if="query || businessType" label="Clear filters" @click="query = ''; businessType = ''" /><Button v-else-if="capabilities.manage" label="New contact" variant="solid" @click="creating = true" /></WorkspaceState>
          <Button v-if="error" label="Retry contacts" @click="load()" /><div v-if="more" ref="moreSentinel" class="h-px" aria-hidden="true" />
        </div>
        <ContactDetails v-if="selected" :key="selected" :contact="selected" dismissible @close="selected = ''" />
      </div>
    </div>
    <NewContactDialog v-if="capabilities.manage" v-model="creating" @created="created" />
  </section>
</template>
