<script setup>
import { inject, ref, watch } from 'vue'
import { Avatar, Button, Badge, ErrorMessage, FeatherIcon } from '@relay/ui'
import { relativeTime } from './relativeTime'
import LoadingRows from './LoadingRows.vue'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import ChannelPreferences from './ChannelPreferences.vue'
const capabilities = inject('relayCapabilities')
const props = defineProps({ contact: String })
const detail = ref(null), busy = ref(false), error = ref('')
let generation = 0
const desk = (doctype, name) => '/desk/' + doctype.toLowerCase().replaceAll(' ', '-') + '/' + encodeURIComponent(name)
const conversation = link => '#/messages?' + new URLSearchParams({ business_doctype: link.doctype, business_name: link.name, contact: props.contact })
async function load() {
  const ticket = ++generation
  detail.value = null; error.value = ''; busy.value = true
  try { const data = await coreApi('api.contact_details', { contact: props.contact }); if (ticket === generation) detail.value = data }
  catch (e) { if (ticket === generation) error.value = e.message }
  finally { if (ticket === generation) busy.value = false }
}
async function revoke(endpoint) {
  if (!window.confirm('Revoke this channel identity? It will no longer be available for sending until enrolled again.')) return
  busy.value = true; error.value = ''
  try { await coreApi('enrollment.revoke', { endpoint }, true); await load() }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
watch(() => props.contact, load, { immediate: true })
useRealtimeRefresh(['Contact', 'Relay Contact Endpoint'], ['contacts', 'incoming'], load)
</script>
<template>
  <section class="workflow-card contact-details" aria-label="Contact and business links">
    <LoadingRows v-if="busy" :count="2" label="Loading contact details…" />
    <ErrorMessage :message="error" /><Button v-if="error" label="Retry contact details" @click="load" />
    <template v-if="detail">
      <header class="contact-detail-heading"><Avatar :label="detail.label" /><div><h3>{{ detail.label }}</h3><p>Contact details</p></div></header>
      <p>{{ detail.phone || 'No phone number' }} <Badge :label="/^[0-9]{7,15}$/.test((detail.phone || '').replace(/[ +()\-]/g, '')) ? 'Phone format valid' : 'Country code and number required'" /></p>
      <a class="underline" :href="desk('Contact', detail.name)">Edit Contact and business links in Desk</a>
      <h4 class="font-medium">Permitted business links</h4>
      <div v-for="link in detail.links" :key="link.doctype + link.name" class="flex flex-wrap gap-3">
        <a class="underline" :href="desk(link.doctype, link.name)">{{ link.doctype }} · {{ link.name }}</a>
        <a class="underline" :href="conversation(link)">Open conversation</a>
      </div>
      <p v-if="!detail.links.length">No accessible, configured business links. Add a link in Contact and enable its business type in Settings.</p>
      <h4 class="font-medium">Channel identities</h4>
      <article v-for="endpoint in detail.endpoints" :key="endpoint.name" class="contact-identity">
        <div class="identity-heading"><span><FeatherIcon :name="endpoint.provider === 'Email' ? 'mail' : endpoint.provider === 'Telegram' ? 'send' : 'message-circle'" :size="14" />{{ endpoint.provider }}</span><Badge :label="endpoint.verified ? 'Verified' : 'Revoked / unverified'" :theme="endpoint.verified ? 'green' : 'amber'" /></div>
        <p class="identity-endpoint">{{ endpoint.endpoint }}</p>
        <div class="identity-actions"><time :datetime="endpoint.modified">Updated {{ relativeTime(endpoint.modified) }}</time><Button v-if="capabilities.manage && endpoint.verified" label="Revoke" aria-label="Revoke identity" variant="ghost" size="xs" :disabled="busy" @click="revoke(endpoint.name)" /></div>
      </article>
      <p v-if="!detail.endpoints.length">No stored Channel identities. Start a conversation from a business link or review an unlinked sender.</p>
      <a v-if="capabilities.manage" class="underline" href="#/contacts?tab=unlinked">Enroll from authenticated incoming messages</a>
      <ChannelPreferences :key="detail.name + JSON.stringify(detail.endpoints)" :contact="detail.name" :links="detail.links" :endpoints="detail.endpoints" :editable="capabilities.configure" />
    </template>
  </section>
</template>

<style scoped>
.contact-details { min-width:0; overflow-wrap:anywhere; }
.contact-detail-heading > div { min-width:0; }
.contact-identity { border-top:1px solid var(--outline-gray-2); padding-top:12px; }
.identity-heading,.identity-heading > span,.identity-actions { display:flex; align-items:center; gap:8px; }
.identity-heading { justify-content:space-between; flex-wrap:wrap; font-size:13px; }
.identity-endpoint { margin-top:4px; font-size:14px; overflow-wrap:anywhere; }
.identity-actions { justify-content:space-between; color:var(--ink-gray-6); font-size:12px; }
.identity-actions .relay-button { min-height:32px; }
</style>
