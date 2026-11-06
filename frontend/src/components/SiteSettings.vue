<script setup>
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Badge, Button, Dialog, ErrorMessage, FeatherIcon, FormControl, toast } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useWhatsAppIdentity } from '../composables/useWhatsAppIdentity'
import { useTask } from '../composables/useTask'
import LoadingRows from './LoadingRows.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import SavedRepliesWorkspace from './SavedRepliesWorkspace.vue'
import BusinessTypeSettings from './BusinessTypeSettings.vue'
import { channelEnabled } from '../services/enabledChannels'
import { routeTab } from '../useViewRoute'
import TelegramAccounts from './telegram/TelegramAccounts.vue'
import EmailAccounts from './email/EmailAccounts.vue'
const { identity, load: refreshIdentity } = useWhatsAppIdentity({ immediate: false })
const capabilities = inject('relayCapabilities')
const channels = ref([])
const config = ref({}), channel = ref(null), types = ref([]), loaded = ref(false), verified = ref(false)
const token = ref(''), callbackSecret = ref(''), tab = ref(routeTab(location.hash, 'setup')), setupCode = ref(''), askCode = ref(false)
const disconnecting = ref(false)
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
// A site linked with a setup code has no token in its config, so Reconnect asks for a new code.
async function reconnect() {
  const result = await coreApi('onboarding.api.connect_hub', { reconnect: 1, ...(askCode.value ? { setup_code: setupCode.value } : {}) }, true)
  if (result.error?.code === 'setup_code_required') askCode.value = true
  if (result.error) throw Error(result.error.message)
  askCode.value = false; setupCode.value = ''
  identity.value = null; await refreshIdentity(); notice.value = 'Reconnected to Relay Hub as ' + result.account + '.'; toast('Reconnected'); await load()
}
// The Hub revokes this site's key; the site keeps its data and links again with a new setup code.
async function disconnect() {
  disconnecting.value = false
  await coreApi('onboarding.api.disconnect_hub', { confirm: 1 }, true)
  identity.value = null; askCode.value = true; notice.value = 'Disconnected from Relay Hub. Enter a new setup code to link this site again.'; toast('Disconnected'); await load()
}
async function verify() { verified.value = false; await coreApi('settings.verify_connection', {}, true); verified.value = true; notice.value = 'Connection works. Incoming messages are checked on the Activity page.' }
const features = [
  { key: 'ai', label: 'Enable AI features', help: 'Shows AI replies, AI skills and AI history on tickets.' },
  { key: 'folders', label: 'Enable chat folders', help: 'Lets people sort chats into folders in the Chats list.' },
  { key: 'flows', label: 'Enable automations', help: 'Shows the Flows page, where managers build automatic replies and steps.' },
]
// A tab is part of the hash, so a checklist link opens it and the browser back button returns.
const tabs = computed(() => [
  { key: 'setup', label: 'Setup & connection' },
  ...['Telegram', 'Email'].filter(provider => channelEnabled(capabilities.value, provider)).map(provider => ({ key: provider.toLowerCase(), label: provider })),
  { key: 'replies', label: 'Saved replies' },
])
function show(key) { if (key !== tab.value) window.location.hash = key === 'setup' ? '#/settings' : '#/settings?tab=' + key }
function readTab() { tab.value = routeTab(location.hash, 'setup') }
const checklist = computed(() => [
  ...(capabilities.value.configure ? [{ label: 'Get started', icon: 'play', ready: !capabilities.value.onboarding?.required, state: capabilities.value.onboarding?.required ? 'Guided setup is not finished' : 'Finished', href: '#/setup' }] : []),
  { label: 'Hub connection', icon: 'link', ready: verified.value, state: !loaded.value ? 'Not checked' : verified.value ? 'Checked just now' : config.value.url && config.value.account && config.value.token_configured ? 'Saved · select Check connection' : 'Needs setup', href: '#hub-connection' },
  { label: 'Incoming message secret', icon: 'lock', ready: config.value.callback_configured, state: !loaded.value ? 'Not checked' : config.value.callback_configured ? 'Saved' : 'Missing', href: '#hub-connection' },
  ...['Telegram', 'Email'].filter(provider => channelEnabled(capabilities.value, provider)).map(provider => ({ label: provider + ' channel', icon: provider === 'Email' ? 'mail' : 'send', ready: channels.value.some(row => row.channel === provider && row.enabled), state: channels.value.some(row => row.channel === provider && row.enabled) ? (capabilities.value.configure ? 'Enabled locally · confirm incoming messages in Activity' : 'Enabled locally · ask an administrator to confirm incoming messages') : 'Needs setup', href: '#/settings?tab=' + provider.toLowerCase() })),
  { label: 'WhatsApp channel', icon: 'message-circle', ready: channel.value?.configured, state: !loaded.value ? 'Not checked' : channel.value?.configured ? 'Enabled for this account' : 'Needs setup', href: '#/whatsapp?tab=account' },
  { label: 'Business types and grouping', icon: 'users', ready: types.value.length > 0, state: !loaded.value ? 'Not checked' : types.value.length ? `${types.value.length} enabled types` : 'Needs setup', href: '/desk/relay-contact-type' },
  { label: 'Contacts and links', icon: 'users', state: 'Review identities, consent and permitted links', href: '#/contacts' },
  ...(capabilities.value.configure ? [{ label: 'Incoming messages and recovery', icon: 'activity', state: 'See what arrived and retry failures', href: '#/activity' }] : []),
])
onMounted(() => { run(load); window.addEventListener('hashchange', readTab) })
onBeforeUnmount(() => window.removeEventListener('hashchange', readTab))
watch(() => capabilities.value?.configure, configure => { if (configure) loadMargin() }, { immediate: true })
function followStep(event, step) { if (step.href === '#hub-connection') { event.preventDefault(); document.getElementById('hub-connection')?.scrollIntoView({ block: 'start' }) } }
</script>
<template>
  <section class="v1-screen">
    <nav class="v1-tabs" aria-label="Settings sections"><Button v-for="item in tabs" :key="item.key" :label="item.label" :variant="tab === item.key ? 'solid' : 'ghost'" @click="show(item.key)" /></nav>
    <SavedRepliesWorkspace v-if="tab === 'replies'" />
    <div v-else-if="tab === 'telegram' && channelEnabled(capabilities, 'Telegram')" class="v1-content space-y-5"><WorkspaceHeading description="Connect Telegram bots. Relay Hub keeps each bot token." /><TelegramAccounts /></div>
    <div v-else-if="tab === 'email' && channelEnabled(capabilities, 'Email')" class="v1-content space-y-5"><WorkspaceHeading description="Connect mailboxes. Relay Hub keeps each password." /><EmailAccounts /></div>
    <div v-else class="v1-content space-y-5">
      <WorkspaceHeading description="Connect your account and prepare your workspace for conversations."><Button variant="outline" label="Refresh setup" icon-left="refresh-cw" :loading="busy" @click="run(load)" /></WorkspaceHeading>
      <ErrorMessage :message="error" /><LoadingRows v-if="busy && !loaded" :count="2" label="Checking configuration…" />
      <div class="v1-card-grid setup-checklist"><a v-for="(step, index) in checklist" :key="step.label" :href="step.href" class="v1-list-card" @click="followStep($event, step)"><span class="setup-step-top"><FeatherIcon :name="step.icon" :size="20" /><Badge :label="!loaded ? 'Not checked' : step.ready ? 'Ready' : 'Review'" :theme="loaded && step.ready ? 'green' : 'gray'" /></span><strong>{{ index + 1 }}. {{ step.label }}</strong><span>{{ step.state }}</span><small>Review setup <FeatherIcon name="arrow-up-right" :size="14" /></small></a></div>
      <BusinessTypeSettings v-if="capabilities.manage" />
      <form id="hub-connection" class="workflow-card" @submit.prevent="run(save)">
        <h2 class="text-lg font-semibold">Hub connection</h2><p class="text-sm">Relay sends and receives messages through Hub.<template v-if="config.account"> This site is linked as {{ config.account }}.</template></p>
        <div v-if="capabilities.configure" class="flex flex-wrap gap-3"><Button label="Reconnect to Relay Hub" variant="outline" icon-left="refresh-cw" :disabled="busy" @click="run(reconnect)" /><Button variant="outline" label="Check connection" :disabled="busy || !config.token_configured" @click="run(verify)" /><Button v-if="config.token_configured" variant="outline" theme="red" label="Disconnect from Relay Hub" :disabled="busy" @click="disconnecting = true" /></div>
        <Dialog v-model="disconnecting" :options="{ title: 'Disconnect from Relay Hub?', size: 'md' }"><div class="space-y-4 text-sm text-ink-gray-8"><p>Relay stops sending and receiving on every channel of this site, and the Hub revokes this site’s key. Chats, contacts and settings stay here. To link again, you need a new setup code from your Relay provider.</p><div class="flex justify-end gap-2"><Button variant="ghost" label="Cancel" @click="disconnecting = false" /><Button variant="solid" theme="red" label="Disconnect" @click="run(disconnect)" /></div></div></Dialog>
        <div v-if="capabilities.configure && askCode" class="settings-fields"><FormControl v-model="setupCode" label="Setup code" autocomplete="off" spellcheck="false" class="font-mono" :disabled="busy" /><p class="text-sm">Enter the setup code or setup link your Relay provider gave you, then select Reconnect to Relay Hub.</p></div>
        <details class="settings-advanced"><summary>Connect manually (advanced)</summary><p class="text-sm">Enter the details your Hub administrator gave you, then save.</p>
        <div class="settings-fields"><FormControl label="Connection address" v-model="config.url" :disabled="busy || !capabilities.configure" /><FormControl label="Account name" v-model="config.account" :disabled="busy || !capabilities.configure" />
        <FormControl v-if="capabilities.configure" label="Access key" type="password" autocomplete="new-password" v-model="token" :placeholder="config.token_configured ? 'Saved — leave blank to keep' : 'Required'" :disabled="busy" /></div>
        <details v-if="capabilities.configure" class="settings-advanced"><summary>Advanced</summary>
          <div class="settings-fields"><FormControl label="Incoming message secret" type="password" autocomplete="new-password" v-model="callbackSecret" :placeholder="config.callback_configured ? 'Saved — leave blank to keep' : '32–512 printable characters'" :disabled="busy" /></div>
          <p class="text-sm text-ink-gray-5">Hub signs each incoming message with this secret. Use the same value in Hub.</p>
        </details><template v-if="capabilities.configure">
          <div class="flex flex-wrap gap-3"><Button type="submit" label="Save connection" variant="solid" :disabled="busy || !loaded" /></div>
        </template></details><p v-if="!capabilities.configure">A System Manager can edit this connection.</p><p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>
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
      <div class="workflow-card"><h2 class="font-semibold">Channels</h2><p>Set up WhatsApp numbers on the <a class="underline" href="#/whatsapp?tab=account">WhatsApp Account</a> page<template v-if="tabs.length > 2">, and Telegram bots and mailboxes on their tabs above</template>. Relay Hub keeps every key and token. <template v-if="capabilities.configure">Check the Activity page to see that messages arrive.</template><template v-else>Ask a system administrator to check that messages arrive.</template></p><p v-for="item in channels" :key="item.name">{{ linkedTitle('Relay Channel', item.name, item.channel) }} <Badge :label="item.enabled ? 'Enabled locally' : 'Disabled'" /></p><a v-if="capabilities.configure" class="underline" href="#/activity">Open Activity</a></div>
      <div class="flex flex-wrap gap-3"><a class="v1-link" href="#/whatsapp?tab=account">WhatsApp numbers</a><a class="v1-link" href="/desk/relay-contact-type">Configure business types and grouping</a><a class="v1-link" href="/desk/relay-contact-endpoint">Contact numbers and addresses</a></div>
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
