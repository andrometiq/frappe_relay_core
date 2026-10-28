<script setup>
import { useLoadMore } from '../../composables/useLoadMore'
import { onMounted, ref } from 'vue'
import { Badge, Button } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { sentenceCase } from '../../services/textCase'
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
const moreSentinel = useLoadMore({ loading: busy, hasMore: after, error, load: () => load(true) })
</script>
<template>
  <div class="whatsapp-forms">
    <FrappeListView title="Forms" description="WhatsApp forms collect answers inside a chat. Send a published form from a private conversation."
      label="Forms" :columns="columns" :items="items" :busy="busy" :empty-title="error ? 'Forms could not be loaded' : 'No forms yet'"
      :empty-description="error || 'Forms are created in Meta Business Manager. Published forms show here.'">
      <template #actions><Button variant="outline" label="Refresh" icon-left="refresh-cw" :loading="busy" @click="load()" /></template>
      <template #empty-action><Button variant="outline" :label="error ? 'Try again' : 'Refresh'" :loading="busy" @click="load()" /></template>
      <template #cell-title="{ item }"><strong>{{ item.name }}</strong></template>
      <template #cell-status="{ item }"><Badge :label="sentenceCase(item.status)" :theme="item.status === 'PUBLISHED' ? 'green' : 'gray'" /></template>
      <template #cell-categories="{ item }">{{ (item.categories || []).map(sentenceCase).join(', ') || '—' }}</template>
      <template v-if="after" #footer><div v-if="after" ref="moreSentinel" class="h-px" aria-hidden="true" /></template>
    </FrappeListView>
  </div>
</template>
