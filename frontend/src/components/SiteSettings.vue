<script setup>
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon, FormControl, toast } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useWhatsAppIdentity } from '../composables/useWhatsAppIdentity'
import { useTask } from '../composables/useTask'
import LoadingRows from './LoadingRows.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import SavedRepliesWorkspace from './SavedRepliesWorkspace.vue'
import { channelEnabled } from '../services/enabledChannels'
const { identity, load: refreshIdentity } = useWhatsAppIdentity({ immediate: false })
const capabilities = inject('relayCapabilities')
const channels = ref([])
const config = ref({}), channel = ref(null), types = ref([]), loaded = ref(false), verified = ref(false)
const token = ref(''), callbackSecret = ref(''), tab = ref('setup')
const margin = ref(''), marginError = ref(''), marginNotice = ref('')
const { busy, error, notice, run } = useTask()
async function load() {
  loaded.value = false
  const [connection, whatsapp, businessTypes, available] = await Promise.all([coreApi('settings.connection'), coreApi('whatsapp.connection'), coreApi('api.business_types'), coreApi('api.channel_options')])
  channels.value = available.items.filter(row => channelEnabled(capabilities.value, row.channel)); config.value = connection; channel.value = whatsapp; types.value = businessTypes; loaded.value = true
}
async function save() {
  verified.value = false
  await coreApi('settings.save_connection', { url: config.value.url, account: config.value.account, token: token.value, callback_secret: callbackSecret.value }, true)
  identity.value = null; await refreshIdentity(); token.value = ''; callbackSecret.value = ''; notice.value = 'Connection saved and checked.'; toast('Saved'); await load()
}
async function loadMargin() {
  marginError.value = ''
  try { margin.value = String((await coreApi('billing.get_margin')).margin_percent) }
  catch (e) { marginError.value = e.message }
}
async function saveMargin() {
  marginNotice.value = ''
  margin.value = String((await coreApi('billing.save_margin', { percent: margin.value }, true)).margin_percent)
  marginNotice.value = 'Service charge saved.'; toast('Saved')
}
async function saveFeature(feature, enabled) { await coreApi('settings.save_feature', { feature, enabled: enabled ? 1 : 0 }, true); location.reload() }
async function verify() { verified.value = false; await coreApi('settings.verify_connection', {}, true); verified.value = true; notice.value = 'Connection works. Incoming messages are checked on the Activity page.' }
const features = [
  { key: 'ai', label: 'Enable AI features', help: 'Shows AI replies, AI skills and AI history on tickets.' },
  { key: 'folders', label: 'Enable chat folders', help: 'Lets people sort chats into folders in the Chats list.' },
  { key: 'teams', label: 'Enable teams', help: 'Shows Teams & access, so managers can group people and share chats by team.' },
  { key: 'flows', label: 'Enable automations', help: 'Shows the Flows page, where managers build automatic replies and steps.' },
]
const checklist = computed(() => [
  { label: 'Hub connection', icon: 'link', ready: verified.value, state: !loaded.value ? 'Not checked' : verified.value ? 'Checked just now' : config.value.url && config.value.account && config.value.token_configured ? 'Saved · select Check connection' : 'Needs setup', href: '#hub-connection' },
  { label: 'Incoming message secret', icon: 'lock', ready: config.value.callback_configured, state: !loaded.value ? 'Not checked' : config.value.callback_configured ? 'Saved' : 'Missing', href: '#hub-connection' },
  ...['Telegram', 'Email'].filter(provider => channelEnabled(capabilities.value, provider)).map(provider => ({ label: provider + ' channel', icon: provider === 'Email' ? 'mail' : 'send', ready: channels.value.some(row => row.channel === provider && row.enabled), state: channels.value.some(row => row.channel === provider && row.enabled) ? 'Enabled locally · confirm receipts in Activity' : 'Needs setup', href: '/desk/relay-channel' })),
  { label: 'WhatsApp channel', icon: 'message-circle', ready: channel.value?.configured, state: !loaded.value ? 'Not checked' : channel.value?.configured ? 'Enabled for this account' : 'Needs setup', href: '/desk/relay-channel' },
  { label: 'Business types and grouping', icon: 'users', ready: types.value.length > 0, state: !loaded.value ? 'Not checked' : types.value.length ? `${types.value.length} enabled types` : 'Needs setup', href: '/desk/relay-contact-type' },
  { label: 'Contacts and links', icon: 'users', state: 'Review identities, consent and permitted links', href: '#/contacts' },
  ...(capabilities.value.teams ? [{ label: 'Teams and access', icon: 'user-check', state: 'Review membership and permissions', href: '#/teams' }] : []),
  { label: 'Incoming messages and recovery', icon: 'activity', state: 'See what arrived and retry failures', href: '#/activity' },
])
onMounted(() => run(load))
watch(() => capabilities.value?.configure, configure => { if (configure) loadMargin() }, { immediate: true })
function followStep(event, step) { if (step.href === '#hub-connection') { event.preventDefault(); document.getElementById('hub-connection')?.scrollIntoView({ block: 'start' }) } }
</script>
<template>
  <section class="v1-screen">
    <nav class="v1-tabs" aria-label="Settings sections"><Button label="Setup & connection" :variant="tab === 'setup' ? 'solid' : 'ghost'" @click="tab = 'setup'" /><Button label="Saved replies" :variant="tab === 'replies' ? 'solid' : 'ghost'" @click="tab = 'replies'" /></nav>
    <SavedRepliesWorkspace v-if="tab === 'replies'" />
    <div v-else class="v1-content space-y-5">
      <WorkspaceHeading description="Connect your account and prepare your workspace for conversations."><Button variant="outline" label="Refresh setup" icon-left="refresh-cw" :loading="busy" @click="run(load)" /></WorkspaceHeading>
      <ErrorMessage :message="error" /><LoadingRows v-if="busy && !loaded" :count="2" label="Checking configuration…" />
      <div class="v1-card-grid setup-checklist"><a v-for="(step, index) in checklist" :key="step.label" :href="step.href" class="v1-list-card" @click="followStep($event, step)"><span class="setup-step-top"><FeatherIcon :name="step.icon" :size="20" /><Badge :label="!loaded ? 'Not checked' : step.ready ? 'Ready' : 'Review'" :theme="loaded && step.ready ? 'green' : 'gray'" /></span><strong>{{ index + 1 }}. {{ step.label }}</strong><span>{{ step.state }}</span><small>Review setup <FeatherIcon name="arrow-up-right" :size="14" /></small></a></div>
      <form id="hub-connection" class="workflow-card" @submit.prevent="run(save)">
        <h2 class="text-lg font-semibold">Hub connection</h2><p class="text-sm">Relay sends and receives messages through Hub. Enter the details your Hub administrator gave you, save, then select Check connection.</p>
        <div class="settings-fields"><FormControl label="Connection address" v-model="config.url" :disabled="busy || !capabilities.configure" /><FormControl label="Account name" v-model="config.account" :disabled="busy || !capabilities.configure" />
        <FormControl v-if="capabilities.configure" label="Access key" type="password" autocomplete="new-password" v-model="token" :placeholder="config.token_configured ? 'Saved — leave blank to keep' : 'Required'" :disabled="busy" /></div>
        <details v-if="capabilities.configure" class="settings-advanced"><summary>Advanced</summary>
          <div class="settings-fields"><FormControl label="Incoming message secret" type="password" autocomplete="new-password" v-model="callbackSecret" :placeholder="config.callback_configured ? 'Saved — leave blank to keep' : '32–512 printable characters'" :disabled="busy" /></div>
          <p class="text-sm text-ink-gray-5">Hub signs each incoming message with this secret. Use the same value in Hub.</p>
        </details><template v-if="capabilities.configure">
          <div class="flex flex-wrap gap-3"><Button type="submit" label="Save connection" variant="solid" :disabled="busy || !loaded" /><Button variant="outline" label="Check connection" :disabled="busy || !config.token_configured" @click="run(verify)" /></div>
        </template><p v-else>A System Manager can edit this connection.</p><p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>
      </form>
      <div v-if="config.can_switch_ai" class="workflow-card settings-features"><h2 class="font-semibold">Features</h2><p class="text-sm text-ink-gray-5">Relay reloads the page after you change a switch.</p>
        <div v-for="feature in features" :key="feature.key"><FormControl type="checkbox" :label="feature.label" :model-value="Boolean(config[feature.key + '_enabled'])" :disabled="busy || !loaded" @update:model-value="value => run(() => saveFeature(feature.key, value))" /><small>{{ feature.help }}</small></div></div>
      <form v-if="capabilities.configure && channelEnabled(capabilities, 'WhatsApp')" class="workflow-card" @submit.prevent="run(saveMargin)">
        <h2 class="font-semibold">WhatsApp billing</h2><p class="text-sm">Included in the rate per message on the Billing page.</p>
        <ErrorMessage :message="marginError" />
        <div class="settings-fields"><FormControl label="Service charge (%)" type="number" min="0" max="1000" step="0.01" v-model="margin" :disabled="busy" /></div>
        <div><Button type="submit" label="Save service charge" variant="solid" :disabled="busy || margin === ''" /></div>
        <p v-if="marginNotice" role="status" class="workspace-success">{{ marginNotice }}</p>
      </form>
      <div class="workflow-card"><h2 class="font-semibold">Channels</h2><p>Each channel is set up in Hub. Check the Activity page to see that messages arrive.</p><p v-for="item in channels" :key="item.name">{{ linkedTitle('Relay Channel', item.name, item.channel) }} <Badge :label="item.enabled ? 'Enabled locally' : 'Disabled'" /></p><a class="underline" href="#/activity">Open Activity</a></div>
      <div class="flex flex-wrap gap-3"><a class="v1-link" href="/desk/relay-channel">Configure channel</a><a class="v1-link" href="/desk/relay-contact-type">Configure business types and grouping</a><a class="v1-link" href="/desk/relay-contact-endpoint">Contact numbers and addresses</a></div>
    </div>
  </section>
</template>
<style scoped>
.settings-advanced { margin-top: 4px; }
.settings-advanced summary { cursor: pointer; font-size: 13px; color: var(--ink-gray-7); }
.settings-advanced[open] summary { margin-bottom: 10px; }
.settings-features { display: grid; gap: 10px; }
.settings-features small { display: block; margin-left: 26px; font-size: 12px; color: var(--ink-gray-5); }
</style>
