<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { whatsappNumbers } from '../../services/whatsappNumbers'
import { whatsappHealth } from '../../services/whatsappHealth'
import { dateTime } from '../relativeTime'

const capabilities = inject('relayCapabilities', ref({}))
// A one-number site reads the default number; a site with more numbers reads each of them.
const numbers = computed(() => {
  const rows = whatsappNumbers(capabilities.value)
  return rows.length > 1 ? rows : [{ name: '', label: '' }]
})
const accounts = ref({}), busy = ref(false), error = ref('')

async function load() {
  busy.value = true; error.value = ''
  try {
    const results = await Promise.all(numbers.value.map(number =>
      coreApi('whatsapp.execute', { operation: 'account.metadata', ...(number.name ? { channel: number.name } : {}) }, true)))
    accounts.value = Object.fromEntries(numbers.value.map((number, index) => [number.name, results[index]]))
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
function syncText(account) {
  if (account.status === 'not_synced') return 'Not synced from Meta yet. Ask your administrator to turn on hourly sync for this number in Relay Hub.'
  const synced = account.last_success ? 'Synced from Meta ' + dateTime(account.last_success) + '.' : 'Waiting for the first sync from Meta.'
  return account.status === 'failed' ? synced + ' The last refresh failed: ' + account.last_error : synced
}
onMounted(load)
</script>
<template>
  <section class="space-y-4" aria-label="WhatsApp accounts">
    <ErrorMessage :message="error" />
    <article v-for="number in numbers" :key="number.name" class="whatsapp-account">
      <template v-if="accounts[number.name]">
        <h3>{{ accounts[number.name].profile?.display_phone_number || number.label || 'Number not synced yet' }}</h3>
        <p v-if="accounts[number.name].profile?.verified_name || number.label" class="whatsapp-account__name">{{ [number.label, accounts[number.name].profile?.verified_name].filter(Boolean).join(' · ') }}</p>
        <dl class="whatsapp-account__health">
          <div v-for="row in whatsappHealth(accounts[number.name].profile)" :key="row.name"><dt>{{ row.name }}</dt><dd><Badge v-if="row.theme" :label="row.label" :theme="row.theme" /><template v-else>{{ row.text }}</template></dd></div>
        </dl>
        <p class="text-sm text-ink-gray-5">{{ syncText(accounts[number.name]) }}</p>
      </template>
      <p v-else-if="busy" role="status">Reading WhatsApp account…</p>
    </article>
    <Button variant="outline" icon-left="refresh-cw" label="Refresh" :loading="busy" @click="load" />
  </section>
</template>
<style scoped>
.whatsapp-account { display:flex; flex-direction:column; gap:8px; padding-bottom:16px; border-bottom:1px solid var(--outline-gray-2); }
.whatsapp-account h3 { font-size:15px; font-weight:600; }
.whatsapp-account__name { color:var(--ink-gray-6); }
.whatsapp-account__health { display:grid; gap:8px; margin:4px 0; }
.whatsapp-account__health > div { display:grid; grid-template-columns:170px minmax(0,1fr); align-items:center; gap:12px; }
.whatsapp-account__health dt { color:var(--ink-gray-5); }
.whatsapp-account__health dd { margin:0; color:var(--ink-gray-8); }
</style>
