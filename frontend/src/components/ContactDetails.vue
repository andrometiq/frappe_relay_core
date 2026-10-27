<script setup>
import { recordTitle } from '../services/recordTitle'
import { inject, ref, watch } from 'vue'
import { Avatar, Button, Badge, ErrorMessage, FeatherIcon } from '@relay/ui'
import { relativeTime } from './relativeTime'
import LoadingRows from './LoadingRows.vue'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import ChannelPreferences from './ChannelPreferences.vue'
import ContactLinks from './ContactLinks.vue'
import { useEnabledChannels } from '../composables/useEnabledChannels'
const channelEnabled = useEnabledChannels()
const capabilities = inject('relayCapabilities')
const props = defineProps({ contact: String, dismissible: Boolean, compact: Boolean, channel: String, assignee: String })
const emit = defineEmits(['close', 'loaded', 'changed'])
const detail = ref(null), busy = ref(false), error = ref('')
let generation = 0
const validPhone = phone => /^[0-9]{7,15}$/.test((phone || '').replace(/[ +()\-]/g, ''))
const providerIcon = provider => provider === 'Email' ? 'mail' : provider === 'Telegram' ? 'send' : 'message-circle'
const desk = (doctype, name) => '/desk/' + doctype.toLowerCase().replaceAll(' ', '-') + '/' + encodeURIComponent(name)
const linksChanged = summary => { detail.value = { ...detail.value, links: summary.links, primary: summary.primary }; emit('changed', summary) }
async function load() {
  const ticket = ++generation
  detail.value = null; error.value = ''; busy.value = true
  try { const data = await coreApi('api.contact_details', { contact: props.contact }); if (ticket === generation) { detail.value = { ...data, endpoints: data.endpoints.filter(row => channelEnabled(row.provider)) }; emit('loaded', detail.value) } }
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
  <section class="contact-details" aria-label="Contact and business links">
    <LoadingRows v-if="busy" :count="2" label="Loading contact details…" />
    <ErrorMessage :message="error" /><Button v-if="error" label="Retry contact details" @click="load" />
    <template v-if="detail">
      <header v-if="!compact" class="contact-detail-heading"><Button v-if="dismissible" icon="chevron-left" aria-label="Back to contacts" @click="emit('close')" /><Avatar :label="recordTitle(detail, 'Contact')" /><div><h3>{{ recordTitle(detail, 'Contact') }}</h3><p>Contact details</p></div></header>
      <ContactLinks :contact="detail.name" :detail="detail" @changed="linksChanged" />
      <h4 class="info-group-title">Details</h4>
      <dl class="info-card">
        <div v-if="channel" class="info-kv"><dt>Channel</dt><dd>{{ channel }}</dd></div>
        <div v-if="assignee" class="info-kv"><dt>Assignment</dt><dd>{{ assignee }}</dd></div>
        <div class="info-kv"><dt>Phone</dt><dd>{{ detail.phone || 'No phone number' }}<Badge v-if="detail.phone && !validPhone(detail.phone)" label="Country code and number required" theme="amber" /></dd></div>
        <div class="info-kv"><dt>Frappe Contact</dt><dd><a :href="desk('Contact', detail.name)">Edit in Desk</a></dd></div>
      </dl>
      <details class="info-section">
        <summary class="info-group-title"><span>Channel identities · {{ detail.endpoints.length }}</span><FeatherIcon name="chevron-down" :size="14" /></summary>
        <ul v-if="detail.endpoints.length" class="info-card">
          <li v-for="endpoint in detail.endpoints" :key="endpoint.name" class="info-item">
            <span class="info-icon" :class="endpoint.verified ? 'is-green' : 'is-blue'" aria-hidden="true"><FeatherIcon :name="providerIcon(endpoint.provider)" :size="18" /></span>
            <span class="info-item-copy"><b>{{ endpoint.endpoint }}</b><small>{{ endpoint.provider }} · {{ endpoint.verified ? 'Verified' : 'Revoked / unverified' }} · <time :datetime="endpoint.modified">Updated {{ relativeTime(endpoint.modified) }}</time></small></span>
            <Button v-if="capabilities.manage && endpoint.verified" label="Revoke" aria-label="Revoke identity" variant="ghost" size="xs" :disabled="busy" @click="revoke(endpoint.name)" />
          </li>
        </ul>
        <p v-else class="info-hint">No stored Channel identities. Start a conversation from a business link or review an unlinked sender.</p>
        <a v-if="capabilities.manage" class="info-link" href="#/contacts?tab=unlinked">Enroll from authenticated incoming messages</a>
      </details>
      <details class="info-section">
        <summary class="info-group-title"><span>Business channel preferences</span><FeatherIcon name="chevron-down" :size="14" /></summary>
        <div class="info-card info-card-body"><ChannelPreferences :key="detail.name + JSON.stringify(detail.endpoints)" :contact="detail.name" :links="detail.links" :endpoints="detail.endpoints" :editable="capabilities.configure" /></div>
      </details>
    </template>
  </section>
</template>

<style scoped>
.contact-details { display:flex; flex-direction:column; min-width:0; overflow-wrap:anywhere; }
.contact-detail-heading { margin-bottom:4px; }
.contact-detail-heading > div { min-width:0; }
.info-kv dd { display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:6px; }
</style>
