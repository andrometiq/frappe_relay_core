<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useWhatsAppIdentity } from '../composables/useWhatsAppIdentity'
import { useTask } from '../composables/useTask'
import SavedRepliesWorkspace from './SavedRepliesWorkspace.vue'
import WhatsAppIdentity from './WhatsAppIdentity.vue'
const { identity, load: refreshIdentity } = useWhatsAppIdentity({ immediate: false })
const capabilities = inject('relayCapabilities')
const config = ref({}), channel = ref(null), types = ref([]), loaded = ref(false), verified = ref(false)
const token = ref(''), callbackSecret = ref(''), tab = ref('setup')
const { busy, error, notice, run } = useTask()
async function load() {
  loaded.value = false
  const [connection, whatsapp, businessTypes] = await Promise.all([coreApi('settings.connection'), coreApi('whatsapp.connection'), coreApi('api.business_types')])
  config.value = connection; channel.value = whatsapp; types.value = businessTypes; loaded.value = true
}
async function save() {
  verified.value = false
  await coreApi('settings.save_connection', { url: config.value.url, account: config.value.account, token: token.value, callback_secret: callbackSecret.value }, true)
  identity.value = null; await refreshIdentity(); token.value = ''; callbackSecret.value = ''; notice.value = 'Connection saved and account/site binding checked.'; await load()
}
async function verify() { verified.value = false; await coreApi('settings.verify_connection', {}, true); verified.value = true; notice.value = 'Hub credentials and account/site binding verified. Callback delivery is checked separately.' }
const checklist = computed(() => [
  { label: 'Hub binding', state: !loaded.value ? 'Not checked' : verified.value ? 'Verified this session' : config.value.url && config.value.account && config.value.token_configured ? 'Saved · verify connection' : 'Needs setup', href: '#hub-connection' },
  { label: 'Callback signing secret', state: !loaded.value ? 'Not checked' : config.value.callback_configured ? 'Configured · receipt not verified' : 'Missing', href: '#hub-connection' },
  { label: 'WhatsApp channel', state: !loaded.value ? 'Not checked' : channel.value?.configured ? 'Enabled for this account' : 'Needs setup', href: '/desk/relay-channel' },
  { label: 'Business types and grouping', state: !loaded.value ? 'Not checked' : types.value.length ? `${types.value.length} enabled types` : 'Needs setup', href: '/desk/relay-contact-type' },
  { label: 'Contacts and links', state: 'Review phone numbers and permitted links', href: '#/contacts' },
  { label: 'Teams and access', state: 'Review membership and permissions', href: '#/teams' },
  { label: 'Callback processing and recovery', state: 'Review received events and recovery', href: '#/activity' },
])
onMounted(() => run(load))
function followStep(event, step) { if (step.href === '#hub-connection') { event.preventDefault(); document.getElementById('hub-connection')?.scrollIntoView({ block: 'start' }) } }
</script>
<template>
  <section class="v1-screen">
    <nav class="v1-tabs" aria-label="Settings sections"><Button label="Setup & connection" :variant="tab === 'setup' ? 'solid' : 'ghost'" @click="tab = 'setup'" /><Button label="Saved replies" :variant="tab === 'replies' ? 'solid' : 'ghost'" @click="tab = 'replies'" /></nav>
    <SavedRepliesWorkspace v-if="tab === 'replies'" />
    <div v-else class="v1-content space-y-5">
      <div class="flex flex-wrap items-center gap-3"><h2 class="text-lg font-semibold">Setup checklist</h2><Button label="Refresh setup" :loading="busy" @click="run(load)" /></div>
      <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p><p v-if="busy" role="status">Checking / saving configuration…</p>
      <div class="v1-card-grid"><a v-for="step in checklist" :key="step.label" :href="step.href" class="v1-list-card" @click="followStep($event, step)"><strong>{{ step.label }}</strong><span>{{ step.state }}</span><small class="underline">Review / fix →</small></a></div>
      <form id="hub-connection" class="workflow-card max-w-3xl" @submit.prevent="run(save)">
        <h2 class="text-lg font-semibold">Hub connection</h2><p class="text-sm">Save the Hub account first, verify this site’s binding, configure matching callback credentials in Hub, then confirm a received event in Activity.</p>
        <FormControl label="Hub MCP URL" v-model="config.url" :disabled="busy || !capabilities.configure" /><FormControl label="Hub account" v-model="config.account" :disabled="busy || !capabilities.configure" />
        <template v-if="capabilities.configure"><FormControl label="Replace API token" type="password" autocomplete="new-password" v-model="token" :placeholder="config.token_configured ? 'Saved — leave blank to keep' : 'Required'" :disabled="busy" /><FormControl label="Replace callback signing secret" type="password" autocomplete="new-password" v-model="callbackSecret" :placeholder="config.callback_configured ? 'Saved — leave blank to keep' : '32–512 printable characters'" :disabled="busy" />
          <div class="flex flex-wrap gap-3"><Button type="submit" label="Save connection" variant="solid" :disabled="busy || !loaded" /><Button label="Verify saved connection" :disabled="busy || !config.token_configured" @click="run(verify)" /></div>
        </template><p v-else>A System Manager can edit this connection.</p><ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
      </form>
      <div class="workflow-card max-w-3xl"><h2 class="font-semibold">Account and sending number</h2><p>Account: {{ config.account || 'Not configured' }}</p><WhatsAppIdentity v-if="channel?.configured" /><p v-else>Enable this account’s WhatsApp channel to read its identity.</p></div>
      <div class="flex flex-wrap gap-3"><a class="v1-link" href="/desk/relay-channel">Configure channel</a><a class="v1-link" href="/desk/relay-contact-type">Configure business types and grouping</a><a class="v1-link" href="/desk/relay-contact-endpoint">Review endpoint bindings</a></div>
    </div>
  </section>
</template>
