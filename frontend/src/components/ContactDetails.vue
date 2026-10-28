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
import { useMobileLayout } from '../composables/useMobileLayout'
const channelEnabled = useEnabledChannels()
const capabilities = inject('relayCapabilities')
const isMobile = useMobileLayout()
// `link` shows only the link form, for an unlinked chat.
const props = defineProps({ contact: String, dismissible: Boolean, compact: Boolean, channel: String, link: Boolean })
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
  if (!window.confirm('Stop sending to this number? Relay will not use it until the customer messages again and it is checked.')) return
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
      <header v-if="!compact" class="contact-detail-heading"><Button v-if="dismissible && isMobile" icon="chevron-left" aria-label="Back to contacts" @click="emit('close')" /><Avatar :label="recordTitle(detail, 'Contact')" /><div class="contact-detail-name"><h3 :title="recordTitle(detail, 'Contact')">{{ recordTitle(detail, 'Contact') }}</h3><p>{{ detail.phone || 'No phone number' }}</p></div><Button v-if="dismissible && !isMobile" class="contact-detail-close" icon="x" variant="ghost" aria-label="Close" title="Close" @click="emit('close')" /></header>
      <p v-if="link && !detail.can_edit_links" class="info-hint">Not linked to a customer yet. A manager can link it.</p>
      <ContactLinks :contact="detail.name" :detail="detail" :start="link" @changed="linksChanged" @cancel="link && emit('close')" />
      <template v-if="!link">
      <h4 class="info-group-title">Details</h4>
      <dl class="info-card">
        <div v-if="channel" class="info-kv"><dt>Channel</dt><dd>{{ channel }}</dd></div>
        <div class="info-kv"><dt>Phone</dt><dd>{{ detail.phone || 'No phone number' }}<Badge v-if="detail.phone && !validPhone(detail.phone)" label="Add country code" theme="orange" /></dd></div>
      </dl>
      <details v-if="capabilities.manage" class="info-section">
        <summary class="info-group-title"><span>Advanced</span><FeatherIcon name="chevron-down" :size="14" /></summary>
        <h4 class="info-group-title">Saved numbers · {{ detail.endpoints.length }}</h4>
        <ul v-if="detail.endpoints.length" class="info-card">
          <li v-for="endpoint in detail.endpoints" :key="endpoint.name" class="info-item">
            <span class="info-icon" :class="endpoint.verified ? 'is-green' : 'is-blue'" aria-hidden="true"><FeatherIcon :name="providerIcon(endpoint.provider)" :size="18" /></span>
            <span class="info-item-copy"><b>{{ endpoint.endpoint }}</b><small>{{ endpoint.provider }} · {{ endpoint.verified ? 'Checked' : 'Not checked' }} · <time :datetime="endpoint.modified">Updated {{ relativeTime(endpoint.modified) }}</time></small></span>
            <Button v-if="endpoint.verified" label="Stop using" :aria-label="'Stop using ' + endpoint.endpoint" variant="ghost" size="xs" :disabled="busy" @click="revoke(endpoint.name)" />
          </li>
        </ul>
        <p v-else class="info-hint">No saved numbers yet. A number is saved when this person messages you.</p>
        <a class="info-link" href="#/contacts?tab=unlinked">Review new senders</a>
        <h4 class="info-group-title">Number to use per customer</h4>
        <div class="info-card info-card-body"><ChannelPreferences :key="detail.name + JSON.stringify(detail.endpoints)" :contact="detail.name" :links="detail.links" :endpoints="detail.endpoints" :editable="capabilities.configure" /></div>
        <a class="info-link" :href="desk('Contact', detail.name)">Open in Frappe Desk</a>
      </details>
      </template>
    </template>
  </section>
</template>

<style scoped>
.contact-details { display:flex; flex-direction:column; min-width:0; overflow-wrap:anywhere; }
.contact-detail-heading { margin-bottom:4px; }
.contact-detail-name { flex:1; min-width:0; }
.contact-detail-heading h3 { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.contact-detail-close { margin-left:auto; }
.info-kv dd { display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:6px; }
</style>
