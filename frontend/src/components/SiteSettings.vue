<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Badge, Button, Dialog, ErrorMessage, FeatherIcon, FormControl, toast } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useWhatsAppIdentity } from '../composables/useWhatsAppIdentity'
import { useTask } from '../composables/useTask'
import LoadingRows from './LoadingRows.vue'
import SavedRepliesWorkspace from './SavedRepliesWorkspace.vue'
import BusinessTypeSettings from './BusinessTypeSettings.vue'
import TicketSettings from './TicketSettings.vue'
import WhatsAppAccounts from './whatsapp/WhatsAppAccounts.vue'
import SettingsLayout from './settings/SettingsLayout.vue'
import ToggleSwitch from './fields/ToggleSwitch.vue'
import { channelEnabled } from '../services/enabledChannels'
import { settingsSections, settingsTab } from '../services/settingsSections'
import { setupRoute } from '../services/onboarding'
import { whatsappRoute } from '../services/navigation'
import { routeTab } from '../useViewRoute'
import TelegramAccounts from './telegram/TelegramAccounts.vue'
import EmailAccounts from './email/EmailAccounts.vue'
const { identity, load: refreshIdentity } = useWhatsAppIdentity({ immediate: false })
const capabilities = inject('relayCapabilities')
const channels = ref([])
const config = ref({}), channel = ref(null), types = ref([]), loaded = ref(false), verified = ref(false)
const token = ref(''), callbackSecret = ref(''), setupCode = ref(''), askCode = ref(false)
const disconnecting = ref(false)
const margin = ref(''), marginError = ref(''), marginNotice = ref('')
const { busy, error, notice, run } = useTask()
const requested = ref(routeTab(location.hash, 'overview'))
const tab = computed(() => settingsTab(settingsSections(capabilities.value), requested.value))
const title = computed(() => settingsSections(capabilities.value).flatMap(section => section.items).find(item => item.key === tab.value)?.label || 'Settings')
const readRoute = () => { if (location.hash.startsWith('#/settings')) requested.value = routeTab(location.hash, 'overview') }
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
  { key: 'ai', label: 'AI features', help: 'Shows AI replies, AI skills and AI history on tickets.' },
  { key: 'folders', label: 'Chat folders', help: 'Lets people sort chats into folders in the Chats list.' },
  { key: 'flows', label: 'Automations', help: 'Shows the Flows page, where managers build automatic replies and steps.' },
]
const providerChannels = provider => channels.value.filter(row => row.channel === provider)
const checklist = computed(() => [
  ...(capabilities.value.configure ? [{ label: 'Get started', icon: 'play', ready: !capabilities.value.onboarding?.required, state: capabilities.value.onboarding?.required ? 'Guided setup is not finished' : 'Finished', href: '#/setup' }] : []),
  { label: 'Hub connection', icon: 'link', ready: verified.value, state: !loaded.value ? 'Not checked' : verified.value ? 'Checked just now' : config.value.url && config.value.account && config.value.token_configured ? 'Saved · select Check connection' : 'Needs setup', href: '#/settings?tab=hub' },
  { label: 'Incoming message secret', icon: 'lock', ready: config.value.callback_configured, state: !loaded.value ? 'Not checked' : config.value.callback_configured ? 'Saved' : 'Missing', href: '#/settings?tab=hub' },
  ...['Telegram', 'Email'].filter(provider => channelEnabled(capabilities.value, provider)).map(provider => ({ label: provider + ' channel', icon: provider === 'Email' ? 'mail' : 'send', ready: providerChannels(provider).some(row => row.enabled), state: providerChannels(provider).some(row => row.enabled) ? (capabilities.value.configure ? 'Enabled locally · confirm incoming messages in Activity' : 'Enabled locally · ask an administrator to confirm incoming messages') : 'Needs setup', href: '#/settings?tab=' + provider.toLowerCase() })),
  { label: 'WhatsApp channel', icon: 'message-circle', ready: channel.value?.configured, state: !loaded.value ? 'Not checked' : channel.value?.configured ? 'Enabled for this account' : 'Needs setup', href: '#/settings?tab=whatsapp' },
  { label: 'Business types and grouping', icon: 'users', ready: types.value.length > 0, state: !loaded.value ? 'Not checked' : types.value.length ? `${types.value.length} enabled types` : 'Needs setup', href: '#/settings?tab=business-types' },
  { label: 'Contacts and links', icon: 'users', state: 'Review identities, consent and permitted links', href: '#/contacts' },
  ...(capabilities.value.configure ? [{ label: 'Incoming messages and recovery', icon: 'activity', state: 'See what arrived and retry failures', href: '#/activity' }] : []),
])
onMounted(() => { run(load); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => window.removeEventListener('hashchange', readRoute))
watch(() => capabilities.value?.configure, configure => { if (configure) loadMargin() }, { immediate: true })
</script>
<template>
  <SettingsLayout :active="tab">
    <main class="page-main" :aria-label="title">
      <header class="page-head">
        <h2>{{ title }}</h2>
        <div class="page-head-actions">
          <a v-if="tab === 'whatsapp' && capabilities.configure" class="relay-button relay-button--solid relay-button--sm" :href="setupRoute('number')"><FeatherIcon name="plus" />{{ channel?.configured ? 'Connect number' : 'Connect WhatsApp' }}</a>
          <Button v-if="tab === 'overview'" variant="outline" label="Refresh" icon-left="refresh-cw" :loading="busy" @click="run(load)" />
        </div>
      </header>
      <div class="settings-page">
        <ErrorMessage :message="error" /><LoadingRows v-if="busy && !loaded" :count="2" label="Checking configuration…" />
        <p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>

        <section v-if="tab === 'overview'" class="settings-card" aria-label="Setup checklist">
          <header><div><h3>Setup checklist</h3><p>Connect your account and prepare your workspace for conversations.</p></div></header>
          <a v-for="(step, index) in checklist" :key="step.label" :href="step.href" class="settings-row">
            <span class="settings-row-icon"><FeatherIcon :name="step.icon" :size="16" /></span>
            <span class="settings-row-text"><b>{{ index + 1 }}. {{ step.label }}</b><small>{{ step.state }}</small></span>
            <span class="settings-row-end"><Badge :label="!loaded ? 'Not checked' : step.ready ? 'Ready' : 'Review'" :theme="loaded && step.ready ? 'green' : 'gray'" /><FeatherIcon name="chevron-right" :size="16" /></span>
          </a>
        </section>

        <template v-else-if="tab === 'whatsapp'">
          <section class="settings-card" aria-label="Connected numbers">
            <header><div><h3>Connected numbers</h3><p>Numbers linked through Meta signup. Messages to these numbers arrive in the inbox.</p></div>
              <Badge v-if="channel" :label="channel.configured ? 'Connected' : 'Needs setup'" :theme="channel.configured ? 'green' : 'orange'" /></header>
            <WhatsAppAccounts v-if="channel?.configured" />
            <p v-else-if="loaded" class="settings-row">{{ capabilities.configure ? 'Connect WhatsApp to add your first number.' : 'Relay is being set up. Ask your administrator to finish setup.' }}</p>
          </section>
          <section class="settings-card" aria-label="WhatsApp pages">
            <a class="settings-row" :href="whatsappRoute('templates')"><span class="settings-row-text"><b>Message templates</b><small>Approved messages you can send outside the 24-hour window</small></span><FeatherIcon name="chevron-right" :size="16" /></a>
          </section>
        </template>

        <section v-else-if="tab === 'telegram' || tab === 'email'" class="settings-card" :aria-label="title">
          <header><div><h3>{{ tab === 'email' ? 'Mailboxes' : 'Bots' }}</h3><p>{{ tab === 'email' ? 'Connect mailboxes. Relay Hub keeps each password.' : 'Connect Telegram bots. Relay Hub keeps each bot token.' }} <template v-if="capabilities.configure">Check the Activity page to see that messages arrive.</template><template v-else>Ask a system administrator to check that messages arrive.</template></p></div></header>
          <div class="settings-card-body"><template v-if="tab === 'email'"><EmailAccounts /></template><template v-else><TelegramAccounts /></template></div>
          <a v-if="capabilities.configure" class="settings-row" href="#/activity"><span class="settings-row-text"><b>Open Activity</b><small>See what arrived and retry failures</small></span><FeatherIcon name="chevron-right" :size="16" /></a>
        </section>

        <BusinessTypeSettings v-else-if="tab === 'business-types'" />
        <section v-else-if="tab === 'replies'" class="settings-card" aria-label="Quick replies"><SavedRepliesWorkspace /></section>
        <TicketSettings v-else-if="tab === 'tickets'" />

        <section v-else-if="tab === 'features'" class="settings-card" aria-label="Features">
          <header><div><h3>Features</h3><p>{{ config.can_switch_ai ? 'Relay reloads the page after you change a switch.' : 'A System Manager can turn these on or off.' }}</p></div></header>
          <div v-for="feature in features" :key="feature.key" class="settings-row">
            <span class="settings-row-text"><b>{{ feature.label }}</b><small>{{ feature.help }}</small></span>
            <ToggleSwitch v-if="config.can_switch_ai" :label="feature.label" :model-value="Boolean(config[feature.key + '_enabled'])" :disabled="busy || !loaded" @update:model-value="value => run(() => saveFeature(feature.key, value))" />
            <Badge v-else :label="config[feature.key + '_enabled'] ? 'On' : 'Off'" :theme="config[feature.key + '_enabled'] ? 'green' : 'gray'" />
          </div>
        </section>

        <template v-else-if="tab === 'billing'">
          <form class="settings-card" @submit.prevent="run(saveMargin)">
            <header><div><h3>WhatsApp billing</h3><p>Included in the rate per message on the Billing page.</p></div></header>
            <div class="settings-card-body">
              <ErrorMessage :message="marginError" />
              <div class="settings-fields-grid"><FormControl label="Service charge (%)" type="number" min="0" max="1000" step="0.01" v-model="margin" :disabled="busy" /></div>
              <div><Button type="submit" label="Save service charge" variant="solid" :disabled="busy || margin === ''" /></div>
              <p v-if="marginNotice" role="status" class="workspace-success">{{ marginNotice }}</p>
            </div>
          </form>
          <section class="settings-card"><a class="settings-row" :href="whatsappRoute('billing')"><span class="settings-row-text"><b>Billing and usage</b><small>Messages sent, rates and monthly totals</small></span><FeatherIcon name="chevron-right" :size="16" /></a></section>
        </template>

        <form v-else-if="tab === 'hub'" id="hub-connection" class="settings-card" @submit.prevent="run(save)">
          <header><div><h3>Hub connection</h3><p>Relay sends and receives messages through Hub.<template v-if="config.account"> This site is linked as {{ config.account }}.</template></p></div>
            <Badge v-if="loaded" :label="verified ? 'Checked' : config.token_configured ? 'Saved' : 'Needs setup'" :theme="verified ? 'green' : config.token_configured ? 'gray' : 'orange'" /></header>
          <div class="settings-card-body">
            <div v-if="capabilities.configure" class="flex flex-wrap gap-3"><Button label="Reconnect to Relay Hub" variant="outline" icon-left="refresh-cw" :disabled="busy" @click="run(reconnect)" /><Button variant="outline" label="Check connection" :disabled="busy || !config.token_configured" @click="run(verify)" /><Button v-if="config.token_configured" variant="outline" theme="red" label="Disconnect from Relay Hub" :disabled="busy" @click="disconnecting = true" /></div>
            <Dialog v-model="disconnecting" :options="{ title: 'Disconnect from Relay Hub?', size: 'md' }"><div class="space-y-4 text-sm text-ink-gray-8"><p>Relay stops sending and receiving on every channel of this site, and the Hub revokes this site’s key. Chats, contacts and settings stay here. To link again, you need a new setup code from your Relay provider.</p><div class="flex justify-end gap-2"><Button variant="ghost" label="Cancel" @click="disconnecting = false" /><Button variant="solid" theme="red" label="Disconnect" @click="run(disconnect)" /></div></div></Dialog>
            <div v-if="capabilities.configure && askCode" class="settings-fields-grid"><FormControl v-model="setupCode" label="Setup code" autocomplete="off" spellcheck="false" class="font-mono" :disabled="busy" /><p class="text-sm">Enter the setup code or setup link your Relay provider gave you, then select Reconnect to Relay Hub.</p></div>
            <details class="settings-advanced"><summary>Connect manually (advanced)</summary><p class="text-sm">Enter the details your Hub administrator gave you, then save.</p>
              <div class="settings-fields-grid"><FormControl label="Connection address" v-model="config.url" :disabled="busy || !capabilities.configure" /><FormControl label="Account name" v-model="config.account" :disabled="busy || !capabilities.configure" />
                <FormControl v-if="capabilities.configure" label="Access key" type="password" autocomplete="new-password" v-model="token" :placeholder="config.token_configured ? 'Saved — leave blank to keep' : 'Required'" :disabled="busy" /></div>
              <details v-if="capabilities.configure" class="settings-advanced"><summary>Advanced</summary>
                <div class="settings-fields-grid"><FormControl label="Incoming message secret" type="password" autocomplete="new-password" v-model="callbackSecret" :placeholder="config.callback_configured ? 'Saved — leave blank to keep' : '32–512 printable characters'" :disabled="busy" /></div>
                <p class="text-sm text-ink-gray-5">Hub signs each incoming message with this secret. Use the same value in Hub.</p>
              </details>
              <div v-if="capabilities.configure" class="flex flex-wrap gap-3"><Button type="submit" label="Save connection" variant="solid" :disabled="busy || !loaded" /></div>
            </details>
            <p v-if="!capabilities.configure" class="text-sm">A System Manager can edit this connection.</p>
          </div>
        </form>
      </div>
    </main>
  </SettingsLayout>
</template>
<style scoped>
.settings-advanced { display:flex; flex-direction:column; gap:10px; }
.settings-advanced summary { cursor:pointer; font-size:13px; color:var(--relay-ink-2); }
.settings-card > p.settings-row { color:var(--relay-ink-3); }
.settings-card :deep(.page-body) { padding:14px 16px; }
</style>
