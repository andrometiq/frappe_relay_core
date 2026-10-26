<script setup>
import { onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import FrappeListView from '../frappe/FrappeListView.vue'

const items = ref([]), after = ref(''), busy = ref(false), error = ref('')
const columns = [
  { key: 'title', label: 'Form', width: 'minmax(200px,1.4fr)' },
  { key: 'status', label: 'Status', width: '140px' },
  { key: 'categories', label: 'Categories', width: 'minmax(140px,1fr)' },
]
async function load(more = false) {
  busy.value = true; error.value = ''
  try {
    const page = await coreApi('meta_flows.execute', { operation: 'list', arguments: more ? { after: after.value } : {} }, true)
    items.value = [...(more ? items.value : []), ...(page.data || [])]
    after.value = page.paging?.has_more ? page.paging.cursors?.after || '' : ''
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <div class="whatsapp-forms">
    <div v-if="error" class="v1-template-feedback"><ErrorMessage :message="error" /></div>
    <FrappeListView title="Forms" description="WhatsApp forms of this account. Send a published form from a private conversation."
      label="Forms" :columns="columns" :items="items" :busy="busy" empty-title="No forms yet"
      empty-description="Forms created for this WhatsApp account show here.">
      <template #actions><Button label="Refresh" icon-left="refresh-cw" :loading="busy" @click="load()" /></template>
      <template #cell-title="{ item }"><strong>{{ item.name }}</strong></template>
      <template #cell-status="{ item }"><Badge :label="item.status" :theme="item.status === 'PUBLISHED' ? 'green' : 'gray'" /></template>
      <template #cell-categories="{ item }">{{ (item.categories || []).join(', ') || '—' }}</template>
      <template v-if="after" #footer><Button label="Load more forms" :loading="busy" @click="load(true)" /></template>
    </FrappeListView>
  </div>
</template>
