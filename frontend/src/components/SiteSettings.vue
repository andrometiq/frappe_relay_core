<script setup>
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon, FormControl } from '@relay/ui'
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
  identity.value = null; await refreshIdentity(); token.value = ''; callbackSecret.value = ''; notice.value = 'Connection saved and account/site binding checked.'; await load()
}
async function loadMargin() {
  marginError.value = ''
  try { margin.value = String((await coreApi('billing.get_margin')).margin_percent) }
  catch (e) { marginError.value = e.message }
}
async function saveMargin() {
  marginNotice.value = ''
  margin.value = String((await coreApi('billing.save_margin', { percent: margin.value }, true)).margin_percent)
  marginNotice.value = 'Service charge saved.'
}
async function saveFeature(feature, enabled) { await coreApi('settings.save_feature', { feature, enabled: enabled ? 1 : 0 }, true); location.reload() }
async function verify() { verified.value = false; await coreApi('settings.verify_connection', {}, true); verified.value = true; notice.value = 'Hub credentials and account/site binding verified. Callback delivery is checked separately.' }
const checklist = computed(() => [
  { label: 'Hub binding', icon: 'link', ready: verified.value, state: !loaded.value ? 'Not checked' : verified.value ? 'Verified this session' : config.value.url && config.value.account && config.value.token_configured ? 'Saved · verify connection' : 'Needs setup', href: '#hub-connection' },
  { label: 'Callback signing secret', icon: 'lock', ready: config.value.callback_configured, state: !loaded.value ? 'Not checked' : config.value.callback_configured ? 'Configured · receipt not verified' : 'Missing', href: '#hub-connection' },
  ...['Telegram', 'Email'].filter(provider => channelEnabled(capabilities.value, provider)).map(provider => ({ label: provider + ' channel', icon: provider === 'Email' ? 'mail' : 'send', ready: channels.value.some(row => row.channel === provider && row.enabled), state: channels.value.some(row => row.channel === provider && row.enabled) ? 'Enabled locally · confirm receipts in Activity' : 'Needs setup', href: '/desk/relay-channel' })),
  { label: 'WhatsApp channel', icon: 'message-circle', ready: channel.value?.configured, state: !loaded.value ? 'Not checked' : channel.value?.configured ? 'Enabled for this account' : 'Needs setup', href: '/desk/relay-channel' },
  { label: 'Business types and grouping', icon: 'users', ready: types.value.length > 0, state: !loaded.value ? 'Not checked' : types.value.length ? `${types.value.length} enabled types` : 'Needs setup', href: '/desk/relay-contact-type' },
  { label: 'Contacts and links', icon: 'users', state: 'Review identities, consent and permitted links', href: '#/contacts' },
  ...(capabilities.value.teams ? [{ label: 'Teams and access', icon: 'user-check', state: 'Review membership and permissions', href: '#/teams' }] : []),
  { label: 'Callback processing and recovery', icon: 'activity', state: 'Review received events and recovery', href: '#/activity' },
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
      <WorkspaceHeading description="Connect your account and prepare your workspace for conversations."><Button label="Refresh setup" icon-left="refresh-cw" :loading="busy" @click="run(load)" /></WorkspaceHeading>
      <ErrorMessage :message="error" /><LoadingRows v-if="busy && !loaded" :count="2" label="Checking configuration…" />
      <div class="v1-card-grid setup-checklist"><a v-for="(step, index) in checklist" :key="step.label" :href="step.href" class="v1-list-card" @click="followStep($event, step)"><span class="setup-step-top"><FeatherIcon :name="step.icon" :size="20" /><Badge :label="!loaded ? 'Not checked' : step.ready ? 'Ready' : 'Review'" :theme="loaded && step.ready ? 'green' : 'gray'" /></span><strong>{{ index + 1 }}. {{ step.label }}</strong><span>{{ step.state }}</span><small>Review setup <FeatherIcon name="arrow-up-right" :size="14" /></small></a></div>
      <form id="hub-connection" class="workflow-card" @submit.prevent="run(save)">
        <h2 class="text-lg font-semibold">Hub connection</h2><p class="text-sm">Save the Hub account first, verify this site’s binding, configure matching callback credentials in Hub, then confirm a received event in Activity.</p>
        <div class="settings-fields"><FormControl label="Hub MCP URL" v-model="config.url" :disabled="busy || !capabilities.configure" /><FormControl label="Hub account" v-model="config.account" :disabled="busy || !capabilities.configure" />
        <template v-if="capabilities.configure"><FormControl label="Replace API token" type="password" autocomplete="new-password" v-model="token" :placeholder="config.token_configured ? 'Saved — leave blank to keep' : 'Required'" :disabled="busy" /><FormControl label="Replace callback signing secret" type="password" autocomplete="new-password" v-model="callbackSecret" :placeholder="config.callback_configured ? 'Saved — leave blank to keep' : '32–512 printable characters'" :disabled="busy" />
        </template></div><template v-if="capabilities.configure">
          <div class="flex flex-wrap gap-3"><Button type="submit" label="Save connection" variant="solid" :disabled="busy || !loaded" /><Button label="Verify saved connection" :disabled="busy || !config.token_configured" @click="run(verify)" /></div>
        </template><p v-else>A System Manager can edit this connection.</p><p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>
      </form>
      <div v-if="config.can_switch_ai" class="workflow-card"><FormControl type="checkbox" label="Enable AI features" :model-value="Boolean(config.ai_enabled)" :disabled="busy || !loaded" @update:model-value="value => run(() => saveFeature('ai', value))" />
        <FormControl type="checkbox" label="Enable chat folders" :model-value="Boolean(config.folders_enabled)" :disabled="busy || !loaded" @update:model-value="value => run(() => saveFeature('folders', value))" />
        <FormControl type="checkbox" label="Enable teams" :model-value="Boolean(config.teams_enabled)" :disabled="busy || !loaded" @update:model-value="value => run(() => saveFeature('teams', value))" /></div>
      <form v-if="capabilities.configure && channelEnabled(capabilities, 'WhatsApp')" class="workflow-card" @submit.prevent="run(saveMargin)">
        <h2 class="font-semibold">WhatsApp billing</h2><p class="text-sm">Included in the rate per message on the Billing page.</p>
        <ErrorMessage :message="marginError" />
        <div class="settings-fields"><FormControl label="Service charge (%)" type="number" min="0" max="1000" step="0.01" v-model="margin" :disabled="busy" /></div>
        <div><Button type="submit" label="Save service charge" variant="solid" :disabled="busy || margin === ''" /></div>
        <p v-if="marginNotice" role="status" class="workspace-success">{{ marginNotice }}</p>
      </form>
      <div class="workflow-card"><h2 class="font-semibold">Channel readiness</h2><p>Identity credentials and provider verification are configured in Hub. Local enablement does not confirm callback delivery.</p><p v-for="item in channels" :key="item.name">{{ linkedTitle('Relay Channel', item.name, item.channel) }} <Badge :label="item.enabled ? 'Enabled locally' : 'Disabled'" /></p><a class="underline" href="#/activity">Review callback and delivery evidence</a></div>
      <div class="flex flex-wrap gap-3"><a class="v1-link" href="/desk/relay-channel">Configure channel</a><a class="v1-link" href="/desk/relay-contact-type">Configure business types and grouping</a><a class="v1-link" href="/desk/relay-contact-endpoint">Review endpoint bindings</a></div>
    </div>
  </section>
</template>
